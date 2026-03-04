"""Tests for the SequentialOrchestrator (P1.11).

Uses MockExecutionAdapter to verify the async main loop, stage iteration,
gate checking, checkpointing, distillation, and manifest writing.
All tests are async (pytest-asyncio with asyncio_mode = "auto").
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from agenticlane.config.models import AgenticLaneConfig
from agenticlane.execution.adapter import ExecutionAdapter
from agenticlane.orchestration.orchestrator import (
    FlowResult,
    SequentialOrchestrator,
    StageResult,
)
from agenticlane.schemas.execution import ExecutionResult
from tests.mocks.mock_adapter import MockExecutionAdapter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(tmp_path: Path, *, budget: int = 3) -> AgenticLaneConfig:
    """Build an AgenticLaneConfig pointing at *tmp_path*."""
    return AgenticLaneConfig(
        project={
            "name": "test_block",
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
                "physical_attempts_per_stage": budget,
            },
        },
    )


class AlwaysFailAdapter(ExecutionAdapter):
    """Adapter that always returns a failure result."""

    def __init__(self, failure_mode: str = "tool_crash") -> None:
        self.failure_mode = failure_mode
        self.call_count = 0

    async def run_stage(
        self,
        *,
        run_root: str,
        stage_name: str,
        librelane_config_path: str,
        resolved_design_config_path: str,
        patch: dict[str, Any],
        state_in_path: Optional[str],
        attempt_dir: str,
        timeout_seconds: int,
    ) -> ExecutionResult:
        self.call_count += 1
        Path(attempt_dir).mkdir(parents=True, exist_ok=True)
        (Path(attempt_dir) / "workspace").mkdir(exist_ok=True)
        (Path(attempt_dir) / "artifacts").mkdir(exist_ok=True)
        # Write crash.log so the crash extractor can find it
        (Path(attempt_dir) / "crash.log").write_text(
            "Simulated failure\nAborted (core dumped)"
        )
        return ExecutionResult(
            execution_status=self.failure_mode,  # type: ignore[arg-type]
            exit_code=1,
            runtime_seconds=0.01,
            attempt_dir=attempt_dir,
            workspace_dir=str(Path(attempt_dir) / "workspace"),
            artifacts_dir=str(Path(attempt_dir) / "artifacts"),
            state_out_path=None,
            stderr_tail="Simulated failure",
            error_summary="Simulated failure",
        )


class FailThenPassAdapter(ExecutionAdapter):
    """Adapter that fails the first N calls then succeeds."""

    def __init__(self, fail_count: int = 1) -> None:
        self.fail_count = fail_count
        self.call_count = 0

    async def run_stage(
        self,
        *,
        run_root: str,
        stage_name: str,
        librelane_config_path: str,
        resolved_design_config_path: str,
        patch: dict[str, Any],
        state_in_path: Optional[str],
        attempt_dir: str,
        timeout_seconds: int,
    ) -> ExecutionResult:
        self.call_count += 1
        Path(attempt_dir).mkdir(parents=True, exist_ok=True)
        ws = Path(attempt_dir) / "workspace"
        ws.mkdir(exist_ok=True)
        art = Path(attempt_dir) / "artifacts"
        art.mkdir(exist_ok=True)

        if self.call_count <= self.fail_count:
            return ExecutionResult(
                execution_status="tool_crash",
                exit_code=139,
                runtime_seconds=0.01,
                attempt_dir=attempt_dir,
                workspace_dir=str(ws),
                artifacts_dir=str(art),
                state_out_path=None,
                stderr_tail="Crash on attempt",
                error_summary="Simulated crash",
            )

        # Write state_out
        state_out = Path(attempt_dir) / "state_out.json"
        state_out.write_text(json.dumps({"stage": stage_name, "status": "ok"}))

        return ExecutionResult(
            execution_status="success",
            exit_code=0,
            runtime_seconds=0.05,
            attempt_dir=attempt_dir,
            workspace_dir=str(ws),
            artifacts_dir=str(art),
            state_out_path=str(state_out),
            stderr_tail=None,
            error_summary=None,
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSingleStagePass:
    """test_single_stage_pass: Run one stage with 100% success adapter, verify pass."""

    async def test_single_stage_pass(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path, budget=3)
        adapter = MockExecutionAdapter(success_probability=1.0)
        orch = SequentialOrchestrator(config, adapter)

        result = await orch.run_flow(stages=["SYNTH"])

        assert result.completed is True
        assert "SYNTH" in result.stages_completed
        assert len(result.stages_failed) == 0
        assert "SYNTH" in result.stage_results
        sr = result.stage_results["SYNTH"]
        assert sr.passed is True
        assert sr.attempts_used == 1
        assert sr.best_attempt == 1


class TestSingleStageFailRetry:
    """test_single_stage_fail_retry: Run with failing adapter, verify retries up to budget."""

    async def test_retries_up_to_budget(self, tmp_path: Path) -> None:
        budget = 3
        config = _make_config(tmp_path, budget=budget)
        adapter = AlwaysFailAdapter()
        orch = SequentialOrchestrator(config, adapter)

        result = await orch.run_flow(stages=["SYNTH"])

        assert result.completed is False
        assert "SYNTH" in result.stages_failed
        sr = result.stage_results["SYNTH"]
        assert sr.passed is False
        assert sr.attempts_used == budget
        assert adapter.call_count == budget

    async def test_fail_then_pass(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path, budget=5)
        adapter = FailThenPassAdapter(fail_count=2)
        orch = SequentialOrchestrator(config, adapter)

        result = await orch.run_flow(stages=["SYNTH"])

        assert result.completed is True
        sr = result.stage_results["SYNTH"]
        assert sr.passed is True
        assert sr.attempts_used == 3  # 2 failures + 1 success
        assert sr.best_attempt == 3


class TestMultiStageSequence:
    """test_multi_stage_sequence: 3 stages in order, all pass."""

    async def test_three_stages_all_pass(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path, budget=3)
        adapter = MockExecutionAdapter(success_probability=1.0)
        orch = SequentialOrchestrator(config, adapter)

        stages = ["SYNTH", "FLOORPLAN", "PDN"]
        result = await orch.run_flow(stages=stages)

        assert result.completed is True
        assert result.stages_completed == stages
        assert len(result.stages_failed) == 0
        for s in stages:
            assert s in result.stage_results
            assert result.stage_results[s].passed is True


class TestGateBlocksOnFailure:
    """test_gate_blocks_on_failure: Stage with execution failure fails gate check."""

    async def test_execution_failure_blocks_gate(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path, budget=1)
        adapter = AlwaysFailAdapter(failure_mode="tool_crash")
        orch = SequentialOrchestrator(config, adapter)

        result = await orch.run_flow(stages=["SYNTH"])

        sr = result.stage_results["SYNTH"]
        assert sr.passed is False
        # Evidence should have crash_info
        assert sr.best_evidence is not None
        assert sr.best_evidence.crash_info is not None
        assert sr.best_evidence.crash_info.crash_type == "tool_crash"


class TestBudgetExhaustionContinues:
    """test_budget_exhaustion_continues: After budget exhausted, continues to next stage."""

    async def test_continues_to_next_stage(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path, budget=2)
        adapter = AlwaysFailAdapter()
        orch = SequentialOrchestrator(config, adapter)

        result = await orch.run_flow(stages=["SYNTH", "FLOORPLAN"])

        assert result.completed is False
        # Both stages should have been attempted
        assert "SYNTH" in result.stages_failed
        assert "FLOORPLAN" in result.stages_failed
        assert len(result.stage_results) == 2
        # Each stage used the full budget
        assert result.stage_results["SYNTH"].attempts_used == 2
        assert result.stage_results["FLOORPLAN"].attempts_used == 2
        # Total calls = 2 stages x 2 attempts = 4
        assert adapter.call_count == 4


class TestCheckpointWrittenOnPass:
    """test_checkpoint_written_on_pass: Successful stage writes checkpoint.json."""

    async def test_checkpoint_exists(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path, budget=3)
        adapter = MockExecutionAdapter(success_probability=1.0)
        orch = SequentialOrchestrator(config, adapter)

        result = await orch.run_flow(stages=["SYNTH"])

        sr = result.stage_results["SYNTH"]
        assert sr.passed is True

        # Find the attempt directory and check for checkpoint.json
        run_dir = Path(result.run_dir)  # type: ignore[arg-type]
        attempt_dir = run_dir / "branches" / "B0" / "stages" / "SYNTH" / "attempt_001"
        assert attempt_dir.exists()
        checkpoint_file = attempt_dir / "checkpoint.json"
        assert checkpoint_file.exists()

        checkpoint = json.loads(checkpoint_file.read_text())
        assert checkpoint["stage"] == "SYNTH"
        assert checkpoint["attempt"] == 1
        assert checkpoint["status"] == "passed"


class TestDistillationCalledPerAttempt:
    """test_distillation_called_per_attempt: Each attempt produces metrics.json and evidence.json."""

    async def test_artifacts_per_attempt(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path, budget=5)
        adapter = FailThenPassAdapter(fail_count=2)
        orch = SequentialOrchestrator(config, adapter)

        result = await orch.run_flow(stages=["SYNTH"])

        run_dir = Path(result.run_dir)  # type: ignore[arg-type]
        stages_dir = run_dir / "branches" / "B0" / "stages" / "SYNTH"

        # 3 attempts: 2 failed + 1 success
        for i in range(1, 4):
            attempt_dir = stages_dir / f"attempt_{i:03d}"
            assert attempt_dir.exists(), f"attempt_{i:03d} should exist"
            assert (attempt_dir / "metrics.json").exists(), f"metrics.json missing in attempt {i}"
            assert (attempt_dir / "evidence.json").exists(), f"evidence.json missing in attempt {i}"
            assert (attempt_dir / "patch.json").exists(), f"patch.json missing in attempt {i}"

            # Verify metrics.json is valid JSON
            metrics_data = json.loads((attempt_dir / "metrics.json").read_text())
            assert "stage" in metrics_data
            assert metrics_data["stage"] == "SYNTH"
            assert metrics_data["attempt"] == i

            # Verify evidence.json is valid JSON
            evidence_data = json.loads((attempt_dir / "evidence.json").read_text())
            assert "stage" in evidence_data
            assert evidence_data["stage"] == "SYNTH"


class TestManifestWritten:
    """test_manifest_written: manifest.json created after flow completes."""

    async def test_manifest_exists_and_valid(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path, budget=3)
        adapter = MockExecutionAdapter(success_probability=1.0)
        orch = SequentialOrchestrator(config, adapter)

        result = await orch.run_flow(stages=["SYNTH", "FLOORPLAN"])

        run_dir = Path(result.run_dir)  # type: ignore[arg-type]
        manifest_file = run_dir / "manifest.json"
        assert manifest_file.exists()

        manifest = json.loads(manifest_file.read_text())
        assert manifest["run_id"] == result.run_id
        assert manifest["completed"] is True
        assert manifest["stages_completed"] == ["SYNTH", "FLOORPLAN"]
        assert manifest["stages_failed"] == []
        assert "SYNTH" in manifest["stage_results"]
        assert "FLOORPLAN" in manifest["stage_results"]
        assert manifest["stage_results"]["SYNTH"]["passed"] is True
        assert manifest["stage_results"]["FLOORPLAN"]["passed"] is True

    async def test_manifest_with_failures(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path, budget=1)
        adapter = AlwaysFailAdapter()
        orch = SequentialOrchestrator(config, adapter)

        result = await orch.run_flow(stages=["SYNTH"])

        run_dir = Path(result.run_dir)  # type: ignore[arg-type]
        manifest = json.loads((run_dir / "manifest.json").read_text())
        assert manifest["completed"] is False
        assert "SYNTH" in manifest["stages_failed"]


class TestRunDirCreated:
    """test_run_dir_created: Run directory hierarchy created correctly."""

    async def test_directory_hierarchy(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path, budget=1)
        adapter = MockExecutionAdapter(success_probability=1.0)
        orch = SequentialOrchestrator(config, adapter)

        result = await orch.run_flow(stages=["SYNTH"])

        run_dir = Path(result.run_dir)  # type: ignore[arg-type]
        assert run_dir.exists()
        assert (run_dir / "branches" / "B0").exists()
        assert (run_dir / "branches" / "B0" / "stages" / "SYNTH").exists()
        assert (run_dir / "branches" / "B0" / "stages" / "SYNTH" / "attempt_001").exists()
        # Sub-directories inside attempt dir
        attempt_dir = run_dir / "branches" / "B0" / "stages" / "SYNTH" / "attempt_001"
        assert (attempt_dir / "proposals").exists()
        assert (attempt_dir / "constraints").exists()
        assert (attempt_dir / "workspace").exists()
        assert (attempt_dir / "artifacts").exists()


class TestStateInPassedBetweenStages:
    """test_state_in_passed_between_stages: state_out from stage N is state_in for stage N+1."""

    async def test_state_chaining(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path, budget=3)
        adapter = MockExecutionAdapter(success_probability=1.0)
        orch = SequentialOrchestrator(config, adapter)

        result = await orch.run_flow(stages=["SYNTH", "FLOORPLAN", "PDN"])

        # The mock adapter records every call. Check that state_in_path
        # for FLOORPLAN was set to SYNTH's state_out (checkpoint path),
        # and PDN's state_in was set to FLOORPLAN's.
        calls = adapter.call_log
        assert len(calls) == 3

        # First stage should have state_in=None (orchestrator starts with None)
        # but actually: the orchestrator updates _state_in_path to checkpoint_path
        # which is the state_out_path from ExecutionResult.
        # For mock adapter, state_out_path is set on success.
        synth_call = calls[0]
        floorplan_call = calls[1]
        pdn_call = calls[2]

        # SYNTH starts with no state_in
        assert synth_call["state_in_path"] is None

        # FLOORPLAN should get SYNTH's state_out
        synth_result_state = result.stage_results["SYNTH"].checkpoint_path
        assert synth_result_state is not None
        assert floorplan_call["state_in_path"] == synth_result_state

        # PDN should get FLOORPLAN's state_out
        floorplan_result_state = result.stage_results["FLOORPLAN"].checkpoint_path
        assert floorplan_result_state is not None
        assert pdn_call["state_in_path"] == floorplan_result_state


class TestCustomStageList:
    """test_custom_stage_list: Can run a subset of stages."""

    async def test_subset_stages(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path, budget=3)
        adapter = MockExecutionAdapter(success_probability=1.0)
        orch = SequentialOrchestrator(config, adapter)

        # Only run CTS and ROUTE_GLOBAL
        result = await orch.run_flow(stages=["CTS", "ROUTE_GLOBAL"])

        assert result.completed is True
        assert len(result.stage_results) == 2
        assert "CTS" in result.stage_results
        assert "ROUTE_GLOBAL" in result.stage_results
        assert result.stages_completed == ["CTS", "ROUTE_GLOBAL"]

    async def test_single_stage(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path, budget=1)
        adapter = MockExecutionAdapter(success_probability=1.0)
        orch = SequentialOrchestrator(config, adapter)

        result = await orch.run_flow(stages=["SIGNOFF"])

        assert result.completed is True
        assert list(result.stage_results.keys()) == ["SIGNOFF"]


class TestFlowResultStructure:
    """test_flow_result_structure: FlowResult contains all expected fields."""

    async def test_flow_result_fields(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path, budget=2)
        adapter = MockExecutionAdapter(success_probability=1.0)
        orch = SequentialOrchestrator(config, adapter)

        result = await orch.run_flow(stages=["SYNTH"])

        # FlowResult fields
        assert isinstance(result, FlowResult)
        assert isinstance(result.run_id, str)
        assert isinstance(result.completed, bool)
        assert isinstance(result.stages_completed, list)
        assert isinstance(result.stages_failed, list)
        assert isinstance(result.stage_results, dict)
        assert result.run_dir is not None

    async def test_stage_result_fields(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path, budget=2)
        adapter = MockExecutionAdapter(success_probability=1.0)
        orch = SequentialOrchestrator(config, adapter)

        result = await orch.run_flow(stages=["SYNTH"])

        sr = result.stage_results["SYNTH"]
        assert isinstance(sr, StageResult)
        assert sr.stage_name == "SYNTH"
        assert isinstance(sr.passed, bool)
        assert isinstance(sr.best_attempt, int)
        assert isinstance(sr.attempts_used, int)
        assert sr.best_metrics is not None
        assert sr.best_evidence is not None

    async def test_auto_run_id_generation(self, tmp_path: Path) -> None:
        config = AgenticLaneConfig(
            project={
                "name": "test_block",
                "run_id": "auto",
                "output_dir": str(tmp_path),
            },
            design={
                "librelane_config_path": str(tmp_path / "design.json"),
            },
        )
        adapter = MockExecutionAdapter(success_probability=1.0)
        orch = SequentialOrchestrator(config, adapter)

        result = await orch.run_flow(stages=["SYNTH"])

        assert result.run_id.startswith("run_")
        assert len(result.run_id) > 4  # "run_" + hex chars

    async def test_explicit_run_id(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path, budget=1)
        adapter = MockExecutionAdapter(success_probability=1.0)
        orch = SequentialOrchestrator(config, adapter)

        result = await orch.run_flow(stages=["SYNTH"], run_id="my_custom_run")

        assert result.run_id == "my_custom_run"


class TestAllStagesDefault:
    """Verify running with no stage list runs all 10 stages."""

    async def test_all_ten_stages(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path, budget=1)
        adapter = MockExecutionAdapter(success_probability=1.0)
        orch = SequentialOrchestrator(config, adapter)

        result = await orch.run_flow()

        assert result.completed is True
        assert len(result.stages_completed) == 10
        assert len(result.stage_results) == 10
        from agenticlane.orchestration.graph import STAGE_ORDER

        assert result.stages_completed == list(STAGE_ORDER)
