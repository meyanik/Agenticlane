"""Tests for the cognitive retry loop (P2.5).

Verifies:
- Budget tracking per attempt and per stage
- Proposal recording (patch_proposed.json, patch_rejected.json)
- Budget exhaustion raises CognitiveBudgetExhausted
- Accepted patches written to patch.json
- Final rejection written to patch_rejected_final.json
- Stage total counter and reset_stage()
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agenticlane.config.models import BudgetConfig
from agenticlane.orchestration.cognitive_retry import (
    CognitiveBudgetExhausted,
    CognitiveRetryLoop,
    CognitiveRetryState,
)
from agenticlane.schemas.patch import Patch, PatchRejected

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_patch(patch_id: str = "test-patch-001") -> Patch:
    """Create a minimal valid Patch for testing."""
    return Patch(
        patch_id=patch_id,
        stage="FLOORPLAN",
        config_vars={"FP_CORE_UTIL": 45},
    )


def _make_rejection(
    patch_id: str = "test-patch-001",
    reason: str = "locked_constraint",
) -> PatchRejected:
    """Create a PatchRejected for testing."""
    return PatchRejected(
        patch_id=patch_id,
        stage="FLOORPLAN",
        reason_code=reason,
        offending_channel="config_vars",
        remediation_hint="Do not modify locked variables.",
    )


def _always_accept(patch: Patch) -> PatchRejected | None:
    """Validator that always accepts."""
    return None


def _always_reject(patch: Patch) -> PatchRejected | None:
    """Validator that always rejects."""
    return _make_rejection(patch_id=patch.patch_id)


def _reject_then_accept(reject_count: int):
    """Return a validator that rejects the first N tries, then accepts."""
    state = {"count": 0}

    def validator(patch: Patch) -> PatchRejected | None:
        state["count"] += 1
        if state["count"] <= reject_count:
            return _make_rejection(patch_id=patch.patch_id)
        return None

    return validator


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCognitiveRetryLoop:
    """Tests for CognitiveRetryLoop."""

    def test_valid_patch_accepted_first_try(self, tmp_path: Path) -> None:
        """Valid patch passes all checks, returned immediately."""
        budget = BudgetConfig(
            cognitive_retries_per_attempt=3,
            max_total_cognitive_retries_per_stage=30,
        )
        loop = CognitiveRetryLoop(budget)
        state = loop.begin_attempt(tmp_path / "attempt_001")

        patch = _make_patch()
        result = loop.try_patch(state, patch, _always_accept)

        assert result is None
        assert state.used == 0
        assert state.remaining == 3
        assert not state.exhausted

    def test_invalid_patch_retried(self, tmp_path: Path) -> None:
        """Invalid patch triggers retry with feedback."""
        budget = BudgetConfig(
            cognitive_retries_per_attempt=3,
            max_total_cognitive_retries_per_stage=30,
        )
        loop = CognitiveRetryLoop(budget)
        state = loop.begin_attempt(tmp_path / "attempt_001")

        validator = _reject_then_accept(reject_count=2)
        patch = _make_patch()

        # First try: rejected
        result = loop.try_patch(state, patch, validator)
        assert result is not None
        assert result.reason_code == "locked_constraint"

        # Second try: rejected
        result = loop.try_patch(state, patch, validator)
        assert result is not None

        # Third try: accepted
        result = loop.try_patch(state, patch, validator)
        assert result is None

    def test_budget_tracking(self, tmp_path: Path) -> None:
        """cognitive_budget decremented per retry."""
        budget = BudgetConfig(
            cognitive_retries_per_attempt=3,
            max_total_cognitive_retries_per_stage=30,
        )
        loop = CognitiveRetryLoop(budget)
        state = loop.begin_attempt(tmp_path / "attempt_001")

        patch = _make_patch()

        assert state.used == 0
        assert state.remaining == 3

        loop.try_patch(state, patch, _always_reject)
        assert state.used == 1
        assert state.remaining == 2

        loop.try_patch(state, patch, _always_reject)
        assert state.used == 2
        assert state.remaining == 1

        loop.try_patch(state, patch, _always_reject)
        assert state.used == 3
        assert state.remaining == 0
        assert state.exhausted

    def test_budget_exhaustion(self, tmp_path: Path) -> None:
        """After max retries, CognitiveBudgetExhausted is raised."""
        budget = BudgetConfig(
            cognitive_retries_per_attempt=2,
            max_total_cognitive_retries_per_stage=2,
        )
        loop = CognitiveRetryLoop(budget)
        state = loop.begin_attempt(tmp_path / "attempt_001")

        patch = _make_patch()

        # Use up both retries
        loop.try_patch(state, patch, _always_reject)
        loop.try_patch(state, patch, _always_reject)

        # Next call hits stage budget
        with pytest.raises(CognitiveBudgetExhausted):
            loop.try_patch(state, patch, _always_reject)

    def test_proposal_stored(self, tmp_path: Path) -> None:
        """Each proposal saved in attempt_dir/proposals/try_001/."""
        budget = BudgetConfig(
            cognitive_retries_per_attempt=3,
            max_total_cognitive_retries_per_stage=30,
        )
        loop = CognitiveRetryLoop(budget)
        attempt_dir = tmp_path / "attempt_001"
        state = loop.begin_attempt(attempt_dir)

        patch = _make_patch()

        # Rejected proposal
        loop.try_patch(state, patch, _always_reject)

        # Check proposal directory structure
        try_dir = attempt_dir / "proposals" / "try_001"
        assert try_dir.exists()
        assert (try_dir / "patch_proposed.json").exists()

        # Verify the proposed patch content
        proposed = json.loads((try_dir / "patch_proposed.json").read_text())
        assert proposed["patch_id"] == "test-patch-001"

    def test_proposal_includes_rejection_reason(
        self, tmp_path: Path
    ) -> None:
        """Rejected proposals have patch_rejected.json."""
        budget = BudgetConfig(
            cognitive_retries_per_attempt=3,
            max_total_cognitive_retries_per_stage=30,
        )
        loop = CognitiveRetryLoop(budget)
        attempt_dir = tmp_path / "attempt_001"
        state = loop.begin_attempt(attempt_dir)

        patch = _make_patch()
        loop.try_patch(state, patch, _always_reject)

        try_dir = attempt_dir / "proposals" / "try_001"
        rejected_path = try_dir / "patch_rejected.json"
        assert rejected_path.exists()

        rejected = json.loads(rejected_path.read_text())
        assert rejected["reason_code"] == "locked_constraint"
        assert rejected["offending_channel"] == "config_vars"
        assert rejected["remediation_hint"] != ""

    def test_stage_total_budget(self, tmp_path: Path) -> None:
        """max_total_cognitive_retries_per_stage enforced across attempts."""
        budget = BudgetConfig(
            cognitive_retries_per_attempt=2,
            max_total_cognitive_retries_per_stage=3,
        )
        loop = CognitiveRetryLoop(budget)

        # Attempt 1: use 2 cognitive retries
        state1 = loop.begin_attempt(tmp_path / "attempt_001")
        patch = _make_patch()
        loop.try_patch(state1, patch, _always_reject)
        loop.try_patch(state1, patch, _always_reject)
        assert loop.stage_total_cognitive_retries == 2

        # Attempt 2: use 1 more, then hit stage limit
        state2 = loop.begin_attempt(tmp_path / "attempt_002")
        loop.try_patch(state2, patch, _always_reject)
        assert loop.stage_total_cognitive_retries == 3

        # Next call should hit stage budget
        with pytest.raises(CognitiveBudgetExhausted):
            loop.try_patch(state2, patch, _always_reject)

    def test_reset_stage(self, tmp_path: Path) -> None:
        """reset_stage() clears stage counter."""
        budget = BudgetConfig(
            cognitive_retries_per_attempt=3,
            max_total_cognitive_retries_per_stage=5,
        )
        loop = CognitiveRetryLoop(budget)

        state = loop.begin_attempt(tmp_path / "attempt_001")
        patch = _make_patch()
        loop.try_patch(state, patch, _always_reject)
        loop.try_patch(state, patch, _always_reject)

        assert loop.stage_total_cognitive_retries == 2

        loop.reset_stage()
        assert loop.stage_total_cognitive_retries == 0

    def test_accepted_patch_written(self, tmp_path: Path) -> None:
        """Accepted patch saved as attempt_dir/patch.json."""
        budget = BudgetConfig(
            cognitive_retries_per_attempt=3,
            max_total_cognitive_retries_per_stage=30,
        )
        loop = CognitiveRetryLoop(budget)
        attempt_dir = tmp_path / "attempt_001"
        state = loop.begin_attempt(attempt_dir)

        patch = _make_patch(patch_id="accepted-patch-42")
        loop.try_patch(state, patch, _always_accept)

        patch_path = attempt_dir / "patch.json"
        assert patch_path.exists()

        saved = json.loads(patch_path.read_text())
        assert saved["patch_id"] == "accepted-patch-42"

    def test_final_rejection_written(self, tmp_path: Path) -> None:
        """When exhausted, patch_rejected_final.json created."""
        budget = BudgetConfig(
            cognitive_retries_per_attempt=2,
            max_total_cognitive_retries_per_stage=30,
        )
        loop = CognitiveRetryLoop(budget)
        attempt_dir = tmp_path / "attempt_001"
        state = loop.begin_attempt(attempt_dir)

        patch = _make_patch()

        # Use up budget
        loop.try_patch(state, patch, _always_reject)
        loop.try_patch(state, patch, _always_reject)

        assert state.exhausted
        final_path = attempt_dir / "patch_rejected_final.json"
        assert final_path.exists()

        final = json.loads(final_path.read_text())
        assert final["reason_code"] == "locked_constraint"


class TestCognitiveRetryState:
    """Unit tests for the CognitiveRetryState dataclass."""

    def test_initial_state(self, tmp_path: Path) -> None:
        """Freshly created state has full budget."""
        state = CognitiveRetryState(
            attempt_dir=tmp_path,
            budget=3,
        )
        assert state.used == 0
        assert state.remaining == 3
        assert not state.exhausted
        assert state.proposals == []

    def test_exhausted_when_used_equals_budget(
        self, tmp_path: Path
    ) -> None:
        """State is exhausted when used == budget."""
        state = CognitiveRetryState(
            attempt_dir=tmp_path,
            budget=2,
            used=2,
        )
        assert state.exhausted
        assert state.remaining == 0

    def test_remaining_never_negative(self, tmp_path: Path) -> None:
        """remaining is floored at 0, never negative."""
        state = CognitiveRetryState(
            attempt_dir=tmp_path,
            budget=1,
            used=5,
        )
        assert state.remaining == 0
