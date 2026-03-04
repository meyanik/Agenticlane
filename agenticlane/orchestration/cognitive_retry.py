"""Cognitive retry loop for AgenticLane.

When a patch is rejected by ConstraintGuard (or schema/knob validation),
this constitutes a "cognitive retry" that doesn't burn a physical attempt.
The agent gets feedback about why the patch was rejected and can try again.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from agenticlane.config.models import BudgetConfig
from agenticlane.schemas.patch import Patch, PatchRejected

logger = logging.getLogger(__name__)


class CognitiveBudgetExhaustedError(Exception):
    """Raised when cognitive retries are exhausted for an attempt."""


# Backward-compatible alias
CognitiveBudgetExhausted = CognitiveBudgetExhaustedError


@dataclass
class CognitiveRetryState:
    """State of the cognitive retry loop for one physical attempt.

    Tracks how many cognitive retries have been used, and records every
    proposal (patch + optional rejection) for reproducibility.
    """

    attempt_dir: Path
    budget: int  # cognitive_retries_per_attempt
    used: int = 0
    proposals: list[tuple[Patch, PatchRejected | None]] = field(
        default_factory=list,
    )

    @property
    def remaining(self) -> int:
        """Number of cognitive retries still available."""
        return max(0, self.budget - self.used)

    @property
    def exhausted(self) -> bool:
        """Whether the cognitive retry budget is used up."""
        return self.used >= self.budget


class CognitiveRetryLoop:
    """Manages cognitive retry budget and proposal recording.

    The cognitive retry loop sits between patch generation (by the agent)
    and physical execution (via the adapter).  When a patch fails
    pre-execution validation (schema, knob range, ConstraintGuard), the
    rejection counts as a cognitive retry rather than a physical attempt.

    Two budget levels are tracked:

    * **Per-attempt budget** (``cognitive_retries_per_attempt``): limits
      retries within a single physical attempt.
    * **Per-stage budget** (``max_total_cognitive_retries_per_stage``):
      caps the total cognitive retries across all attempts of a stage.

    Usage::

        loop = CognitiveRetryLoop(budget_config)
        state = loop.begin_attempt(attempt_dir)

        while not state.exhausted:
            patch = agent.propose_patch(feedback=last_rejection)
            result = loop.try_patch(state, patch, validator)
            if result is None:
                # Patch accepted!
                break
            # result is PatchRejected -- try again
    """

    def __init__(self, budget_config: BudgetConfig) -> None:
        self.budget = budget_config
        self._stage_total_cognitive_retries: int = 0

    @property
    def stage_total_cognitive_retries(self) -> int:
        """Total cognitive retries used in the current stage."""
        return self._stage_total_cognitive_retries

    def begin_attempt(self, attempt_dir: Path) -> CognitiveRetryState:
        """Begin cognitive retry tracking for a new physical attempt.

        Creates the ``proposals/`` subdirectory inside the attempt directory
        and returns a fresh :class:`CognitiveRetryState`.

        Args:
            attempt_dir: Filesystem path to the attempt directory.

        Returns:
            A new ``CognitiveRetryState`` with full budget.
        """
        proposals_dir = attempt_dir / "proposals"
        proposals_dir.mkdir(parents=True, exist_ok=True)
        return CognitiveRetryState(
            attempt_dir=attempt_dir,
            budget=self.budget.cognitive_retries_per_attempt,
        )

    def try_patch(
        self,
        state: CognitiveRetryState,
        patch: Patch,
        validator: Callable[[Patch], PatchRejected | None],
    ) -> PatchRejected | None:
        """Try a patch through validation.

        Saves the proposed patch to disk, runs the ``validator`` callable,
        and records the outcome.

        Args:
            state: Current cognitive retry state for this physical attempt.
            patch: The patch to validate.
            validator: A callable that returns ``None`` when the patch is
                accepted, or a :class:`PatchRejected` when it is not.

        Returns:
            ``None`` if the patch passed validation, or a
            :class:`PatchRejected` describing why it was rejected.

        Raises:
            CognitiveBudgetExhausted: If the per-stage cognitive retry
                budget is exceeded.
        """
        # Check stage-level budget
        if (
            self._stage_total_cognitive_retries
            >= self.budget.max_total_cognitive_retries_per_stage
        ):
            raise CognitiveBudgetExhaustedError(
                f"Stage cognitive retry budget exhausted "
                f"({self._stage_total_cognitive_retries} used)"
            )

        # Validate the patch
        rejection = validator(patch)

        # Record the proposal
        try_num = state.used + 1
        try_dir = state.attempt_dir / "proposals" / f"try_{try_num:03d}"
        try_dir.mkdir(parents=True, exist_ok=True)
        (try_dir / "patch_proposed.json").write_text(
            patch.model_dump_json(indent=2),
        )

        if rejection is not None:
            (try_dir / "patch_rejected.json").write_text(
                rejection.model_dump_json(indent=2),
            )
            state.used += 1
            self._stage_total_cognitive_retries += 1
            state.proposals.append((patch, rejection))
            logger.info(
                "Cognitive retry %d/%d: rejected (%s)",
                state.used,
                state.budget,
                rejection.reason_code,
            )

            if state.exhausted:
                # Write final rejection marker
                (state.attempt_dir / "patch_rejected_final.json").write_text(
                    rejection.model_dump_json(indent=2),
                )

            return rejection

        # Patch accepted
        (state.attempt_dir / "patch.json").write_text(
            patch.model_dump_json(indent=2),
        )
        state.proposals.append((patch, None))
        logger.info("Patch accepted on cognitive try %d", try_num)
        return None

    def reset_stage(self) -> None:
        """Reset stage-level counters (call between stages)."""
        self._stage_total_cognitive_retries = 0
