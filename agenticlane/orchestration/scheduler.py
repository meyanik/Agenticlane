"""Scheduler + Branch Manager for AgenticLane.

Manages parallel branch exploration with divergence strategies,
pruning, and best-branch selection.

Key components:
- BranchState: status values for branch lifecycle
- Branch: Pydantic model tracking a single exploration branch
- DivergenceStrategy: Protocol for generating divergent knob sets
- DiverseSamplingStrategy: Latin Hypercube-like deterministic sampling
- MutationalStrategy: Perturbation of a base patch's config_vars
- BranchScheduler: orchestrates branch creation, scoring, pruning, selection
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# BranchState
# ---------------------------------------------------------------------------

BranchState = Literal["active", "pruned", "completed", "failed"]


# ---------------------------------------------------------------------------
# Branch model
# ---------------------------------------------------------------------------


class Branch(BaseModel):
    """Tracks the lifecycle and scoring of a single exploration branch."""

    branch_id: str  # e.g. "B0", "B1", "B2"
    status: BranchState = "active"
    workspace_root: Path
    init_patch: Optional[dict[str, object]] = None
    tip_stage: Optional[str] = None
    tip_attempt: int = 0
    best_composite_score: Optional[float] = None
    best_attempt: Optional[int] = None
    score_history: list[float] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    pruned_at: Optional[str] = None
    completed_at: Optional[str] = None


# ---------------------------------------------------------------------------
# DivergenceStrategy protocol + implementations
# ---------------------------------------------------------------------------


@runtime_checkable
class DivergenceStrategy(Protocol):
    """Protocol for generating divergent knob sets for branch initialization."""

    def generate(self, n_branches: int) -> list[dict[str, float]]:
        """Return *n_branches* divergent knob-set dicts."""
        ...


class DiverseSamplingStrategy:
    """Latin Hypercube-like sampling that produces spread-out knob sets.

    For each knob, the range is divided into *n* equal segments and the
    centre of each segment is selected.  The segments are then distributed
    across branches so that each branch gets one sample from each knob.

    This is a deterministic, reproducible approach.
    """

    def __init__(self, knob_ranges: dict[str, tuple[float, float]]) -> None:
        self.knob_ranges = knob_ranges

    def generate(self, n_branches: int) -> list[dict[str, float]]:
        if n_branches < 1:
            return []

        knob_names = sorted(self.knob_ranges.keys())

        if not knob_names:
            return [{} for _ in range(n_branches)]

        # For each knob, divide range into n equal segments, pick centres
        knob_samples: dict[str, list[float]] = {}
        for name in knob_names:
            lo, hi = self.knob_ranges[name]
            if n_branches == 1:
                knob_samples[name] = [(lo + hi) / 2.0]
            else:
                segment_width = (hi - lo) / n_branches
                knob_samples[name] = [
                    lo + segment_width * (i + 0.5) for i in range(n_branches)
                ]

        # Build per-branch dicts.
        # To get LHS-like spread, rotate the sample assignment per knob
        # so that branch i gets sample i for the first knob, sample (i+1) % n
        # for the second, etc.  This avoids all branches getting correlated
        # "low" or "high" combos.
        result: list[dict[str, float]] = []
        for branch_idx in range(n_branches):
            knob_set: dict[str, float] = {}
            for knob_offset, name in enumerate(knob_names):
                sample_idx = (branch_idx + knob_offset) % n_branches
                knob_set[name] = knob_samples[name][sample_idx]
            result.append(knob_set)

        return result


class MutationalStrategy:
    """Perturbation within a percentage range of a base patch's config_vars.

    Generates *n_branches* perturbed copies of a base config by applying
    deterministic, spread-out perturbations in [-perturbation_pct, +perturbation_pct].
    """

    def __init__(
        self,
        base_config_vars: dict[str, float],
        perturbation_pct: float = 0.15,
    ) -> None:
        self.base_config_vars = base_config_vars
        self.perturbation_pct = perturbation_pct

    def generate(self, n_branches: int) -> list[dict[str, float]]:
        if n_branches < 1:
            return []

        knob_names = sorted(self.base_config_vars.keys())
        if not knob_names:
            return [{} for _ in range(n_branches)]

        result: list[dict[str, float]] = []
        for branch_idx in range(n_branches):
            perturbed: dict[str, float] = {}
            for name in knob_names:
                base_val = self.base_config_vars[name]
                # Spread perturbations evenly across [-pct, +pct]
                if n_branches == 1:
                    frac = 0.0
                else:
                    frac = -self.perturbation_pct + (
                        2 * self.perturbation_pct * branch_idx / (n_branches - 1)
                    )
                perturbed[name] = base_val * (1.0 + frac)
            result.append(perturbed)

        return result


# ---------------------------------------------------------------------------
# BranchScheduler
# ---------------------------------------------------------------------------


class BranchScheduler:
    """Orchestrates parallel branch creation, scoring, pruning, and selection.

    Parameters
    ----------
    n_branches:
        Number of branches to create.
    output_dir:
        Root output directory; branches are created under ``output_dir/branches/B<i>/``.
    divergence_strategy:
        ``"diverse"`` for :class:`DiverseSamplingStrategy` (requires *knob_ranges*),
        ``"mutational"`` for :class:`MutationalStrategy`.
    knob_ranges:
        Required when *divergence_strategy* is ``"diverse"``.
    prune_delta_score:
        Score gap below best that triggers pruning consideration.
    prune_patience_attempts:
        Number of consecutive below-threshold attempts before pruning.
    """

    def __init__(
        self,
        *,
        n_branches: int = 3,
        output_dir: Path,
        divergence_strategy: str = "diverse",
        knob_ranges: Optional[dict[str, tuple[float, float]]] = None,
        prune_delta_score: float = 0.1,
        prune_patience_attempts: int = 3,
    ) -> None:
        self.n_branches = n_branches
        self.output_dir = output_dir
        self.divergence_strategy_name = divergence_strategy
        self.knob_ranges = knob_ranges or {}
        self.prune_delta_score = prune_delta_score
        self.prune_patience_attempts = prune_patience_attempts

        self._branches: dict[str, Branch] = {}

    # ------------------------------------------------------------------
    # Branch creation
    # ------------------------------------------------------------------

    def create_branches(
        self, init_patch: Optional[dict[str, object]] = None
    ) -> list[Branch]:
        """Create *n_branches* branches with divergent initial knob sets.

        If *init_patch* is supplied its ``config_vars`` are used as the base
        for the mutational strategy.  For the diverse strategy, *knob_ranges*
        set at init time are used directly.

        Returns the list of newly created :class:`Branch` objects.
        """
        strategy = self._build_strategy(init_patch)
        knob_sets = strategy.generate(self.n_branches)

        branches: list[Branch] = []
        start_idx = len(self._branches)
        for i, knob_set in enumerate(knob_sets):
            branch_id = f"B{start_idx + i}"
            workspace = self.output_dir / "branches" / branch_id
            workspace.mkdir(parents=True, exist_ok=True)

            patch: dict[str, object] = dict(init_patch) if init_patch else {}
            if knob_set:
                patch["config_vars"] = knob_set

            branch = Branch(
                branch_id=branch_id,
                workspace_root=workspace,
                init_patch=patch if patch else None,
            )
            self._branches[branch_id] = branch
            branches.append(branch)

        return branches

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_branch(self, branch_id: str) -> Branch:
        """Return the :class:`Branch` identified by *branch_id*.

        Raises ``KeyError`` if not found.
        """
        return self._branches[branch_id]

    def get_active_branches(self) -> list[Branch]:
        """Return all branches with status ``"active"``."""
        return [b for b in self._branches.values() if b.status == "active"]

    def select_best_branch(self) -> Optional[Branch]:
        """Return the branch with the highest ``best_composite_score``.

        Returns ``None`` if no branch has been scored.
        """
        scored = [
            b
            for b in self._branches.values()
            if b.best_composite_score is not None
        ]
        if not scored:
            return None
        return max(scored, key=lambda b: b.best_composite_score or 0.0)

    def get_branch_summary(self) -> dict[str, object]:
        """Return a summary dict describing all branches."""
        return {
            "total_branches": len(self._branches),
            "active": len(self.get_active_branches()),
            "pruned": len(
                [b for b in self._branches.values() if b.status == "pruned"]
            ),
            "completed": len(
                [b for b in self._branches.values() if b.status == "completed"]
            ),
            "failed": len(
                [b for b in self._branches.values() if b.status == "failed"]
            ),
            "branches": {
                bid: {
                    "status": b.status,
                    "best_score": b.best_composite_score,
                    "tip_stage": b.tip_stage,
                    "tip_attempt": b.tip_attempt,
                    "score_count": len(b.score_history),
                }
                for bid, b in self._branches.items()
            },
        }

    # ------------------------------------------------------------------
    # Score / lifecycle updates
    # ------------------------------------------------------------------

    def update_branch_score(
        self, branch_id: str, score: float, stage: str, attempt: int
    ) -> None:
        """Record a new score for *branch_id*.

        Updates ``tip_stage``, ``tip_attempt``, ``score_history``, and
        ``best_composite_score`` / ``best_attempt`` if this is a new best.
        """
        branch = self._branches[branch_id]
        branch.tip_stage = stage
        branch.tip_attempt = attempt
        branch.score_history.append(score)

        if branch.best_composite_score is None or score > branch.best_composite_score:
            branch.best_composite_score = score
            branch.best_attempt = attempt

    def prune_branch(self, branch_id: str, reason: str = "") -> None:
        """Mark *branch_id* as pruned."""
        branch = self._branches[branch_id]
        branch.status = "pruned"
        branch.pruned_at = datetime.now(timezone.utc).isoformat()

    def complete_branch(self, branch_id: str) -> None:
        """Mark *branch_id* as completed."""
        branch = self._branches[branch_id]
        branch.status = "completed"
        branch.completed_at = datetime.now(timezone.utc).isoformat()

    def fail_branch(self, branch_id: str, reason: str = "") -> None:
        """Mark *branch_id* as failed."""
        branch = self._branches[branch_id]
        branch.status = "failed"

    # ------------------------------------------------------------------
    # Pruning logic
    # ------------------------------------------------------------------

    def should_prune(self, branch_id: str) -> bool:
        """Decide whether *branch_id* should be pruned.

        A branch is prunable when:

        1. It has at least ``prune_patience_attempts`` scores recorded.
        2. Every one of the last ``prune_patience_attempts`` scores is below
           ``best_global_score - prune_delta_score``.
        """
        branch = self._branches[branch_id]
        if len(branch.score_history) < self.prune_patience_attempts:
            return False

        best_global = self._best_global_score()
        if best_global is None:
            return False

        threshold = best_global - self.prune_delta_score
        tail = branch.score_history[-self.prune_patience_attempts :]
        return all(s < threshold for s in tail)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _best_global_score(self) -> Optional[float]:
        """Return the highest ``best_composite_score`` across all branches."""
        scores = [
            b.best_composite_score
            for b in self._branches.values()
            if b.best_composite_score is not None
        ]
        return max(scores) if scores else None

    def _build_strategy(
        self, init_patch: Optional[dict[str, object]] = None
    ) -> DivergenceStrategy:
        """Instantiate the configured divergence strategy."""
        if self.divergence_strategy_name == "mutational":
            base_vars: dict[str, float] = {}
            if init_patch and "config_vars" in init_patch:
                raw = init_patch["config_vars"]
                if isinstance(raw, dict):
                    base_vars = {
                        str(k): float(v)
                        for k, v in raw.items()
                        if isinstance(v, (int, float))
                    }
            return MutationalStrategy(base_config_vars=base_vars)

        # Default: diverse sampling
        return DiverseSamplingStrategy(knob_ranges=self.knob_ranges)
