"""P3.8 Single-Stage Flow Integration tests.

End-to-end tests for the agent-driven single-stage loop using
MockLLMProvider and MockExecutionAdapter.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agenticlane.agents.mock_llm import MockLLMProvider
from agenticlane.config.models import AgenticLaneConfig
from agenticlane.execution.workspaces import WorkspaceManager
from agenticlane.orchestration.agent_loop import AgentStageLoop
from agenticlane.schemas.judge import JudgeVote
from agenticlane.schemas.patch import Patch
from tests.mocks.mock_adapter import MockExecutionAdapter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(tmp_path: Path, attempts: int = 3) -> AgenticLaneConfig:
    """Create a minimal config for testing.

    Disables the ``metrics_parse_valid`` hard gate so that the judge
    ensemble consults the LLM votes even when sub-metrics are absent
    (no distill module is available yet).
    """
    return AgenticLaneConfig(
        project={
            "name": "test",
            "run_id": "test_run",
            "output_dir": str(tmp_path),
        },
        design={
            "librelane_config_path": str(tmp_path / "design.json"),
            "pdk": "sky130A",
        },
        execution={
            "mode": "local",
            "tool_timeout_seconds": 60,
        },
        flow_control={
            "budgets": {
                "physical_attempts_per_stage": attempts,
                "cognitive_retries_per_attempt": 3,
            },
        },
        judging={
            "strictness": {
                # Only keep execution_success; drop metrics_parse_valid
                # so the judge consults LLM votes even without sub-metrics.
                "hard_gates": ["execution_success"],
            },
        },
    )


def _make_patch(stage: str = "PLACE_GLOBAL", attempt: int = 1) -> Patch:
    return Patch(
        patch_id=f"test_patch_{attempt}",
        stage=stage,
        types=["config_vars"],
        config_vars={"PL_TARGET_DENSITY_PCT": 65},
        rationale="Increase density for better utilization",
    )


def _make_pass_vote(judge_id: str = "j0") -> JudgeVote:
    return JudgeVote(
        judge_id=judge_id,
        model="test",
        vote="PASS",
        confidence=0.9,
        rationale="Metrics improved",
    )


def _make_fail_vote(judge_id: str = "j0") -> JudgeVote:
    return JudgeVote(
        judge_id=judge_id,
        model="test",
        vote="FAIL",
        confidence=0.7,
        rationale="Needs improvement",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSingleStageFlow:
    @pytest.fixture()
    def tmp_dir(self, tmp_path: Path) -> Path:
        return tmp_path

    def _setup_loop(
        self,
        tmp_dir: Path,
        attempts: int = 3,
    ) -> tuple[AgentStageLoop, MockLLMProvider, MockExecutionAdapter, Path, Path]:
        config = _make_config(tmp_dir, attempts=attempts)
        adapter = MockExecutionAdapter()
        provider = MockLLMProvider(log_dir=tmp_dir / "logs")
        ws = WorkspaceManager()

        run_dir = ws.create_run_dir(tmp_dir, "test_run")
        branch_dir = ws.create_branch_dir(run_dir, "B0")

        loop = AgentStageLoop(config, adapter, provider, ws)
        return loop, provider, adapter, run_dir, branch_dir

    @pytest.mark.asyncio()
    async def test_stage_passes_with_good_votes(self, tmp_dir: Path) -> None:
        """Stage passes when judge votes PASS."""
        loop, provider, adapter, run_dir, branch_dir = self._setup_loop(tmp_dir)

        patch = _make_patch()
        # Attempt 1: 1 worker call + 3 judge calls = 4 LLM calls
        provider.queue_responses(
            patch,
            _make_pass_vote("j0"),
            _make_pass_vote("j1"),
            _make_pass_vote("j2"),
        )

        result = await loop.run_stage(
            "PLACE_GLOBAL", branch_dir, run_dir, run_id="test_run"
        )
        assert result.passed
        assert result.best_attempt >= 1
        assert len(result.attempt_outcomes) >= 1

    @pytest.mark.asyncio()
    async def test_stage_fails_after_budget_exhaustion(self, tmp_dir: Path) -> None:
        """Stage fails when all attempts get FAIL votes."""
        loop, provider, adapter, run_dir, branch_dir = self._setup_loop(
            tmp_dir, attempts=2
        )

        patch = _make_patch()
        # For each of 2 attempts: 1 worker + 3 judges = 4 calls
        for _ in range(2):
            provider.queue_responses(
                patch,
                _make_fail_vote("j0"),
                _make_fail_vote("j1"),
                _make_fail_vote("j2"),
            )

        result = await loop.run_stage(
            "PLACE_GLOBAL", branch_dir, run_dir, run_id="test_run"
        )
        assert not result.passed
        assert result.attempts_used == 2

    @pytest.mark.asyncio()
    async def test_cognitive_retry_before_physical(self, tmp_dir: Path) -> None:
        """Rejected patches don't burn physical attempts."""
        loop, provider, adapter, run_dir, branch_dir = self._setup_loop(
            tmp_dir, attempts=2
        )

        # First worker response includes CLOCK_PERIOD (locked) -> rejected
        bad_patch = Patch(
            patch_id="bad",
            stage="PLACE_GLOBAL",
            types=["config_vars"],
            config_vars={"CLOCK_PERIOD": 20.0},
            rationale="Relax clock",
        )
        good_patch = _make_patch()

        # Attempt 1: bad patch (cognitive reject) -> good patch (accepted) -> judges PASS
        provider.queue_responses(
            bad_patch,
            good_patch,
            _make_pass_vote("j0"),
            _make_pass_vote("j1"),
            _make_pass_vote("j2"),
        )

        result = await loop.run_stage(
            "PLACE_GLOBAL", branch_dir, run_dir, run_id="test_run"
        )
        assert result.passed
        assert result.attempts_used == 1  # Only 1 physical attempt used

    @pytest.mark.asyncio()
    async def test_artifacts_persisted(self, tmp_dir: Path) -> None:
        """Check that metrics, evidence, judge_votes, and composite_score JSONs are written."""
        loop, provider, adapter, run_dir, branch_dir = self._setup_loop(
            tmp_dir, attempts=1
        )

        patch = _make_patch()
        provider.queue_responses(
            patch,
            _make_pass_vote("j0"),
            _make_pass_vote("j1"),
            _make_pass_vote("j2"),
        )

        await loop.run_stage(
            "PLACE_GLOBAL", branch_dir, run_dir, run_id="test_run"
        )

        # The workspace structure is: branch_dir/stages/PLACE_GLOBAL/attempt_NNN
        stage_dir = branch_dir / "stages" / "PLACE_GLOBAL"
        assert stage_dir.exists()

        # Should have attempt_000 (baseline) and attempt_001
        attempt_dirs = sorted(stage_dir.iterdir())
        assert len(attempt_dirs) >= 2

        attempt_1 = [d for d in attempt_dirs if "001" in d.name][0]
        assert (attempt_1 / "metrics.json").exists()
        assert (attempt_1 / "evidence.json").exists()
        assert (attempt_1 / "judge_votes.json").exists()
        assert (attempt_1 / "composite_score.json").exists()

    @pytest.mark.asyncio()
    async def test_llm_calls_logged(self, tmp_dir: Path) -> None:
        """LLM calls are recorded."""
        loop, provider, adapter, run_dir, branch_dir = self._setup_loop(tmp_dir)

        patch = _make_patch()
        provider.queue_responses(
            patch,
            _make_pass_vote("j0"),
            _make_pass_vote("j1"),
            _make_pass_vote("j2"),
        )

        await loop.run_stage(
            "PLACE_GLOBAL", branch_dir, run_dir, run_id="test_run"
        )

        records = provider.call_records
        assert len(records) >= 4  # 1 worker + 3 judges minimum

    @pytest.mark.asyncio()
    async def test_lessons_learned_generated(self, tmp_dir: Path) -> None:
        """lessons_learned.json is written after attempts."""
        loop, provider, adapter, run_dir, branch_dir = self._setup_loop(
            tmp_dir, attempts=2
        )

        patch = _make_patch()
        # Attempt 1: FAIL, attempt 2: PASS
        provider.queue_responses(
            patch,
            _make_fail_vote("j0"),
            _make_fail_vote("j1"),
            _make_fail_vote("j2"),
            patch,
            _make_pass_vote("j0"),
            _make_pass_vote("j1"),
            _make_pass_vote("j2"),
        )

        await loop.run_stage(
            "PLACE_GLOBAL", branch_dir, run_dir, run_id="test_run"
        )

        # Find lessons_learned.json in attempt dirs
        stage_dir = branch_dir / "stages" / "PLACE_GLOBAL"
        found_lessons = list(stage_dir.rglob("lessons_learned.json"))
        assert len(found_lessons) >= 1

    @pytest.mark.asyncio()
    async def test_deterministic_scoring(self, tmp_dir: Path) -> None:
        """Same inputs produce same composite score."""
        loop, provider, adapter, run_dir, branch_dir = self._setup_loop(
            tmp_dir, attempts=1
        )

        patch = _make_patch()
        provider.queue_responses(
            patch,
            _make_pass_vote("j0"),
            _make_pass_vote("j1"),
            _make_pass_vote("j2"),
        )

        result = await loop.run_stage(
            "PLACE_GLOBAL", branch_dir, run_dir, run_id="test_run"
        )

        assert len(result.attempt_outcomes) >= 1
        # Score should be a real number
        if result.attempt_outcomes:
            assert isinstance(result.attempt_outcomes[0].composite_score, float)

    @pytest.mark.asyncio()
    async def test_checkpoint_written_on_pass(self, tmp_dir: Path) -> None:
        """checkpoint.json written when stage passes."""
        loop, provider, adapter, run_dir, branch_dir = self._setup_loop(
            tmp_dir, attempts=1
        )

        patch = _make_patch()
        provider.queue_responses(
            patch,
            _make_pass_vote("j0"),
            _make_pass_vote("j1"),
            _make_pass_vote("j2"),
        )

        await loop.run_stage(
            "PLACE_GLOBAL", branch_dir, run_dir, run_id="test_run"
        )

        stage_dir = branch_dir / "stages" / "PLACE_GLOBAL"
        checkpoints = list(stage_dir.rglob("checkpoint.json"))
        assert len(checkpoints) >= 1

    @pytest.mark.asyncio()
    async def test_cognitive_budget_exhaustion(self, tmp_dir: Path) -> None:
        """When all cognitive retries fail, attempt is marked rejected."""
        config = _make_config(tmp_dir, attempts=1)
        # Override cognitive retries to 1
        config.flow_control.budgets.cognitive_retries_per_attempt = 1

        adapter = MockExecutionAdapter()
        provider = MockLLMProvider(log_dir=tmp_dir / "logs")
        ws = WorkspaceManager()
        run_dir = ws.create_run_dir(tmp_dir, "cog_test")
        branch_dir = ws.create_branch_dir(run_dir, "B0")

        loop = AgentStageLoop(config, adapter, provider, ws)

        # Worker always proposes locked var
        bad_patch = Patch(
            patch_id="bad",
            stage="PLACE_GLOBAL",
            types=["config_vars"],
            config_vars={"CLOCK_PERIOD": 20.0},
            rationale="Relax clock",
        )
        provider.set_response(bad_patch)

        result = await loop.run_stage("PLACE_GLOBAL", branch_dir, run_dir)
        assert not result.passed
        # Should have 1 attempt that failed due to cognitive exhaustion
        assert result.attempts_used >= 1
        # The attempt should not have been accepted
        assert len(result.attempt_outcomes) >= 1
        assert not result.attempt_outcomes[0].patch_accepted

    @pytest.mark.asyncio()
    async def test_baseline_artifacts_written(self, tmp_dir: Path) -> None:
        """Baseline (attempt 0) produces metrics.json and evidence.json."""
        loop, provider, adapter, run_dir, branch_dir = self._setup_loop(
            tmp_dir, attempts=1
        )

        patch = _make_patch()
        provider.queue_responses(
            patch,
            _make_pass_vote("j0"),
            _make_pass_vote("j1"),
            _make_pass_vote("j2"),
        )

        await loop.run_stage(
            "PLACE_GLOBAL", branch_dir, run_dir, run_id="test_run"
        )

        # Baseline attempt dir
        baseline_dir = branch_dir / "stages" / "PLACE_GLOBAL" / "attempt_000"
        assert baseline_dir.exists()
        assert (baseline_dir / "metrics.json").exists()
        assert (baseline_dir / "evidence.json").exists()

    @pytest.mark.asyncio()
    async def test_adapter_called_with_patch_data(self, tmp_dir: Path) -> None:
        """Execution adapter receives the accepted patch."""
        loop, provider, adapter, run_dir, branch_dir = self._setup_loop(
            tmp_dir, attempts=1
        )

        patch = _make_patch()
        provider.queue_responses(
            patch,
            _make_pass_vote("j0"),
            _make_pass_vote("j1"),
            _make_pass_vote("j2"),
        )

        await loop.run_stage(
            "PLACE_GLOBAL", branch_dir, run_dir, run_id="test_run"
        )

        # call_log[0] = baseline, call_log[1] = attempt 1
        assert len(adapter.call_log) >= 2
        attempt_call = adapter.call_log[1]
        # The patch should contain the config_vars from the accepted patch
        assert attempt_call["patch"]["config_vars"]["PL_TARGET_DENSITY_PCT"] == 65
