"""Tests for AgenticLane canonical schemas.

Verifies serialization/deserialization roundtrip, correct default values,
and schema version enforcement for all Appendix A schemas.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from agenticlane.schemas.constraints import (
    ClockDefinition,
    ConstraintDigest,
    DelayCounts,
    ExceptionCounts,
    UncertaintyCounts,
)
from agenticlane.schemas.evidence import (
    CrashInfo,
    ErrorWarning,
    EvidencePack,
    SpatialHotspot,
)
from agenticlane.schemas.execution import ExecutionResult
from agenticlane.schemas.judge import BlockingIssue, JudgeAggregate, JudgeVote
from agenticlane.schemas.llm import LLMCallRecord
from agenticlane.schemas.metrics import (
    MetricsPayload,
    PhysicalMetrics,
    PowerMetrics,
    RouteMetrics,
    RuntimeMetrics,
    SignoffMetrics,
    TimingMetrics,
)
from agenticlane.schemas.patch import (
    MacroPlacement,
    Patch,
    PatchRejected,
    SDCEdit,
    TclEdit,
)


class TestPatchV5:
    """Tests for Patch schema version 5."""

    def _make_patch(self) -> Patch:
        """Create a fully populated Patch instance matching Appendix A1."""
        return Patch(
            patch_id="test-patch-001",
            stage="FLOORPLAN",
            types=["config_vars", "macro_placements", "sdc_edits", "tcl_edits"],
            config_vars={"FP_CORE_UTIL": 55},
            macro_placements=[
                MacroPlacement(
                    instance="U_SRAM_0",
                    location_hint="SW",
                    x_um=None,
                    y_um=None,
                    orientation="N",
                ),
            ],
            sdc_edits=[
                SDCEdit(
                    name="agent_floorplan.sdc",
                    mode="append_lines",
                    lines=[
                        "set_input_delay 1.0 -clock core_clk [get_clocks core_clk] [get_ports in0]"
                    ],
                ),
            ],
            tcl_edits=[
                TclEdit(
                    name="post_gp_fix.tcl",
                    tool="openroad",
                    hook={"type": "post_step", "step_id": "OpenROAD.GlobalPlacement"},
                    mode="append_lines",
                    lines=["# example hook", 'puts "Hello"'],
                ),
            ],
            rtl_changes=None,
            declared_constraint_changes={"CLOCK_PERIOD": None},
            rationale="Relieve localized congestion; do not relax user constraints.",
        )

    def test_patch_v5_roundtrip(self) -> None:
        """Patch serializes to JSON and deserializes back identically."""
        patch = self._make_patch()
        json_str = patch.model_dump_json()
        restored = Patch.model_validate_json(json_str)

        assert restored == patch
        assert restored.patch_id == "test-patch-001"
        assert restored.stage == "FLOORPLAN"
        assert len(restored.macro_placements) == 1
        assert restored.macro_placements[0].instance == "U_SRAM_0"
        assert len(restored.sdc_edits) == 1
        assert len(restored.tcl_edits) == 1
        assert restored.tcl_edits[0].hook["step_id"] == "OpenROAD.GlobalPlacement"
        assert restored.config_vars["FP_CORE_UTIL"] == 55
        assert restored.declared_constraint_changes["CLOCK_PERIOD"] is None

    def test_patch_v5_version_field(self) -> None:
        """Patch always has schema_version=5 and rejects other versions."""
        patch = self._make_patch()
        assert patch.schema_version == 5

        # Verify schema_version appears in serialized JSON
        data = patch.model_dump()
        assert data["schema_version"] == 5

        # Verify that a different version is rejected
        data["schema_version"] = 4
        with pytest.raises(ValidationError):
            Patch.model_validate(data)

    def test_patch_v5_defaults(self) -> None:
        """Patch with minimal fields has correct defaults."""
        patch = Patch(patch_id="minimal", stage="SYNTH")

        assert patch.schema_version == 5
        assert patch.types == []
        assert patch.config_vars == {}
        assert patch.macro_placements == []
        assert patch.sdc_edits == []
        assert patch.tcl_edits == []
        assert patch.rtl_changes is None
        assert patch.declared_constraint_changes == {}
        assert patch.rationale == ""


class TestPatchRejectedV1:
    """Tests for PatchRejected schema version 1."""

    def test_patch_rejected_v1(self) -> None:
        """PatchRejected roundtrips correctly with all fields."""
        rejected = PatchRejected(
            patch_id="test-patch-001",
            stage="PLACE_GLOBAL",
            reason_code="locked_constraint_backdoor",
            offending_channel="sdc_edits",
            offending_commands=["create_clock"],
            offending_lines=[1],
            remediation_hint=(
                "CLOCK_PERIOD is locked. Improve timing via "
                "placement/CTS/routing knobs, not constraints."
            ),
        )

        assert rejected.schema_version == 1

        # Roundtrip
        json_str = rejected.model_dump_json()
        restored = PatchRejected.model_validate_json(json_str)
        assert restored == rejected
        assert restored.reason_code == "locked_constraint_backdoor"
        assert restored.offending_channel == "sdc_edits"
        assert restored.offending_commands == ["create_clock"]
        assert restored.offending_lines == [1]
        assert "CLOCK_PERIOD is locked" in restored.remediation_hint

    def test_patch_rejected_defaults(self) -> None:
        """PatchRejected with minimal fields has correct defaults."""
        rejected = PatchRejected(
            patch_id="rej-1",
            stage="SYNTH",
            reason_code="forbidden_command",
            offending_channel="tcl_edits",
        )
        assert rejected.offending_commands == []
        assert rejected.offending_lines == []
        assert rejected.remediation_hint == ""


class TestMetricsPayloadV3:
    """Tests for MetricsPayload schema version 3."""

    def _make_metrics(self) -> MetricsPayload:
        """Create a fully populated MetricsPayload matching Appendix A3."""
        return MetricsPayload(
            run_id="run_abcdef",
            branch_id="B0",
            stage="PLACE_GLOBAL",
            attempt=2,
            execution_status="success",
            missing_metrics=[],
            constraints_digest_path="constraints/constraints_digest.json",
            timing=TimingMetrics(setup_wns_ns={"tt": -0.10}),
            physical=PhysicalMetrics(
                core_area_um2=1_500_000.0, utilization_pct=72.5
            ),
            route=RouteMetrics(congestion_overflow_pct=8.2),
            signoff=SignoffMetrics(drc_count=None, lvs_pass=None),
            runtime=RuntimeMetrics(stage_seconds=312.4),
        )

    def test_metrics_payload_v3_roundtrip(self) -> None:
        """MetricsPayload serializes to JSON and deserializes identically."""
        metrics = self._make_metrics()
        json_str = metrics.model_dump_json()
        restored = MetricsPayload.model_validate_json(json_str)

        assert restored == metrics
        assert restored.schema_version == 3
        assert restored.run_id == "run_abcdef"
        assert restored.branch_id == "B0"
        assert restored.execution_status == "success"
        assert restored.timing is not None
        assert restored.timing.setup_wns_ns["tt"] == pytest.approx(-0.10)
        assert restored.physical is not None
        assert restored.physical.core_area_um2 == pytest.approx(1_500_000.0)
        assert restored.physical.utilization_pct == pytest.approx(72.5)
        assert restored.route is not None
        assert restored.route.congestion_overflow_pct == pytest.approx(8.2)
        assert restored.signoff is not None
        assert restored.signoff.drc_count is None
        assert restored.signoff.lvs_pass is None
        assert restored.runtime is not None
        assert restored.runtime.stage_seconds == pytest.approx(312.4)

    def test_metrics_payload_v3_version(self) -> None:
        """MetricsPayload always has schema_version=3."""
        metrics = self._make_metrics()
        assert metrics.schema_version == 3

        data = metrics.model_dump()
        data["schema_version"] = 2
        with pytest.raises(ValidationError):
            MetricsPayload.model_validate(data)

    def test_metrics_payload_with_power(self) -> None:
        """MetricsPayload with power sub-metrics roundtrips correctly."""
        metrics = MetricsPayload(
            run_id="run_power",
            branch_id="B0",
            stage="CTS",
            attempt=1,
            execution_status="success",
            power=PowerMetrics(
                total_power_mw=10.5,
                internal_power_mw=5.0,
                switching_power_mw=3.5,
                leakage_power_mw=2.0,
                leakage_pct=19.05,
            ),
        )

        json_str = metrics.model_dump_json()
        restored = MetricsPayload.model_validate_json(json_str)
        assert restored.power is not None
        assert restored.power.total_power_mw == pytest.approx(10.5)
        assert restored.power.internal_power_mw == pytest.approx(5.0)
        assert restored.power.switching_power_mw == pytest.approx(3.5)
        assert restored.power.leakage_power_mw == pytest.approx(2.0)
        assert restored.power.leakage_pct == pytest.approx(19.05)

    def test_metrics_payload_null_sub_metrics(self) -> None:
        """MetricsPayload with all null optional sub-metrics is valid."""
        metrics = MetricsPayload(
            run_id="run_xyz",
            branch_id="B1",
            stage="SYNTH",
            attempt=1,
            execution_status="tool_crash",
            missing_metrics=["timing", "physical", "route"],
        )
        assert metrics.timing is None
        assert metrics.physical is None
        assert metrics.route is None
        assert metrics.signoff is None
        assert metrics.runtime is None
        assert metrics.power is None


class TestEvidencePack:
    """Tests for EvidencePack schema version 1."""

    def _make_evidence(self) -> EvidencePack:
        """Create a fully populated EvidencePack."""
        return EvidencePack(
            stage="ROUTE_DETAILED",
            attempt=3,
            execution_status="success",
            errors=[
                ErrorWarning(
                    source="openroad.log",
                    severity="error",
                    message="DRC violation: metal2 spacing",
                    count=5,
                ),
            ],
            warnings=[
                ErrorWarning(
                    source="openroad.log",
                    severity="warning",
                    message="High congestion in region NE",
                    count=1,
                ),
            ],
            spatial_hotspots=[
                SpatialHotspot(
                    type="congestion",
                    grid_bin={"x": 12, "y": 8},
                    region_label="NE quadrant",
                    severity=0.85,
                    nearby_macros=["U_SRAM_0", "U_SRAM_1"],
                ),
                SpatialHotspot(
                    type="drc",
                    grid_bin={"x": 3, "y": 2},
                    region_label="SW quadrant",
                    severity=0.4,
                    nearby_macros=[],
                ),
            ],
            crash_info=None,
            missing_reports=[],
            stderr_tail=None,
            bounded_snippets=[
                {"source": "timing.rpt", "content": "WNS: -0.10 ns"},
            ],
        )

    def test_evidence_pack_roundtrip(self) -> None:
        """EvidencePack serializes to JSON and deserializes identically."""
        evidence = self._make_evidence()
        json_str = evidence.model_dump_json()
        restored = EvidencePack.model_validate_json(json_str)

        assert restored == evidence
        assert restored.schema_version == 1
        assert restored.stage == "ROUTE_DETAILED"
        assert restored.attempt == 3
        assert len(restored.errors) == 1
        assert restored.errors[0].severity == "error"
        assert restored.errors[0].count == 5
        assert len(restored.warnings) == 1
        assert len(restored.spatial_hotspots) == 2
        assert restored.spatial_hotspots[0].type == "congestion"
        assert restored.spatial_hotspots[0].grid_bin == {"x": 12, "y": 8}
        assert restored.spatial_hotspots[0].nearby_macros == ["U_SRAM_0", "U_SRAM_1"]
        assert restored.crash_info is None
        assert len(restored.bounded_snippets) == 1

    def test_evidence_pack_with_crash(self) -> None:
        """EvidencePack with crash info roundtrips correctly."""
        evidence = EvidencePack(
            stage="SYNTH",
            attempt=1,
            execution_status="tool_crash",
            crash_info=CrashInfo(
                crash_type="tool_crash",
                stderr_tail="Segmentation fault (core dumped)",
                error_signature="SEGFAULT_yosys_synthesis",
            ),
            stderr_tail="Segmentation fault (core dumped)",
        )

        json_str = evidence.model_dump_json()
        restored = EvidencePack.model_validate_json(json_str)
        assert restored.crash_info is not None
        assert restored.crash_info.crash_type == "tool_crash"
        assert "Segmentation fault" in (restored.crash_info.stderr_tail or "")

    def test_evidence_pack_defaults(self) -> None:
        """EvidencePack with minimal fields has correct defaults."""
        evidence = EvidencePack(
            stage="FLOORPLAN",
            attempt=1,
            execution_status="success",
        )
        assert evidence.errors == []
        assert evidence.warnings == []
        assert evidence.spatial_hotspots == []
        assert evidence.crash_info is None
        assert evidence.missing_reports == []
        assert evidence.stderr_tail is None
        assert evidence.bounded_snippets == []


class TestJudgeVote:
    """Tests for JudgeVote and JudgeAggregate."""

    def test_judge_vote_roundtrip(self) -> None:
        """JudgeVote and JudgeAggregate serialize and deserialize correctly."""
        vote_pass = JudgeVote(
            judge_id="judge-0",
            model="openai/local-model",
            vote="PASS",
            confidence=0.85,
            blocking_issues=[],
            rationale="Timing improved, area within budget.",
        )
        vote_fail = JudgeVote(
            judge_id="judge-1",
            model="openai/local-model",
            vote="FAIL",
            confidence=0.70,
            blocking_issues=[
                BlockingIssue(
                    metric_key="setup_wns_ns.tt",
                    description="Setup WNS degraded from -0.05 to -0.15",
                    severity="high",
                ),
            ],
            rationale="Timing regression is unacceptable.",
        )

        # Test individual vote roundtrip
        json_str = vote_pass.model_dump_json()
        restored_pass = JudgeVote.model_validate_json(json_str)
        assert restored_pass == vote_pass
        assert restored_pass.vote == "PASS"
        assert restored_pass.confidence == pytest.approx(0.85)

        json_str = vote_fail.model_dump_json()
        restored_fail = JudgeVote.model_validate_json(json_str)
        assert restored_fail == vote_fail
        assert restored_fail.vote == "FAIL"
        assert len(restored_fail.blocking_issues) == 1
        assert restored_fail.blocking_issues[0].metric_key == "setup_wns_ns.tt"

        # Test aggregate roundtrip
        aggregate = JudgeAggregate(
            votes=[vote_pass, vote_fail],
            result="FAIL",
            confidence=0.70,
            blocking_issues=vote_fail.blocking_issues,
        )

        json_str = aggregate.model_dump_json()
        restored_agg = JudgeAggregate.model_validate_json(json_str)
        assert restored_agg == aggregate
        assert restored_agg.result == "FAIL"
        assert len(restored_agg.votes) == 2
        assert restored_agg.votes[0].vote == "PASS"
        assert restored_agg.votes[1].vote == "FAIL"

    def test_judge_vote_confidence_bounds(self) -> None:
        """JudgeVote rejects confidence values outside [0.0, 1.0]."""
        with pytest.raises(ValidationError):
            JudgeVote(
                judge_id="j0",
                model="m",
                vote="PASS",
                confidence=1.5,
            )

        with pytest.raises(ValidationError):
            JudgeVote(
                judge_id="j0",
                model="m",
                vote="PASS",
                confidence=-0.1,
            )


class TestExecutionResult:
    """Tests for ExecutionResult."""

    def test_execution_result_success(self) -> None:
        """ExecutionResult for a successful execution roundtrips correctly."""
        result = ExecutionResult(
            execution_status="success",
            exit_code=0,
            runtime_seconds=245.7,
            attempt_dir="/runs/run_abc/branches/B0/stages/SYNTH/attempt_001",
            workspace_dir="/runs/run_abc/branches/B0/stages/SYNTH/attempt_001/workspace",
            artifacts_dir="/runs/run_abc/branches/B0/stages/SYNTH/attempt_001/artifacts",
            state_out_path="/runs/run_abc/branches/B0/stages/SYNTH/attempt_001/state_out.json",
            stderr_tail=None,
            error_summary=None,
        )

        json_str = result.model_dump_json()
        restored = ExecutionResult.model_validate_json(json_str)
        assert restored == result
        assert restored.execution_status == "success"
        assert restored.exit_code == 0
        assert restored.runtime_seconds == pytest.approx(245.7)
        assert restored.state_out_path is not None
        assert restored.stderr_tail is None
        assert restored.error_summary is None

    def test_execution_result_failure(self) -> None:
        """ExecutionResult for a failed execution captures error details."""
        result = ExecutionResult(
            execution_status="tool_crash",
            exit_code=139,
            runtime_seconds=12.3,
            attempt_dir="/runs/run_abc/branches/B0/stages/SYNTH/attempt_001",
            workspace_dir="/runs/run_abc/branches/B0/stages/SYNTH/attempt_001/workspace",
            artifacts_dir="/runs/run_abc/branches/B0/stages/SYNTH/attempt_001/artifacts",
            state_out_path=None,
            stderr_tail="Segmentation fault (core dumped)\nYosys crashed",
            error_summary="Yosys crashed with SIGSEGV during synthesis",
        )

        json_str = result.model_dump_json()
        restored = ExecutionResult.model_validate_json(json_str)
        assert restored == result
        assert restored.execution_status == "tool_crash"
        assert restored.exit_code == 139
        assert restored.state_out_path is None
        assert "Segmentation fault" in (restored.stderr_tail or "")
        assert "SIGSEGV" in (restored.error_summary or "")

    def test_execution_result_all_statuses(self) -> None:
        """ExecutionResult accepts all valid ExecutionStatus values."""
        statuses = [
            "success",
            "tool_crash",
            "timeout",
            "oom_killed",
            "config_error",
            "patch_rejected",
            "unknown_fail",
        ]
        for status in statuses:
            result = ExecutionResult(
                execution_status=status,  # type: ignore[arg-type]
                exit_code=1,
                runtime_seconds=0.0,
                attempt_dir="/tmp/test",
                workspace_dir="/tmp/test/workspace",
                artifacts_dir="/tmp/test/artifacts",
            )
            assert result.execution_status == status


class TestLLMCallRecord:
    """Tests for LLMCallRecord."""

    def test_llm_call_record(self) -> None:
        """LLMCallRecord roundtrips correctly with all fields."""
        record = LLMCallRecord(
            timestamp="2025-01-15T10:30:00Z",
            call_id="call-uuid-001",
            model="openai/local-model",
            provider="litellm",
            role="worker",
            stage="PLACE_GLOBAL",
            attempt=2,
            branch="B0",
            parameters={"temperature": 0.7, "max_tokens": 4096},
            prompt_hash="sha256:abc123def456",
            response_hash="sha256:789ghi012jkl",
            latency_ms=1250,
            tokens_in=2048,
            tokens_out=512,
            structured_output_valid=True,
            retries=0,
            error=None,
        )

        json_str = record.model_dump_json()
        restored = LLMCallRecord.model_validate_json(json_str)
        assert restored == record
        assert restored.timestamp == "2025-01-15T10:30:00Z"
        assert restored.model == "openai/local-model"
        assert restored.role == "worker"
        assert restored.latency_ms == 1250
        assert restored.tokens_in == 2048
        assert restored.tokens_out == 512
        assert restored.structured_output_valid is True
        assert restored.retries == 0
        assert restored.error is None
        assert restored.parameters["temperature"] == 0.7

    def test_llm_call_record_with_error(self) -> None:
        """LLMCallRecord captures error information."""
        record = LLMCallRecord(
            timestamp="2025-01-15T10:31:00Z",
            call_id="call-uuid-002",
            model="openai/local-model",
            provider="litellm",
            role="judge",
            stage="SYNTH",
            attempt=1,
            branch="B0",
            parameters={"temperature": 0.0},
            prompt_hash="sha256:prompt_hash",
            response_hash="sha256:empty",
            latency_ms=5000,
            tokens_in=1024,
            tokens_out=0,
            structured_output_valid=False,
            retries=3,
            error="Connection refused: LM Studio not running",
        )

        json_str = record.model_dump_json()
        restored = LLMCallRecord.model_validate_json(json_str)
        assert restored.structured_output_valid is False
        assert restored.retries == 3
        assert "Connection refused" in (restored.error or "")

    def test_llm_call_record_defaults(self) -> None:
        """LLMCallRecord uses correct defaults for optional fields."""
        record = LLMCallRecord(
            timestamp="2025-01-15T10:30:00Z",
            call_id="call-uuid-003",
            model="anthropic/claude-3",
            provider="anthropic",
            role="master",
            stage="FLOORPLAN",
            attempt=1,
            branch="B1",
            prompt_hash="sha256:hash",
            response_hash="sha256:hash",
            latency_ms=800,
            tokens_in=500,
            tokens_out=200,
        )
        assert record.parameters == {}
        assert record.structured_output_valid is True
        assert record.retries == 0
        assert record.error is None


class TestConstraintDigestV1:
    """Tests for ConstraintDigest schema version 1."""

    def test_constraint_digest_v1(self) -> None:
        """ConstraintDigest roundtrips correctly matching Appendix A4."""
        digest = ConstraintDigest(
            opaque=False,
            clocks=[
                ClockDefinition(
                    name="core_clk",
                    period_ns=10.0,
                    targets=["clk"],
                ),
            ],
            exceptions=ExceptionCounts(
                false_path_count=0,
                multicycle_path_count=0,
                disable_timing_count=0,
            ),
            delays=DelayCounts(
                set_max_delay_count=0,
                set_min_delay_count=0,
            ),
            uncertainty=UncertaintyCounts(
                set_clock_uncertainty_count=0,
            ),
            notes=[],
        )

        assert digest.schema_version == 1

        json_str = digest.model_dump_json()
        restored = ConstraintDigest.model_validate_json(json_str)
        assert restored == digest
        assert restored.opaque is False
        assert len(restored.clocks) == 1
        assert restored.clocks[0].name == "core_clk"
        assert restored.clocks[0].period_ns == pytest.approx(10.0)
        assert restored.clocks[0].targets == ["clk"]
        assert restored.exceptions.false_path_count == 0
        assert restored.delays.set_max_delay_count == 0
        assert restored.uncertainty.set_clock_uncertainty_count == 0

    def test_constraint_digest_defaults(self) -> None:
        """ConstraintDigest with all defaults is valid."""
        digest = ConstraintDigest()
        assert digest.schema_version == 1
        assert digest.opaque is False
        assert digest.clocks == []
        assert digest.exceptions.false_path_count == 0
        assert digest.exceptions.multicycle_path_count == 0
        assert digest.exceptions.disable_timing_count == 0
        assert digest.delays.set_max_delay_count == 0
        assert digest.delays.set_min_delay_count == 0
        assert digest.uncertainty.set_clock_uncertainty_count == 0
        assert digest.notes == []

    def test_constraint_digest_version_enforced(self) -> None:
        """ConstraintDigest rejects invalid schema versions."""
        data = ConstraintDigest().model_dump()
        data["schema_version"] = 2
        with pytest.raises(ValidationError):
            ConstraintDigest.model_validate(data)

    def test_constraint_digest_multiple_clocks(self) -> None:
        """ConstraintDigest handles multiple clock definitions."""
        digest = ConstraintDigest(
            clocks=[
                ClockDefinition(name="core_clk", period_ns=10.0, targets=["clk"]),
                ClockDefinition(name="io_clk", period_ns=5.0, targets=["io_clk_pin"]),
            ],
            exceptions=ExceptionCounts(
                false_path_count=2,
                multicycle_path_count=1,
            ),
        )

        json_str = digest.model_dump_json()
        restored = ConstraintDigest.model_validate_json(json_str)
        assert len(restored.clocks) == 2
        assert restored.clocks[1].period_ns == pytest.approx(5.0)
        assert restored.exceptions.false_path_count == 2


class TestJsonSerializationConsistency:
    """Cross-cutting tests for JSON serialization consistency."""

    def test_all_schemas_produce_valid_json(self) -> None:
        """All schemas produce valid JSON that can be parsed by json.loads."""
        models = [
            ExecutionResult(
                execution_status="success",
                exit_code=0,
                runtime_seconds=1.0,
                attempt_dir="/tmp",
                workspace_dir="/tmp/ws",
                artifacts_dir="/tmp/art",
            ),
            Patch(patch_id="p1", stage="SYNTH"),
            PatchRejected(
                patch_id="p1",
                stage="SYNTH",
                reason_code="test",
                offending_channel="config_vars",
            ),
            MetricsPayload(
                run_id="r1",
                branch_id="B0",
                stage="SYNTH",
                attempt=1,
                execution_status="success",
            ),
            EvidencePack(stage="SYNTH", attempt=1, execution_status="success"),
            ConstraintDigest(),
            JudgeVote(
                judge_id="j0",
                model="m",
                vote="PASS",
                confidence=0.5,
            ),
            JudgeAggregate(
                result="PASS",
                confidence=0.5,
            ),
            LLMCallRecord(
                timestamp="2025-01-01T00:00:00Z",
                call_id="c1",
                model="m",
                provider="p",
                role="worker",
                stage="SYNTH",
                attempt=1,
                branch="B0",
                prompt_hash="h1",
                response_hash="h2",
                latency_ms=100,
                tokens_in=10,
                tokens_out=10,
            ),
        ]

        for model in models:
            json_str = model.model_dump_json()
            # Verify it is valid JSON
            parsed = json.loads(json_str)
            assert isinstance(parsed, dict), f"{type(model).__name__} did not produce a JSON object"

    def test_model_dump_dict_roundtrip(self) -> None:
        """All schemas roundtrip through model_dump() -> model_validate()."""
        patch = Patch(
            patch_id="roundtrip-test",
            stage="CTS",
            types=["config_vars"],
            config_vars={"CTS_CLK_MAX_WIRE_LENGTH": 500},
        )
        data = patch.model_dump()
        restored = Patch.model_validate(data)
        assert restored == patch
