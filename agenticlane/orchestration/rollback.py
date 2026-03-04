"""Cross-stage rollback engine for AgenticLane.

Enables the master agent to decide whether to retry the current stage,
roll back to an earlier stage, or stop the run entirely.  Integrates
with the stage graph (``graph.py``) for valid rollback edges and with
the LLM provider for master-agent decisions.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal, Optional

from pydantic import BaseModel, Field

from agenticlane.agents.llm_provider import LLMProvider
from agenticlane.config.models import AgenticLaneConfig
from agenticlane.orchestration.agent_loop import AttemptOutcome
from agenticlane.orchestration.graph import STAGE_ORDER, get_rollback_targets, get_stage_index
from agenticlane.schemas.evidence import EvidencePack

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class RollbackDecision(BaseModel):
    """Master-agent decision on how to proceed after a stage failure."""

    action: Literal["retry", "rollback", "stop"] = Field(
        default="retry",
        description="What to do: retry the current stage, rollback to an earlier stage, or stop.",
    )
    target_stage: Optional[str] = Field(
        default=None,
        description="Stage to rollback to (required when action=='rollback').",
    )
    reason: str = Field(
        default="",
        description="Explanation for the decision.",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confidence in the decision (0-1).",
    )


@dataclass
class StageCheckpoint:
    """Snapshot of a stage's state at a particular attempt."""

    stage: str
    attempt: int
    composite_score: float
    state_in_path: Optional[str] = None
    attempt_dir: Optional[str] = None


# ---------------------------------------------------------------------------
# Rollback engine
# ---------------------------------------------------------------------------


class RollbackEngine:
    """Cross-stage rollback engine.

    Decision logic:
    1. If no rollback targets exist for the failed stage -> retry.
    2. If scores are still improving (latest > mean of previous) -> retry.
    3. Otherwise, ask the master LLM for a decision.
    """

    def __init__(self, llm_provider: LLMProvider, config: AgenticLaneConfig) -> None:
        self.llm_provider = llm_provider
        self.config = config

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #

    async def decide(
        self,
        failed_stage: str,
        attempt_outcomes: list[AttemptOutcome],
        evidence: EvidencePack,
        checkpoints: dict[str, list[StageCheckpoint]],
    ) -> RollbackDecision:
        """Decide whether to retry, rollback, or stop.

        Args:
            failed_stage: Name of the stage that just failed.
            attempt_outcomes: Outcomes from attempts on this stage.
            evidence: Evidence from the most recent failed attempt.
            checkpoints: Per-stage checkpoint history (stage -> checkpoints).

        Returns:
            A ``RollbackDecision`` indicating the chosen action.
        """
        targets = get_rollback_targets(failed_stage)

        # Rule 1: No rollback targets -> always retry
        if not targets:
            logger.info(
                "Stage %s has no rollback targets; deciding retry.",
                failed_stage,
            )
            return RollbackDecision(
                action="retry",
                reason=f"Stage {failed_stage} has no rollback targets.",
                confidence=1.0,
            )

        # Rule 2: If scores are still improving, prefer retry
        if self._is_improving(attempt_outcomes):
            logger.info(
                "Scores still improving for %s; deciding retry.",
                failed_stage,
            )
            return RollbackDecision(
                action="retry",
                reason="Scores are still improving across recent attempts.",
                confidence=0.8,
            )

        # Rule 3: Ask the master LLM
        decision = await self._ask_master(
            failed_stage=failed_stage,
            attempt_outcomes=attempt_outcomes,
            evidence=evidence,
            targets=targets,
            checkpoints=checkpoints,
        )

        if decision is not None:
            return decision

        # Fallback: if LLM returns None, default to retry
        logger.warning(
            "Master LLM returned None for %s; defaulting to retry.",
            failed_stage,
        )
        return RollbackDecision(
            action="retry",
            reason="Master LLM did not provide a decision; defaulting to retry.",
            confidence=0.3,
        )

    def select_best_checkpoint(
        self,
        target_stage: str,
        checkpoints: dict[str, list[StageCheckpoint]],
    ) -> Optional[StageCheckpoint]:
        """Select the checkpoint with the highest composite_score for *target_stage*.

        Returns:
            The best ``StageCheckpoint``, or ``None`` if no checkpoints exist
            for the target stage.
        """
        stage_checkpoints = checkpoints.get(target_stage, [])
        if not stage_checkpoints:
            return None
        return max(stage_checkpoints, key=lambda cp: cp.composite_score)

    def get_rollback_path(
        self,
        from_stage: str,
        to_stage: str,
    ) -> list[str]:
        """Return the stages that need to be re-run from *to_stage* to *from_stage* (inclusive).

        Uses ``STAGE_ORDER`` to compute all stages between (and including)
        *to_stage* and *from_stage*.

        Args:
            from_stage: The stage that failed (upper bound, inclusive).
            to_stage: The rollback target (lower bound, inclusive).

        Returns:
            Ordered list of stage names from *to_stage* through *from_stage*.

        Raises:
            ValueError: If either stage is unknown or *to_stage* comes after
                *from_stage* in the canonical order.
        """
        from_idx = get_stage_index(from_stage)
        to_idx = get_stage_index(to_stage)

        if to_idx > from_idx:
            raise ValueError(
                f"Rollback target '{to_stage}' (index {to_idx}) comes after "
                f"failed stage '{from_stage}' (index {from_idx}) in STAGE_ORDER."
            )

        return STAGE_ORDER[to_idx : from_idx + 1]

    # --------------------------------------------------------------------- #
    # Internals
    # --------------------------------------------------------------------- #

    @staticmethod
    def _is_improving(attempt_outcomes: list[AttemptOutcome]) -> bool:
        """Return True if the latest score exceeds the mean of all previous scores."""
        scores = [o.composite_score for o in attempt_outcomes if o.composite_score > 0.0]
        if len(scores) < 2:
            return False

        latest = scores[-1]
        previous_mean = sum(scores[:-1]) / len(scores[:-1])
        return latest > previous_mean

    async def _ask_master(
        self,
        failed_stage: str,
        attempt_outcomes: list[AttemptOutcome],
        evidence: EvidencePack,
        targets: list[str],
        checkpoints: dict[str, list[StageCheckpoint]],
    ) -> Optional[RollbackDecision]:
        """Ask the master LLM for a rollback decision.

        Builds a prompt with the failed stage context, evidence summary,
        available rollback targets, and recent scores, then requests a
        structured ``RollbackDecision`` response.
        """
        # Build score history text
        score_lines: list[str] = []
        for outcome in attempt_outcomes:
            score_lines.append(
                f"  Attempt {outcome.attempt_num}: score={outcome.composite_score:.4f} "
                f"judge={outcome.judge_result}"
            )
        score_history = "\n".join(score_lines) if score_lines else "  (no attempts)"

        # Build target info text
        target_info_lines: list[str] = []
        for t in targets:
            best = self.select_best_checkpoint(t, checkpoints)
            if best is not None:
                target_info_lines.append(
                    f"  - {t}: best checkpoint score={best.composite_score:.4f} "
                    f"(attempt {best.attempt})"
                )
            else:
                target_info_lines.append(f"  - {t}: no checkpoint available")
        target_info = "\n".join(target_info_lines)

        # Build evidence summary
        error_lines = [f"  - [{e.severity}] {e.message}" for e in evidence.errors[:5]]
        error_summary = "\n".join(error_lines) if error_lines else "  (no errors)"

        prompt = (
            f"You are the master agent for an ASIC PnR flow.\n\n"
            f"Stage '{failed_stage}' has failed. Decide what to do next.\n\n"
            f"## Recent Attempt Scores\n{score_history}\n\n"
            f"## Available Rollback Targets\n{target_info}\n\n"
            f"## Evidence Summary\n"
            f"Execution status: {evidence.execution_status}\n"
            f"Errors:\n{error_summary}\n\n"
            f"## Instructions\n"
            f"Choose one of:\n"
            f"- 'retry': Retry the current stage with a new patch.\n"
            f"- 'rollback': Roll back to one of the available target stages.\n"
            f"- 'stop': Abort the run (only if the situation is unrecoverable).\n\n"
            f"If you choose 'rollback', specify which target_stage to roll back to.\n"
            f"Provide your reasoning and confidence (0-1).\n\n"
            f"IMPORTANT: Respond with ONLY a JSON object, no markdown or explanation outside the JSON.\n"
            f"Example: {{\"action\": \"retry\", \"target_stage\": null, \"reason\": \"...\", \"confidence\": 0.8}}\n"
        )

        master_model = self.config.llm.models.master
        decision = await self.llm_provider.generate(
            prompt=prompt,
            response_model=RollbackDecision,
            model=master_model,
            stage=failed_stage,
            role="master",
        )

        return decision
