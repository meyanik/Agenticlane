"""Tests for EvidencePack assembly pipeline.

Tests the full assembly pipeline that runs all extractors and produces
MetricsPayload + EvidencePack objects.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agenticlane.config.models import DistillConfig
from agenticlane.distill.evidence import assemble_evidence, build_constraint_digest
from agenticlane.schemas.evidence import EvidencePack
from agenticlane.schemas.execution import ExecutionResult
from agenticlane.schemas.metrics import MetricsPayload

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_success_result(attempt_dir: Path) -> ExecutionResult:
    """Create a success ExecutionResult."""
    return ExecutionResult(
        execution_status="success",
        exit_code=0,
        runtime_seconds=42.5,
        attempt_dir=str(attempt_dir),
        workspace_dir=str(attempt_dir / "workspace"),
        artifacts_dir=str(attempt_dir / "artifacts"),
        state_out_path=str(attempt_dir / "state_out.json"),
        stderr_tail=None,
        error_summary=None,
    )


def _make_failure_result(attempt_dir: Path) -> ExecutionResult:
    """Create a failure ExecutionResult."""
    return ExecutionResult(
        execution_status="tool_crash",
        exit_code=139,
        runtime_seconds=10.0,
        attempt_dir=str(attempt_dir),
        workspace_dir=str(attempt_dir / "workspace"),
        artifacts_dir=str(attempt_dir / "artifacts"),
        state_out_path=None,
        stderr_tail="SIGSEGV at foo.cpp:42\nAborted",
        error_summary="Stage failed with tool_crash",
    )


def _setup_full_attempt(tmp_path: Path) -> Path:
    """Create a fully-populated attempt directory with all reports."""
    attempt = tmp_path / "attempt_001"
    artifacts = attempt / "artifacts"
    artifacts.mkdir(parents=True)
    (attempt / "workspace").mkdir()

    # timing.rpt
    (artifacts / "timing.rpt").write_text(
        "wns -0.1500\n"
        "tns -1.5000\n"
        "Clock clk Period: 10.000\n"
        "  Setup WNS: -0.1500 ns\n"
        "  Setup TNS: -1.5000 ns\n"
    )

    # area.rpt
    (artifacts / "area.rpt").write_text(
        "Design area 500000.00 u^2\n"
        "Core utilization: 45.00%\n"
        "  Core area: 500000.00 um^2\n"
        "  Utilization: 45.00%\n"
    )

    # congestion.rpt
    (artifacts / "congestion.rpt").write_text("Overflow: 2.0000%\n")

    # state_out.json
    state = {
        "stage": "synth",
        "status": "success",
        "metrics_snapshot": {
            "setup_wns_ns": -0.15,
            "core_area_um2": 500000.0,
            "utilization_pct": 45.0,
            "congestion_overflow_pct": 2.0,
        },
    }
    (attempt / "state_out.json").write_text(json.dumps(state))

    # power.rpt
    (artifacts / "power.rpt").write_text(
        "Group    Internal  Switching  Leakage    Total\n"
        "Total    5.00e-03  3.00e-03   2.00e-03   1.00e-02\n"
    )

    # SDC file
    (artifacts / "synth.sdc").write_text(
        "create_clock -name core_clk -period 10.0 [get_ports clk]\n"
        "set_false_path -from [get_ports reset]\n"
    )

    return attempt


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAssembleEvidence:
    @pytest.mark.asyncio
    async def test_full_assembly(self, tmp_path: Path) -> None:
        """Full assembly produces valid MetricsPayload + EvidencePack."""
        attempt = _setup_full_attempt(tmp_path)
        result = _make_success_result(attempt)
        config = DistillConfig()

        metrics, evidence = await assemble_evidence(
            attempt_dir=attempt,
            stage_name="synth",
            attempt_num=1,
            execution_result=result,
            config=config,
            run_id="test_run",
            branch_id="B0",
        )

        # MetricsPayload checks
        assert isinstance(metrics, MetricsPayload)
        assert metrics.schema_version == 3
        assert metrics.run_id == "test_run"
        assert metrics.branch_id == "B0"
        assert metrics.stage == "synth"
        assert metrics.attempt == 1
        assert metrics.execution_status == "success"

        # Timing
        assert metrics.timing is not None
        assert metrics.timing.setup_wns_ns.get("default") == pytest.approx(-0.15)

        # Physical
        assert metrics.physical is not None
        assert metrics.physical.core_area_um2 == pytest.approx(500000.0)
        assert metrics.physical.utilization_pct == pytest.approx(45.0)

        # Route
        assert metrics.route is not None
        assert metrics.route.congestion_overflow_pct == pytest.approx(2.0)

        # Runtime
        assert metrics.runtime is not None
        assert metrics.runtime.stage_seconds == pytest.approx(42.5)

        # Power
        assert metrics.power is not None
        assert metrics.power.total_power_mw == pytest.approx(10.0)
        assert metrics.power.internal_power_mw == pytest.approx(5.0)
        assert metrics.power.switching_power_mw == pytest.approx(3.0)
        assert metrics.power.leakage_power_mw == pytest.approx(2.0)
        assert metrics.power.leakage_pct == pytest.approx(20.0)

        # EvidencePack checks
        assert isinstance(evidence, EvidencePack)
        assert evidence.schema_version == 1
        assert evidence.stage == "synth"
        assert evidence.attempt == 1
        assert evidence.execution_status == "success"
        assert evidence.crash_info is None
        assert len(evidence.errors) == 0

    @pytest.mark.asyncio
    async def test_assembly_with_crash(self, tmp_path: Path) -> None:
        """Assembly handles crashed execution correctly."""
        attempt = tmp_path / "attempt_crash"
        artifacts = attempt / "artifacts"
        artifacts.mkdir(parents=True)
        (attempt / "workspace").mkdir()

        # Write crash.log
        (attempt / "crash.log").write_text(
            "OpenROAD crashed with SIGSEGV at route.cpp:100\n"
            "Aborted (core dumped)\n"
        )

        result = _make_failure_result(attempt)
        config = DistillConfig()

        metrics, evidence = await assemble_evidence(
            attempt_dir=attempt,
            stage_name="route_detail",
            attempt_num=2,
            execution_result=result,
            config=config,
            run_id="test_run",
            branch_id="B0",
        )

        assert metrics.execution_status == "tool_crash"
        assert evidence.crash_info is not None
        assert evidence.crash_info.crash_type == "tool_crash"
        assert evidence.stderr_tail is not None
        assert len(evidence.errors) > 0  # error_summary should be captured

    @pytest.mark.asyncio
    async def test_assembly_with_empty_dir(self, tmp_path: Path) -> None:
        """Assembly handles empty attempt dir gracefully."""
        attempt = tmp_path / "attempt_empty"
        attempt.mkdir()

        result = _make_success_result(attempt)
        config = DistillConfig()

        metrics, evidence = await assemble_evidence(
            attempt_dir=attempt,
            stage_name="synth",
            attempt_num=1,
            execution_result=result,
            config=config,
        )

        assert isinstance(metrics, MetricsPayload)
        assert isinstance(evidence, EvidencePack)
        # Missing metrics should be recorded
        assert len(metrics.missing_metrics) > 0

    @pytest.mark.asyncio
    async def test_assembly_spatial_hotspots(self, tmp_path: Path) -> None:
        """Assembly includes spatial hotspots when congestion is present."""
        attempt = _setup_full_attempt(tmp_path)
        result = _make_success_result(attempt)
        config = DistillConfig()

        metrics, evidence = await assemble_evidence(
            attempt_dir=attempt,
            stage_name="route_global",
            attempt_num=1,
            execution_result=result,
            config=config,
        )

        # Should have spatial hotspots from 2% overflow
        assert len(evidence.spatial_hotspots) > 0
        for h in evidence.spatial_hotspots:
            assert h.type == "congestion"
            assert h.severity >= 0.0

    @pytest.mark.asyncio
    async def test_runtime_from_execution_result(self, tmp_path: Path) -> None:
        """Runtime is taken from ExecutionResult when not in state_out."""
        attempt = tmp_path / "attempt_runtime"
        attempt.mkdir()

        result = ExecutionResult(
            execution_status="success",
            exit_code=0,
            runtime_seconds=99.9,
            attempt_dir=str(attempt),
            workspace_dir=str(attempt / "workspace"),
            artifacts_dir=str(attempt / "artifacts"),
            state_out_path=None,
            stderr_tail=None,
            error_summary=None,
        )
        config = DistillConfig()

        metrics, _ = await assemble_evidence(
            attempt_dir=attempt,
            stage_name="synth",
            attempt_num=1,
            execution_result=result,
            config=config,
        )

        assert metrics.runtime is not None
        assert metrics.runtime.stage_seconds == pytest.approx(99.9)

    @pytest.mark.asyncio
    async def test_constraint_digest_in_bounded_snippets(
        self, tmp_path: Path
    ) -> None:
        """Constraint digest info appears in bounded_snippets."""
        attempt = _setup_full_attempt(tmp_path)
        result = _make_success_result(attempt)
        config = DistillConfig()

        _, evidence = await assemble_evidence(
            attempt_dir=attempt,
            stage_name="synth",
            attempt_num=1,
            execution_result=result,
            config=config,
        )

        # Should have a constraints snippet
        constraint_snippets = [
            s for s in evidence.bounded_snippets if s["source"] == "constraints"
        ]
        assert len(constraint_snippets) > 0
        assert "core_clk" in constraint_snippets[0]["content"]


class TestBuildConstraintDigest:
    def test_builds_from_raw(self) -> None:
        raw = {
            "opaque": False,
            "clocks": [
                {"name": "clk", "period_ns": 10.0, "targets": ["clk"]},
            ],
            "exceptions": {
                "false_path_count": 2,
                "multicycle_path_count": 1,
                "disable_timing_count": 0,
            },
            "delays": {
                "set_max_delay_count": 1,
                "set_min_delay_count": 0,
            },
            "uncertainty": {
                "set_clock_uncertainty_count": 1,
            },
            "notes": [],
        }

        cd = build_constraint_digest(raw)

        assert cd.schema_version == 1
        assert len(cd.clocks) == 1
        assert cd.clocks[0].name == "clk"
        assert cd.clocks[0].period_ns == pytest.approx(10.0)
        assert cd.exceptions.false_path_count == 2
        assert cd.exceptions.multicycle_path_count == 1
        assert cd.delays.set_max_delay_count == 1
        assert cd.uncertainty.set_clock_uncertainty_count == 1

    def test_builds_from_empty(self) -> None:
        cd = build_constraint_digest({})
        assert cd.clocks == []
        assert cd.exceptions.false_path_count == 0
