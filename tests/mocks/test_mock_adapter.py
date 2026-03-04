"""Tests for MockExecutionAdapter and MockLLMProvider.

Test cases:
- test_mock_produces_execution_result: returns valid ExecutionResult with status=success
- test_mock_deterministic: same inputs produce same results
- test_mock_responds_to_knob_changes: changing FP_CORE_UTIL affects area metrics
- test_mock_failure_injection: failure_mode causes failures
- test_mock_creates_directory_structure: attempt_dir has workspace/, artifacts/
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agenticlane.schemas.execution import ExecutionResult
from tests.mocks.mock_adapter import MockExecutionAdapter
from tests.mocks.mock_llm import MockLLMProvider

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_adapter() -> MockExecutionAdapter:
    """Return a default MockExecutionAdapter with 100% success."""
    return MockExecutionAdapter(success_probability=1.0, noise_seed=42)


@pytest.fixture
def default_run_kwargs(tmp_path: Path) -> dict:
    """Return default keyword arguments for run_stage."""
    attempt_dir = str(tmp_path / "run001" / "floorplan" / "attempt_1")
    return {
        "run_root": str(tmp_path / "run001"),
        "stage_name": "floorplan",
        "librelane_config_path": str(tmp_path / "config.yaml"),
        "resolved_design_config_path": str(tmp_path / "design.yaml"),
        "patch": {"config_vars": {"FP_CORE_UTIL": 45}},
        "state_in_path": None,
        "attempt_dir": attempt_dir,
        "timeout_seconds": 3600,
    }


# ===========================================================================
# MockExecutionAdapter Tests
# ===========================================================================


class TestMockProducesExecutionResult:
    """test_mock_produces_execution_result - returns valid ExecutionResult with status=success."""

    async def test_returns_execution_result(
        self, mock_adapter: MockExecutionAdapter, default_run_kwargs: dict
    ) -> None:
        result = await mock_adapter.run_stage(**default_run_kwargs)
        assert isinstance(result, ExecutionResult)

    async def test_success_status(
        self, mock_adapter: MockExecutionAdapter, default_run_kwargs: dict
    ) -> None:
        result = await mock_adapter.run_stage(**default_run_kwargs)
        assert result.execution_status == "success"

    async def test_zero_exit_code(
        self, mock_adapter: MockExecutionAdapter, default_run_kwargs: dict
    ) -> None:
        result = await mock_adapter.run_stage(**default_run_kwargs)
        assert result.exit_code == 0

    async def test_positive_runtime(
        self, mock_adapter: MockExecutionAdapter, default_run_kwargs: dict
    ) -> None:
        result = await mock_adapter.run_stage(**default_run_kwargs)
        assert result.runtime_seconds >= 0.0

    async def test_state_out_path_exists(
        self, mock_adapter: MockExecutionAdapter, default_run_kwargs: dict
    ) -> None:
        result = await mock_adapter.run_stage(**default_run_kwargs)
        assert result.state_out_path is not None
        assert os.path.isfile(result.state_out_path)

    async def test_no_error_on_success(
        self, mock_adapter: MockExecutionAdapter, default_run_kwargs: dict
    ) -> None:
        result = await mock_adapter.run_stage(**default_run_kwargs)
        assert result.stderr_tail is None
        assert result.error_summary is None

    async def test_state_out_valid_json(
        self, mock_adapter: MockExecutionAdapter, default_run_kwargs: dict
    ) -> None:
        result = await mock_adapter.run_stage(**default_run_kwargs)
        assert result.state_out_path is not None
        with open(result.state_out_path) as f:
            data = json.load(f)
        assert data["stage"] == "floorplan"
        assert data["status"] == "success"
        assert "metrics_snapshot" in data

    async def test_call_log_recorded(
        self, mock_adapter: MockExecutionAdapter, default_run_kwargs: dict
    ) -> None:
        await mock_adapter.run_stage(**default_run_kwargs)
        assert len(mock_adapter.call_log) == 1
        assert mock_adapter.call_log[0]["stage_name"] == "floorplan"


class TestMockDeterministic:
    """test_mock_deterministic - same inputs produce same results."""

    async def test_same_inputs_same_metrics(self, tmp_path: Path) -> None:
        """Running twice with identical inputs must produce identical metrics."""
        metrics_list = []
        for i in range(2):
            adapter = MockExecutionAdapter(success_probability=1.0, noise_seed=42)
            attempt_dir = str(tmp_path / f"run_{i}" / "floorplan" / "attempt_1")
            result = await adapter.run_stage(
                run_root=str(tmp_path / f"run_{i}"),
                stage_name="floorplan",
                librelane_config_path="config.yaml",
                resolved_design_config_path="design.yaml",
                patch={"config_vars": {"FP_CORE_UTIL": 45}},
                state_in_path=None,
                attempt_dir=attempt_dir,
                timeout_seconds=3600,
            )
            assert result.state_out_path is not None
            with open(result.state_out_path) as f:
                data = json.load(f)
            metrics_list.append(data["metrics_snapshot"])

        assert metrics_list[0] == metrics_list[1]

    async def test_different_seed_different_metrics(self, tmp_path: Path) -> None:
        """Different seeds must produce different noise (metrics differ)."""
        metrics_list = []
        for seed in [42, 99]:
            adapter = MockExecutionAdapter(success_probability=1.0, noise_seed=seed)
            attempt_dir = str(tmp_path / f"seed_{seed}" / "floorplan" / "attempt_1")
            result = await adapter.run_stage(
                run_root=str(tmp_path / f"seed_{seed}"),
                stage_name="floorplan",
                librelane_config_path="config.yaml",
                resolved_design_config_path="design.yaml",
                patch={"config_vars": {"FP_CORE_UTIL": 45}},
                state_in_path=None,
                attempt_dir=attempt_dir,
                timeout_seconds=3600,
            )
            assert result.state_out_path is not None
            with open(result.state_out_path) as f:
                data = json.load(f)
            metrics_list.append(data["metrics_snapshot"])

        # The noise component should make them slightly different
        assert metrics_list[0] != metrics_list[1]

    async def test_deterministic_across_stages(self, tmp_path: Path) -> None:
        """Different stages with same seed should produce different baselines."""
        results: dict[str, dict] = {}
        for stage in ["floorplan", "place_global"]:
            adapter = MockExecutionAdapter(success_probability=1.0, noise_seed=42)
            attempt_dir = str(tmp_path / stage / "attempt_1")
            result = await adapter.run_stage(
                run_root=str(tmp_path),
                stage_name=stage,
                librelane_config_path="config.yaml",
                resolved_design_config_path="design.yaml",
                patch={"config_vars": {"FP_CORE_UTIL": 45}},
                state_in_path=None,
                attempt_dir=attempt_dir,
                timeout_seconds=3600,
            )
            assert result.state_out_path is not None
            with open(result.state_out_path) as f:
                data = json.load(f)
            results[stage] = data["metrics_snapshot"]

        # Different stages have different baselines
        assert results["floorplan"]["congestion_overflow_pct"] != results[
            "place_global"
        ]["congestion_overflow_pct"]


class TestMockRespondsToKnobChanges:
    """test_mock_responds_to_knob_changes - changing FP_CORE_UTIL affects area metrics."""

    async def test_higher_fp_util_smaller_area(self, tmp_path: Path) -> None:
        """Higher FP_CORE_UTIL should produce smaller area."""
        areas: dict[int, float] = {}
        for util in [30, 45, 70]:
            adapter = MockExecutionAdapter(success_probability=1.0, noise_seed=42)
            attempt_dir = str(tmp_path / f"util_{util}" / "floorplan" / "a1")
            result = await adapter.run_stage(
                run_root=str(tmp_path / f"util_{util}"),
                stage_name="floorplan",
                librelane_config_path="config.yaml",
                resolved_design_config_path="design.yaml",
                patch={"config_vars": {"FP_CORE_UTIL": util}},
                state_in_path=None,
                attempt_dir=attempt_dir,
                timeout_seconds=3600,
            )
            assert result.state_out_path is not None
            with open(result.state_out_path) as f:
                data = json.load(f)
            areas[util] = data["metrics_snapshot"]["core_area_um2"]

        # Higher utilization -> smaller area
        assert areas[30] > areas[45] > areas[70]

    async def test_higher_fp_util_more_congestion(self, tmp_path: Path) -> None:
        """Higher FP_CORE_UTIL should produce more congestion."""
        congestion: dict[int, float] = {}
        for util in [30, 45, 70]:
            adapter = MockExecutionAdapter(success_probability=1.0, noise_seed=42)
            attempt_dir = str(tmp_path / f"util_{util}" / "floorplan" / "a1")
            result = await adapter.run_stage(
                run_root=str(tmp_path / f"util_{util}"),
                stage_name="floorplan",
                librelane_config_path="config.yaml",
                resolved_design_config_path="design.yaml",
                patch={"config_vars": {"FP_CORE_UTIL": util}},
                state_in_path=None,
                attempt_dir=attempt_dir,
                timeout_seconds=3600,
            )
            assert result.state_out_path is not None
            with open(result.state_out_path) as f:
                data = json.load(f)
            congestion[util] = data["metrics_snapshot"]["congestion_overflow_pct"]

        # Higher utilization -> more congestion
        assert congestion[30] < congestion[45] < congestion[70]

    async def test_higher_pl_density_worse_timing(self, tmp_path: Path) -> None:
        """Higher PL_TARGET_DENSITY_PCT should produce worse timing slack."""
        wns: dict[int, float] = {}
        for density in [40, 60, 80]:
            adapter = MockExecutionAdapter(success_probability=1.0, noise_seed=42)
            attempt_dir = str(tmp_path / f"density_{density}" / "place_global" / "a1")
            result = await adapter.run_stage(
                run_root=str(tmp_path / f"density_{density}"),
                stage_name="place_global",
                librelane_config_path="config.yaml",
                resolved_design_config_path="design.yaml",
                patch={"config_vars": {"PL_TARGET_DENSITY_PCT": density}},
                state_in_path=None,
                attempt_dir=attempt_dir,
                timeout_seconds=3600,
            )
            assert result.state_out_path is not None
            with open(result.state_out_path) as f:
                data = json.load(f)
            wns[density] = data["metrics_snapshot"]["setup_wns_ns"]

        # Higher density -> worse (more negative) WNS
        assert wns[40] > wns[60] > wns[80]

    async def test_grt_adjustment_affects_congestion(self, tmp_path: Path) -> None:
        """Higher GRT_ADJUSTMENT should increase congestion."""
        congestion: dict[float, float] = {}
        for adj in [0.0, 0.5, 1.0]:
            adapter = MockExecutionAdapter(success_probability=1.0, noise_seed=42)
            attempt_dir = str(
                tmp_path / f"grt_{adj}" / "route_global" / "a1"
            )
            result = await adapter.run_stage(
                run_root=str(tmp_path / f"grt_{adj}"),
                stage_name="route_global",
                librelane_config_path="config.yaml",
                resolved_design_config_path="design.yaml",
                patch={"config_vars": {"GRT_ADJUSTMENT": adj}},
                state_in_path=None,
                attempt_dir=attempt_dir,
                timeout_seconds=3600,
            )
            assert result.state_out_path is not None
            with open(result.state_out_path) as f:
                data = json.load(f)
            congestion[adj] = data["metrics_snapshot"]["congestion_overflow_pct"]

        assert congestion[0.0] < congestion[0.5] < congestion[1.0]


class TestMockFailureInjection:
    """test_mock_failure_injection - failure_mode causes failures."""

    async def test_tool_crash(self, tmp_path: Path) -> None:
        adapter = MockExecutionAdapter(
            success_probability=0.0, failure_mode="tool_crash", noise_seed=42
        )
        attempt_dir = str(tmp_path / "crash" / "floorplan" / "a1")
        result = await adapter.run_stage(
            run_root=str(tmp_path / "crash"),
            stage_name="floorplan",
            librelane_config_path="config.yaml",
            resolved_design_config_path="design.yaml",
            patch={"config_vars": {}},
            state_in_path=None,
            attempt_dir=attempt_dir,
            timeout_seconds=3600,
        )
        assert result.execution_status == "tool_crash"
        assert result.exit_code == 139  # SIGSEGV
        assert result.state_out_path is None
        assert result.stderr_tail is not None
        assert "SIGSEGV" in result.stderr_tail
        assert result.error_summary is not None

    async def test_timeout(self, tmp_path: Path) -> None:
        adapter = MockExecutionAdapter(
            success_probability=0.0, failure_mode="timeout", noise_seed=42
        )
        attempt_dir = str(tmp_path / "timeout" / "floorplan" / "a1")
        result = await adapter.run_stage(
            run_root=str(tmp_path / "timeout"),
            stage_name="floorplan",
            librelane_config_path="config.yaml",
            resolved_design_config_path="design.yaml",
            patch={"config_vars": {}},
            state_in_path=None,
            attempt_dir=attempt_dir,
            timeout_seconds=3600,
        )
        assert result.execution_status == "timeout"
        assert result.exit_code == 124
        assert result.state_out_path is None
        assert result.stderr_tail is not None
        assert "timeout" in result.stderr_tail.lower()

    async def test_oom_killed(self, tmp_path: Path) -> None:
        adapter = MockExecutionAdapter(
            success_probability=0.0, failure_mode="oom_killed", noise_seed=42
        )
        attempt_dir = str(tmp_path / "oom" / "floorplan" / "a1")
        result = await adapter.run_stage(
            run_root=str(tmp_path / "oom"),
            stage_name="floorplan",
            librelane_config_path="config.yaml",
            resolved_design_config_path="design.yaml",
            patch={"config_vars": {}},
            state_in_path=None,
            attempt_dir=attempt_dir,
            timeout_seconds=3600,
        )
        assert result.execution_status == "oom_killed"
        assert result.exit_code == 137  # SIGKILL
        assert result.state_out_path is None
        assert result.stderr_tail is not None
        assert "OOM" in result.stderr_tail

    async def test_crash_log_written(self, tmp_path: Path) -> None:
        adapter = MockExecutionAdapter(
            success_probability=0.0, failure_mode="tool_crash", noise_seed=42
        )
        attempt_dir = str(tmp_path / "crash_log" / "floorplan" / "a1")
        await adapter.run_stage(
            run_root=str(tmp_path / "crash_log"),
            stage_name="floorplan",
            librelane_config_path="config.yaml",
            resolved_design_config_path="design.yaml",
            patch={"config_vars": {}},
            state_in_path=None,
            attempt_dir=attempt_dir,
            timeout_seconds=3600,
        )
        crash_log = os.path.join(attempt_dir, "crash.log")
        assert os.path.isfile(crash_log)
        with open(crash_log) as f:
            content = f.read()
        assert "SIGSEGV" in content

    async def test_per_stage_failure_config(self, tmp_path: Path) -> None:
        """Per-stage configs override global settings."""
        adapter = MockExecutionAdapter(
            success_probability=1.0,  # global: always succeed
            failure_mode="tool_crash",
            noise_seed=42,
            stage_configs={
                "floorplan": {
                    "success_probability": 0.0,
                    "failure_mode": "oom_killed",
                },
            },
        )
        # floorplan should fail (per-stage override)
        attempt_dir = str(tmp_path / "per_stage" / "floorplan" / "a1")
        result = await adapter.run_stage(
            run_root=str(tmp_path / "per_stage"),
            stage_name="floorplan",
            librelane_config_path="config.yaml",
            resolved_design_config_path="design.yaml",
            patch={"config_vars": {}},
            state_in_path=None,
            attempt_dir=attempt_dir,
            timeout_seconds=3600,
        )
        assert result.execution_status == "oom_killed"

        # synth should succeed (global default)
        attempt_dir2 = str(tmp_path / "per_stage" / "synth" / "a1")
        result2 = await adapter.run_stage(
            run_root=str(tmp_path / "per_stage"),
            stage_name="synth",
            librelane_config_path="config.yaml",
            resolved_design_config_path="design.yaml",
            patch={"config_vars": {}},
            state_in_path=None,
            attempt_dir=attempt_dir2,
            timeout_seconds=3600,
        )
        assert result2.execution_status == "success"


class TestMockCreatesDirectoryStructure:
    """test_mock_creates_directory_structure - attempt_dir has workspace/, artifacts/."""

    async def test_workspace_dir_created(
        self, mock_adapter: MockExecutionAdapter, default_run_kwargs: dict
    ) -> None:
        result = await mock_adapter.run_stage(**default_run_kwargs)
        assert os.path.isdir(result.workspace_dir)
        assert result.workspace_dir.endswith("workspace")

    async def test_artifacts_dir_created(
        self, mock_adapter: MockExecutionAdapter, default_run_kwargs: dict
    ) -> None:
        result = await mock_adapter.run_stage(**default_run_kwargs)
        assert os.path.isdir(result.artifacts_dir)
        assert result.artifacts_dir.endswith("artifacts")

    async def test_timing_report_exists(
        self, mock_adapter: MockExecutionAdapter, default_run_kwargs: dict
    ) -> None:
        result = await mock_adapter.run_stage(**default_run_kwargs)
        timing_rpt = os.path.join(result.artifacts_dir, "timing.rpt")
        assert os.path.isfile(timing_rpt)
        with open(timing_rpt) as f:
            content = f.read()
        assert "wns" in content.lower() or "WNS" in content

    async def test_area_report_exists(
        self, mock_adapter: MockExecutionAdapter, default_run_kwargs: dict
    ) -> None:
        result = await mock_adapter.run_stage(**default_run_kwargs)
        area_rpt = os.path.join(result.artifacts_dir, "area.rpt")
        assert os.path.isfile(area_rpt)
        with open(area_rpt) as f:
            content = f.read()
        assert "area" in content.lower()

    async def test_congestion_report_exists(
        self, mock_adapter: MockExecutionAdapter, default_run_kwargs: dict
    ) -> None:
        result = await mock_adapter.run_stage(**default_run_kwargs)
        congestion_rpt = os.path.join(result.artifacts_dir, "congestion.rpt")
        assert os.path.isfile(congestion_rpt)

    async def test_def_file_exists(
        self, mock_adapter: MockExecutionAdapter, default_run_kwargs: dict
    ) -> None:
        result = await mock_adapter.run_stage(**default_run_kwargs)
        def_file = os.path.join(result.artifacts_dir, "floorplan.def")
        assert os.path.isfile(def_file)

    async def test_dirs_inside_attempt_dir(
        self, mock_adapter: MockExecutionAdapter, default_run_kwargs: dict
    ) -> None:
        result = await mock_adapter.run_stage(**default_run_kwargs)
        attempt_dir = default_run_kwargs["attempt_dir"]
        assert result.workspace_dir == os.path.join(attempt_dir, "workspace")
        assert result.artifacts_dir == os.path.join(attempt_dir, "artifacts")
        assert result.attempt_dir == attempt_dir

    async def test_failure_still_creates_dirs(self, tmp_path: Path) -> None:
        """Even on failure, workspace/ and artifacts/ should exist."""
        adapter = MockExecutionAdapter(
            success_probability=0.0, failure_mode="tool_crash", noise_seed=42
        )
        attempt_dir = str(tmp_path / "fail_dirs" / "floorplan" / "a1")
        result = await adapter.run_stage(
            run_root=str(tmp_path / "fail_dirs"),
            stage_name="floorplan",
            librelane_config_path="config.yaml",
            resolved_design_config_path="design.yaml",
            patch={"config_vars": {}},
            state_in_path=None,
            attempt_dir=attempt_dir,
            timeout_seconds=3600,
        )
        assert os.path.isdir(result.workspace_dir)
        assert os.path.isdir(result.artifacts_dir)


# ===========================================================================
# MockExecutionAdapter Validation Tests
# ===========================================================================


class TestMockAdapterValidation:
    """Test constructor validation."""

    def test_invalid_success_probability_high(self) -> None:
        with pytest.raises(ValueError, match="success_probability"):
            MockExecutionAdapter(success_probability=1.5)

    def test_invalid_success_probability_low(self) -> None:
        with pytest.raises(ValueError, match="success_probability"):
            MockExecutionAdapter(success_probability=-0.1)

    def test_invalid_failure_mode(self) -> None:
        with pytest.raises(ValueError, match="failure_mode"):
            MockExecutionAdapter(failure_mode="invalid_mode")

    async def test_unknown_stage_uses_defaults(self, tmp_path: Path) -> None:
        """Unknown stage names should use fallback baselines."""
        adapter = MockExecutionAdapter(success_probability=1.0, noise_seed=42)
        attempt_dir = str(tmp_path / "unknown" / "custom_stage" / "a1")
        result = await adapter.run_stage(
            run_root=str(tmp_path / "unknown"),
            stage_name="custom_stage",
            librelane_config_path="config.yaml",
            resolved_design_config_path="design.yaml",
            patch={"config_vars": {}},
            state_in_path=None,
            attempt_dir=attempt_dir,
            timeout_seconds=3600,
        )
        assert result.execution_status == "success"
        assert result.state_out_path is not None


# ===========================================================================
# MockLLMProvider Tests
# ===========================================================================


class TestMockLLMProvider:
    """Tests for MockLLMProvider."""

    async def test_default_response(self) -> None:
        llm = MockLLMProvider()
        result = await llm.generate("Hello world")
        assert result == {}

    async def test_stage_key_lookup(self) -> None:
        llm = MockLLMProvider(
            responses={"floorplan": {"config_vars": {"FP_CORE_UTIL": 40}}}
        )
        result = await llm.generate("Optimize floorplan", stage="floorplan")
        assert result == {"config_vars": {"FP_CORE_UTIL": 40}}

    async def test_role_key_lookup(self) -> None:
        llm = MockLLMProvider(responses={"judge": "PASS"})
        result = await llm.generate("Judge this", role="judge")
        assert result == "PASS"

    async def test_prompt_hash_takes_priority(self) -> None:
        """Prompt hash match should take priority over stage match."""
        prompt = "Specific prompt"
        prompt_hash = MockLLMProvider._hash_prompt(prompt)
        llm = MockLLMProvider(
            responses={
                prompt_hash: "hash_response",
                "floorplan": "stage_response",
            }
        )
        result = await llm.generate(prompt, stage="floorplan")
        assert result == "hash_response"

    async def test_add_response(self) -> None:
        llm = MockLLMProvider()
        llm.add_response("synth", {"strategy": "DELAY"})
        result = await llm.generate("Optimize synthesis", stage="synth")
        assert result == {"strategy": "DELAY"}

    async def test_call_log_recorded(self) -> None:
        llm = MockLLMProvider()
        await llm.generate("prompt1", stage="floorplan", role="worker")
        await llm.generate("prompt2", stage="synth", role="judge")
        assert llm.call_count == 2
        assert llm.call_log[0]["stage"] == "floorplan"
        assert llm.call_log[1]["role"] == "judge"

    async def test_get_calls_by_role(self) -> None:
        llm = MockLLMProvider()
        await llm.generate("p1", role="worker")
        await llm.generate("p2", role="judge")
        await llm.generate("p3", role="worker")
        worker_calls = llm.get_calls(role="worker")
        assert len(worker_calls) == 2
        judge_calls = llm.get_calls(role="judge")
        assert len(judge_calls) == 1

    async def test_get_calls_for_stage(self) -> None:
        llm = MockLLMProvider()
        await llm.generate("p1", stage="floorplan")
        await llm.generate("p2", stage="synth")
        await llm.generate("p3", stage="floorplan")
        fp_calls = llm.get_calls_for_stage("floorplan")
        assert len(fp_calls) == 2

    async def test_set_default_response(self) -> None:
        llm = MockLLMProvider()
        llm.set_default_response("fallback")
        result = await llm.generate("anything")
        assert result == "fallback"

    async def test_reset_clears_log_keeps_responses(self) -> None:
        llm = MockLLMProvider(responses={"key": "value"})
        await llm.generate("prompt", stage="key")
        assert llm.call_count == 1
        llm.reset()
        assert llm.call_count == 0
        result = await llm.generate("prompt", stage="key")
        assert result == "value"

    async def test_response_model_construction(self) -> None:
        """When response_model is provided and response is a dict, construct it."""
        from pydantic import BaseModel

        class TestModel(BaseModel):
            name: str
            value: int

        llm = MockLLMProvider(responses={"test": {"name": "foo", "value": 42}})
        result = await llm.generate("prompt", response_model=TestModel, stage="test")
        assert isinstance(result, TestModel)
        assert result.name == "foo"
        assert result.value == 42
