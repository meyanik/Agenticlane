"""Pruning + Selection for AgenticLane (P5.3).

Score-based branch pruning and best-branch selection logic that
integrates with the BranchScheduler.  The :class:`PruningEngine`
evaluates branches against configurable thresholds and patience
windows to decide which branches to prune and which to keep.

Key components
--------------
- PruneDecision: dataclass capturing the outcome of a single-branch evaluation
- SelectionResult: dataclass capturing the winner-selection outcome
- PruningEngine: stateless engine that scores, prunes, and selects branches
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PruneDecision:
    """Result of a pruning evaluation."""

    branch_id: str
    should_prune: bool
    reason: str = ""
    current_score: float | None = None
    best_global_score: float | None = None
    score_gap: float | None = None


@dataclass
class SelectionResult:
    """Result of best-branch selection."""

    winning_branch_id: str | None = None
    winning_score: float | None = None
    all_scores: dict[str, float] = field(default_factory=dict)
    pruned_branches: list[str] = field(default_factory=list)
    reason: str = ""


class PruningEngine:
    """Score-based branch pruning and selection engine.

    Evaluates branches against configurable thresholds and patience
    windows to decide which branches to prune and which to keep.
    """

    def __init__(
        self,
        *,
        prune_delta_score: float = 0.1,
        prune_patience_attempts: int = 3,
        min_attempts_before_prune: int = 2,
    ) -> None:
        self._delta = prune_delta_score
        self._patience = prune_patience_attempts
        self._min_attempts = min_attempts_before_prune

    def evaluate_branch(
        self,
        branch_scores: list[float],
        best_global_score: float,
    ) -> PruneDecision:
        """Evaluate whether a single branch should be pruned.

        A branch is prunable when:

        1. It has >= *min_attempts_before_prune* scores.
        2. The last *prune_patience_attempts* scores are **all** below
           ``best_global_score - prune_delta_score``.
        """
        branch_id = ""  # Will be set by caller

        if len(branch_scores) < self._min_attempts:
            return PruneDecision(
                branch_id=branch_id,
                should_prune=False,
                reason="insufficient_attempts",
                current_score=branch_scores[-1] if branch_scores else None,
                best_global_score=best_global_score,
            )

        threshold = best_global_score - self._delta
        recent = branch_scores[-self._patience :]

        if len(recent) < self._patience:
            return PruneDecision(
                branch_id=branch_id,
                should_prune=False,
                reason="within_patience_window",
                current_score=branch_scores[-1],
                best_global_score=best_global_score,
            )

        all_below = all(s < threshold for s in recent)

        if all_below:
            gap = best_global_score - branch_scores[-1]
            return PruneDecision(
                branch_id=branch_id,
                should_prune=True,
                reason=f"underperforming_for_{self._patience}_attempts",
                current_score=branch_scores[-1],
                best_global_score=best_global_score,
                score_gap=gap,
            )

        return PruneDecision(
            branch_id=branch_id,
            should_prune=False,
            reason="within_threshold",
            current_score=branch_scores[-1],
            best_global_score=best_global_score,
        )

    def evaluate_all_branches(
        self,
        branch_scores: dict[str, list[float]],
    ) -> list[PruneDecision]:
        """Evaluate all branches and return pruning decisions.

        Args:
            branch_scores: Dict of branch_id -> list of scores.

        Returns:
            List of :class:`PruneDecision` for each branch.
        """
        if not branch_scores:
            return []

        # Find best global score across all branches
        all_scores = [s for scores in branch_scores.values() for s in scores]
        best_global = max(all_scores) if all_scores else 0.0

        decisions: list[PruneDecision] = []
        for branch_id, scores in sorted(branch_scores.items()):
            decision = self.evaluate_branch(scores, best_global)
            decision.branch_id = branch_id
            decisions.append(decision)

        return decisions

    def select_winner(
        self,
        branch_scores: dict[str, list[float]],
        pruned_ids: set[str] | None = None,
    ) -> SelectionResult:
        """Select the best branch based on highest final score.

        Args:
            branch_scores: Dict of branch_id -> list of scores.
            pruned_ids: Set of branch IDs that have been pruned (excluded).

        Returns:
            :class:`SelectionResult` with winning branch info.
        """
        pruned = pruned_ids or set()

        active_scores: dict[str, float] = {}
        for branch_id, scores in branch_scores.items():
            if branch_id not in pruned and scores:
                active_scores[branch_id] = max(scores)  # best score for branch

        if not active_scores:
            return SelectionResult(
                reason="no_active_branches_with_scores",
                pruned_branches=sorted(pruned),
            )

        winner_id = max(active_scores, key=lambda k: active_scores[k])

        return SelectionResult(
            winning_branch_id=winner_id,
            winning_score=active_scores[winner_id],
            all_scores=active_scores,
            pruned_branches=sorted(pruned),
            reason="highest_best_score",
        )

    def get_pruning_summary(
        self,
        decisions: list[PruneDecision],
    ) -> dict[str, Any]:
        """Generate a summary of pruning decisions."""
        to_prune = [d for d in decisions if d.should_prune]
        to_keep = [d for d in decisions if not d.should_prune]

        return {
            "total_branches": len(decisions),
            "to_prune": len(to_prune),
            "to_keep": len(to_keep),
            "prune_ids": [d.branch_id for d in to_prune],
            "keep_ids": [d.branch_id for d in to_keep],
            "decisions": [
                {
                    "branch_id": d.branch_id,
                    "should_prune": d.should_prune,
                    "reason": d.reason,
                    "current_score": d.current_score,
                    "score_gap": d.score_gap,
                }
                for d in decisions
            ],
        }
