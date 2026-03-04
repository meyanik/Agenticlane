"""P4.1 Rollback Engine tests."""
from __future__ import annotations

import pytest

from agenticlane.agents.mock_llm import MockLLMProvider
from agenticlane.config.models import AgenticLaneConfig
from agenticlane.orchestration.agent_loop import AttemptOutcome
from agenticlane.orchestration.rollback import (
    RollbackDecision,
    RollbackEngine,
    StageCheckpoint,
)
from agenticlane.schemas.evidence import EvidencePack

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_outcome(
    attempt: int,
    score: float = 0.0,
    judge: str = "FAIL",
) -> AttemptOutcome:
    return AttemptOutcome(
        attempt_num=attempt,
        composite_score=score,
        judge_result=judge,
    )


def _make_evidence(stage: str = "ROUTE_DETAILED", attempt: int = 1) -> EvidencePack:
    return EvidencePack(
        stage=stage,
        attempt=attempt,
        execution_status="tool_crash",
    )


def _make_checkpoint(
    stage: str,
    attempt: int,
    score: float,
    state_in_path: str | None = None,
    attempt_dir: str | None = None,
) -> StageCheckpoint:
    return StageCheckpoint(
        stage=stage,
        attempt=attempt,
        composite_score=score,
        state_in_path=state_in_path,
        attempt_dir=attempt_dir,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def llm() -> MockLLMProvider:
    return MockLLMProvider()


@pytest.fixture()
def config() -> AgenticLaneConfig:
    return AgenticLaneConfig()


@pytest.fixture()
def engine(llm: MockLLMProvider, config: AgenticLaneConfig) -> RollbackEngine:
    return RollbackEngine(llm_provider=llm, config=config)


# ---------------------------------------------------------------------------
# Tests: get_rollback_path
# ---------------------------------------------------------------------------


class TestGetRollbackPath:
    def test_rollback_path_computed(self, engine: RollbackEngine) -> None:
        """ROUTE_DETAILED -> FLOORPLAN should include all intermediate stages."""
        path = engine.get_rollback_path("ROUTE_DETAILED", "FLOORPLAN")
        expected = [
            "FLOORPLAN",
            "PDN",
            "PLACE_GLOBAL",
            "PLACE_DETAILED",
            "CTS",
            "ROUTE_GLOBAL",
            "ROUTE_DETAILED",
        ]
        assert path == expected

    def test_get_rollback_path_same_stage(self, engine: RollbackEngine) -> None:
        """from_stage == to_stage should return [to_stage]."""
        path = engine.get_rollback_path("FLOORPLAN", "FLOORPLAN")
        assert path == ["FLOORPLAN"]

    def test_rollback_path_adjacent(self, engine: RollbackEngine) -> None:
        """CTS -> PLACE_DETAILED are adjacent; path is [PLACE_DETAILED, CTS]."""
        path = engine.get_rollback_path("CTS", "PLACE_DETAILED")
        assert path == ["PLACE_DETAILED", "CTS"]

    def test_rollback_path_signoff_to_route_detailed(
        self, engine: RollbackEngine
    ) -> None:
        """SIGNOFF -> ROUTE_DETAILED includes FINISH between them."""
        path = engine.get_rollback_path("SIGNOFF", "ROUTE_DETAILED")
        assert path == ["ROUTE_DETAILED", "FINISH", "SIGNOFF"]

    def test_rollback_path_invalid_direction(self, engine: RollbackEngine) -> None:
        """Rolling back to a later stage should raise ValueError."""
        with pytest.raises(ValueError, match="comes after"):
            engine.get_rollback_path("FLOORPLAN", "SIGNOFF")

    def test_rollback_path_unknown_stage(self, engine: RollbackEngine) -> None:
        """Unknown stage should raise ValueError."""
        with pytest.raises(ValueError, match="Unknown stage"):
            engine.get_rollback_path("NONEXISTENT", "FLOORPLAN")


# ---------------------------------------------------------------------------
# Tests: select_best_checkpoint
# ---------------------------------------------------------------------------


class TestSelectBestCheckpoint:
    def test_best_checkpoint_selected(self, engine: RollbackEngine) -> None:
        """Checkpoint with the highest composite_score is selected."""
        checkpoints: dict[str, list[StageCheckpoint]] = {
            "FLOORPLAN": [
                _make_checkpoint("FLOORPLAN", 1, 0.3),
                _make_checkpoint("FLOORPLAN", 2, 0.7),
                _make_checkpoint("FLOORPLAN", 3, 0.5),
            ],
        }
        best = engine.select_best_checkpoint("FLOORPLAN", checkpoints)
        assert best is not None
        assert best.attempt == 2
        assert best.composite_score == 0.7

    def test_select_checkpoint_no_checkpoints(self, engine: RollbackEngine) -> None:
        """Empty checkpoints for target stage returns None."""
        checkpoints: dict[str, list[StageCheckpoint]] = {}
        best = engine.select_best_checkpoint("FLOORPLAN", checkpoints)
        assert best is None

    def test_select_checkpoint_missing_stage(self, engine: RollbackEngine) -> None:
        """Stage not in checkpoints dict returns None."""
        checkpoints: dict[str, list[StageCheckpoint]] = {
            "SYNTH": [_make_checkpoint("SYNTH", 1, 0.4)],
        }
        best = engine.select_best_checkpoint("FLOORPLAN", checkpoints)
        assert best is None

    def test_state_baton_reloaded(self, engine: RollbackEngine) -> None:
        """Rolled-back stage checkpoint has state_in_path."""
        checkpoints: dict[str, list[StageCheckpoint]] = {
            "PLACE_DETAILED": [
                _make_checkpoint(
                    "PLACE_DETAILED",
                    2,
                    0.6,
                    state_in_path="/runs/r1/B0/PLACE_DETAILED/a2/state.odb",
                    attempt_dir="/runs/r1/B0/PLACE_DETAILED/a2",
                ),
            ],
        }
        best = engine.select_best_checkpoint("PLACE_DETAILED", checkpoints)
        assert best is not None
        assert best.state_in_path == "/runs/r1/B0/PLACE_DETAILED/a2/state.odb"
        assert best.attempt_dir == "/runs/r1/B0/PLACE_DETAILED/a2"

    def test_single_checkpoint(self, engine: RollbackEngine) -> None:
        """Single checkpoint for a stage is returned."""
        checkpoints: dict[str, list[StageCheckpoint]] = {
            "ROUTE_GLOBAL": [_make_checkpoint("ROUTE_GLOBAL", 1, 0.5)],
        }
        best = engine.select_best_checkpoint("ROUTE_GLOBAL", checkpoints)
        assert best is not None
        assert best.composite_score == 0.5


# ---------------------------------------------------------------------------
# Tests: decide (async)
# ---------------------------------------------------------------------------


class TestDecide:
    async def test_no_targets_returns_retry(
        self, engine: RollbackEngine
    ) -> None:
        """A stage with no rollback targets (e.g. SYNTH) should always retry."""
        decision = await engine.decide(
            failed_stage="SYNTH",
            attempt_outcomes=[_make_outcome(1, 0.1), _make_outcome(2, 0.2)],
            evidence=_make_evidence("SYNTH"),
            checkpoints={},
        )
        assert decision.action == "retry"
        assert decision.target_stage is None
        assert "no rollback targets" in decision.reason

    async def test_no_rollback_when_improving(
        self, engine: RollbackEngine
    ) -> None:
        """Improving scores should lead to retry even when rollback targets exist."""
        # CTS has rollback target [PLACE_DETAILED]
        outcomes = [
            _make_outcome(1, 0.1),
            _make_outcome(2, 0.2),
            _make_outcome(3, 0.5),  # latest > mean(0.1, 0.2) = 0.15
        ]
        decision = await engine.decide(
            failed_stage="CTS",
            attempt_outcomes=outcomes,
            evidence=_make_evidence("CTS"),
            checkpoints={"PLACE_DETAILED": [_make_checkpoint("PLACE_DETAILED", 1, 0.4)]},
        )
        assert decision.action == "retry"
        assert "improving" in decision.reason.lower()

    async def test_master_decides_rollback_vs_retry(
        self, llm: MockLLMProvider, engine: RollbackEngine
    ) -> None:
        """Mock LLM returns a rollback decision; engine respects it."""
        llm.set_response(
            RollbackDecision(
                action="rollback",
                target_stage="FLOORPLAN",
                reason="DRC violations persist; re-floorplan needed.",
                confidence=0.85,
            )
        )

        # Non-improving scores on ROUTE_DETAILED
        outcomes = [
            _make_outcome(1, 0.3),
            _make_outcome(2, 0.2),
            _make_outcome(3, 0.1),
        ]
        decision = await engine.decide(
            failed_stage="ROUTE_DETAILED",
            attempt_outcomes=outcomes,
            evidence=_make_evidence("ROUTE_DETAILED"),
            checkpoints={
                "FLOORPLAN": [_make_checkpoint("FLOORPLAN", 1, 0.5)],
                "ROUTE_GLOBAL": [_make_checkpoint("ROUTE_GLOBAL", 1, 0.4)],
            },
        )
        assert decision.action == "rollback"
        assert decision.target_stage == "FLOORPLAN"
        assert decision.confidence == 0.85

    async def test_master_decides_retry(
        self, llm: MockLLMProvider, engine: RollbackEngine
    ) -> None:
        """Mock LLM returns retry; engine respects it."""
        llm.set_response(
            RollbackDecision(
                action="retry",
                reason="Still room for improvement with parameter tuning.",
                confidence=0.7,
            )
        )

        # Non-improving scores
        outcomes = [
            _make_outcome(1, 0.3),
            _make_outcome(2, 0.2),
        ]
        decision = await engine.decide(
            failed_stage="SIGNOFF",
            attempt_outcomes=outcomes,
            evidence=_make_evidence("SIGNOFF"),
            checkpoints={
                "ROUTE_DETAILED": [_make_checkpoint("ROUTE_DETAILED", 1, 0.6)],
            },
        )
        assert decision.action == "retry"

    async def test_master_decides_stop(
        self, llm: MockLLMProvider, engine: RollbackEngine
    ) -> None:
        """Mock LLM returns stop; engine respects it."""
        llm.set_response(
            RollbackDecision(
                action="stop",
                reason="Unrecoverable design issue.",
                confidence=0.95,
            )
        )

        outcomes = [
            _make_outcome(1, 0.05),
            _make_outcome(2, 0.02),
        ]
        decision = await engine.decide(
            failed_stage="SIGNOFF",
            attempt_outcomes=outcomes,
            evidence=_make_evidence("SIGNOFF"),
            checkpoints={},
        )
        assert decision.action == "stop"

    async def test_rollback_recorded_in_history(
        self, llm: MockLLMProvider, engine: RollbackEngine
    ) -> None:
        """RollbackDecision with action='rollback' has target_stage set."""
        llm.set_response(
            RollbackDecision(
                action="rollback",
                target_stage="PLACE_DETAILED",
                reason="Clock tree issues trace back to placement.",
                confidence=0.9,
            )
        )

        outcomes = [
            _make_outcome(1, 0.2),
            _make_outcome(2, 0.15),
        ]
        decision = await engine.decide(
            failed_stage="CTS",
            attempt_outcomes=outcomes,
            evidence=_make_evidence("CTS"),
            checkpoints={
                "PLACE_DETAILED": [
                    _make_checkpoint("PLACE_DETAILED", 2, 0.6),
                ],
            },
        )
        assert decision.action == "rollback"
        assert decision.target_stage == "PLACE_DETAILED"
        # The AttemptRecord in compaction.py has was_rollback field;
        # verify the decision carries enough info to set it.
        assert decision.target_stage is not None

    async def test_llm_returns_none_fallback_retry(
        self, llm: MockLLMProvider, engine: RollbackEngine
    ) -> None:
        """If LLM returns None (parse failure), fall back to retry."""
        llm.set_failure(count=10)  # All calls fail -> generate returns None

        outcomes = [
            _make_outcome(1, 0.3),
            _make_outcome(2, 0.2),
        ]
        decision = await engine.decide(
            failed_stage="ROUTE_DETAILED",
            attempt_outcomes=outcomes,
            evidence=_make_evidence("ROUTE_DETAILED"),
            checkpoints={},
        )
        assert decision.action == "retry"
        assert "defaulting to retry" in decision.reason.lower()

    async def test_single_attempt_no_improving(
        self, llm: MockLLMProvider, engine: RollbackEngine
    ) -> None:
        """A single attempt cannot be classified as improving; goes to LLM."""
        llm.set_response(
            RollbackDecision(
                action="rollback",
                target_stage="ROUTE_GLOBAL",
                reason="Single attempt failure; rollback to global routing.",
                confidence=0.6,
            )
        )
        outcomes = [_make_outcome(1, 0.1)]
        decision = await engine.decide(
            failed_stage="ROUTE_DETAILED",
            attempt_outcomes=outcomes,
            evidence=_make_evidence("ROUTE_DETAILED"),
            checkpoints={
                "ROUTE_GLOBAL": [_make_checkpoint("ROUTE_GLOBAL", 1, 0.5)],
            },
        )
        assert decision.action == "rollback"
        assert decision.target_stage == "ROUTE_GLOBAL"

    async def test_no_outcomes_goes_to_llm(
        self, llm: MockLLMProvider, engine: RollbackEngine
    ) -> None:
        """Empty outcomes list (edge case) goes to LLM decision."""
        llm.set_response(
            RollbackDecision(
                action="retry",
                reason="No history; try again.",
                confidence=0.5,
            )
        )
        decision = await engine.decide(
            failed_stage="CTS",
            attempt_outcomes=[],
            evidence=_make_evidence("CTS"),
            checkpoints={},
        )
        assert decision.action == "retry"


# ---------------------------------------------------------------------------
# Tests: _is_improving (static helper)
# ---------------------------------------------------------------------------


class TestIsImproving:
    def test_improving_true(self) -> None:
        outcomes = [_make_outcome(1, 0.1), _make_outcome(2, 0.3)]
        assert RollbackEngine._is_improving(outcomes) is True

    def test_improving_false_declining(self) -> None:
        outcomes = [_make_outcome(1, 0.5), _make_outcome(2, 0.2)]
        assert RollbackEngine._is_improving(outcomes) is False

    def test_improving_single_outcome(self) -> None:
        """Single outcome cannot be improving."""
        outcomes = [_make_outcome(1, 0.3)]
        assert RollbackEngine._is_improving(outcomes) is False

    def test_improving_empty(self) -> None:
        assert RollbackEngine._is_improving([]) is False

    def test_improving_zero_scores_ignored(self) -> None:
        """Zero scores are filtered out."""
        outcomes = [
            _make_outcome(1, 0.0),
            _make_outcome(2, 0.0),
            _make_outcome(3, 0.5),
        ]
        # Only one non-zero score -> can't be improving
        assert RollbackEngine._is_improving(outcomes) is False

    def test_improving_latest_above_mean(self) -> None:
        """latest=0.4 > mean(0.1, 0.2, 0.3) = 0.2 -> improving."""
        outcomes = [
            _make_outcome(1, 0.1),
            _make_outcome(2, 0.2),
            _make_outcome(3, 0.3),
            _make_outcome(4, 0.4),
        ]
        assert RollbackEngine._is_improving(outcomes) is True

    def test_improving_latest_equals_mean(self) -> None:
        """latest == mean of previous -> not improving (must be strictly greater)."""
        outcomes = [
            _make_outcome(1, 0.3),
            _make_outcome(2, 0.3),
        ]
        assert RollbackEngine._is_improving(outcomes) is False
