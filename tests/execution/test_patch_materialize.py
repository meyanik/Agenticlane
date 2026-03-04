"""Tests for the patch materialization pipeline (P2.6).

Verifies:
- Steps execute in exact 1-8 order
- Early rejection at steps 1-3 raises EarlyRejectionError
- SDC and Tcl fragments written to correct files
- Config overrides applied
- No side effects on early rejection
- Full pipeline success with all steps
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from agenticlane.execution.patch_materialize import (
    EarlyRejectionError,
    PatchMaterializer,
)
from agenticlane.schemas.patch import (
    Patch,
    PatchRejected,
    SDCEdit,
    TclEdit,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_patch(
    patch_id: str = "test-patch-001",
    config_vars: dict[str, Any] | None = None,
    sdc_edits: list[SDCEdit] | None = None,
    tcl_edits: list[TclEdit] | None = None,
) -> Patch:
    """Create a Patch with optional overrides."""
    return Patch(
        patch_id=patch_id,
        stage="FLOORPLAN",
        config_vars=config_vars or {},
        sdc_edits=sdc_edits or [],
        tcl_edits=tcl_edits or [],
    )


@dataclass
class _MockGuardResult:
    passed: bool
    rejection: PatchRejected | None = None


class _MockGuardAccept:
    """ConstraintGuard mock that always accepts."""

    def validate(self, patch: Patch) -> _MockGuardResult:
        return _MockGuardResult(passed=True)


class _MockGuardReject:
    """ConstraintGuard mock that always rejects."""

    def __init__(self, reason: str = "locked_constraint_backdoor") -> None:
        self._reason = reason

    def validate(self, patch: Patch) -> _MockGuardResult:
        rejection = PatchRejected(
            patch_id=patch.patch_id,
            stage=patch.stage,
            reason_code=self._reason,
            offending_channel="config_vars",
            remediation_hint="Do not modify locked variables.",
        )
        return _MockGuardResult(passed=False, rejection=rejection)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestStepOrder:
    """Verify that steps execute in the correct 1-8 order."""

    def test_step_order_enforced(self, tmp_path: Path) -> None:
        """Steps execute in exact 1-8 order."""
        materializer = PatchMaterializer()
        patch = _make_patch(config_vars={"FP_CORE_UTIL": 45})

        ctx = materializer.materialize(
            patch=patch,
            attempt_dir=tmp_path / "attempt_001",
            stage_name="FLOORPLAN",
        )

        expected_order = [
            "schema_validation",
            "knob_validation",
            "constraint_guard_skipped",  # no guard configured
            "macro_resolution_skipped",  # no macro_placements
            "grid_snap_skipped",  # no resolved macros
            "sdc_materialize",
            "tcl_materialize",
            "config_overrides",
        ]
        assert ctx.steps_completed == expected_order


class TestEarlyRejection:
    """Verify that steps 1-3 can reject without side effects."""

    def test_schema_validation_first(self, tmp_path: Path) -> None:
        """Invalid schema rejected at step 1."""
        materializer = PatchMaterializer()
        patch = _make_patch(patch_id="")  # empty patch_id

        with pytest.raises(EarlyRejectionError) as exc_info:
            materializer.materialize(
                patch=patch,
                attempt_dir=tmp_path / "attempt_001",
                stage_name="FLOORPLAN",
            )

        assert exc_info.value.rejection.reason_code == "invalid_schema"

    def test_knob_range_validation_second(self, tmp_path: Path) -> None:
        """Out-of-range knob rejected at step 2."""
        materializer = PatchMaterializer()
        # FP_CORE_UTIL range is 20-80; 99 is out of range
        patch = _make_patch(config_vars={"FP_CORE_UTIL": 99})

        with pytest.raises(EarlyRejectionError) as exc_info:
            materializer.materialize(
                patch=patch,
                attempt_dir=tmp_path / "attempt_001",
                stage_name="FLOORPLAN",
            )

        assert exc_info.value.rejection.reason_code == "knob_out_of_range"
        assert "FP_CORE_UTIL" in exc_info.value.rejection.offending_commands

    def test_constraint_guard_third(self, tmp_path: Path) -> None:
        """Locked var rejected at step 3."""
        guard = _MockGuardReject(reason="locked_constraint_backdoor")
        materializer = PatchMaterializer(constraint_guard=guard)
        patch = _make_patch(config_vars={"FP_CORE_UTIL": 45})

        with pytest.raises(EarlyRejectionError) as exc_info:
            materializer.materialize(
                patch=patch,
                attempt_dir=tmp_path / "attempt_001",
                stage_name="FLOORPLAN",
            )

        assert (
            exc_info.value.rejection.reason_code
            == "locked_constraint_backdoor"
        )

    def test_early_rejection_no_side_effects(self, tmp_path: Path) -> None:
        """Steps 1-3 rejection means no fragment files written."""
        materializer = PatchMaterializer()
        # Bad knob value triggers step 2 rejection
        sdc_edit = SDCEdit(
            name="test.sdc",
            lines=["set_false_path -from [get_ports clk]"],
        )
        patch = _make_patch(
            config_vars={"FP_CORE_UTIL": 99},  # out of range
            sdc_edits=[sdc_edit],
        )

        attempt_dir = tmp_path / "attempt_001"

        with pytest.raises(EarlyRejectionError):
            materializer.materialize(
                patch=patch,
                attempt_dir=attempt_dir,
                stage_name="FLOORPLAN",
            )

        # No constraints directory should have been created
        assert not (attempt_dir / "constraints").exists()


class TestMaterialization:
    """Verify that steps 6-8 produce correct output files and config."""

    def test_sdc_materialization_sixth(self, tmp_path: Path) -> None:
        """SDC edits written to fragment files."""
        materializer = PatchMaterializer()
        sdc_edit = SDCEdit(
            name="agent_floorplan.sdc",
            lines=[
                "set_false_path -from [get_ports clk]",
                "set_max_delay 5.0 -from [get_ports din]",
            ],
        )
        patch = _make_patch(sdc_edits=[sdc_edit])

        attempt_dir = tmp_path / "attempt_001"
        ctx = materializer.materialize(
            patch=patch,
            attempt_dir=attempt_dir,
            stage_name="FLOORPLAN",
        )

        assert len(ctx.sdc_fragment_paths) == 1
        assert ctx.sdc_fragment_paths[0].name == "agent_floorplan.sdc"
        assert ctx.sdc_fragment_paths[0].exists()

    def test_tcl_materialization_seventh(self, tmp_path: Path) -> None:
        """Tcl edits written to hook files."""
        materializer = PatchMaterializer()
        tcl_edit = TclEdit(
            name="post_gp_fix.tcl",
            tool="openroad",
            hook={"type": "post_step", "step_id": "OpenROAD.GlobalPlacement"},
            lines=["set_global_routing_layer_adjustment metal1 0.5"],
        )
        patch = _make_patch(tcl_edits=[tcl_edit])

        attempt_dir = tmp_path / "attempt_001"
        ctx = materializer.materialize(
            patch=patch,
            attempt_dir=attempt_dir,
            stage_name="PLACE_GLOBAL",
        )

        assert len(ctx.tcl_hook_paths) == 1
        assert ctx.tcl_hook_paths[0].name == "post_gp_fix.tcl"
        assert ctx.tcl_hook_paths[0].exists()

    def test_config_overrides_eighth(self, tmp_path: Path) -> None:
        """Knob overrides applied."""
        materializer = PatchMaterializer()
        patch = _make_patch(
            config_vars={
                "FP_CORE_UTIL": 45,
                "FP_ASPECT_RATIO": 1.2,
            },
        )

        ctx = materializer.materialize(
            patch=patch,
            attempt_dir=tmp_path / "attempt_001",
            stage_name="FLOORPLAN",
        )

        assert ctx.resolved_config_vars == {
            "FP_CORE_UTIL": 45,
            "FP_ASPECT_RATIO": 1.2,
        }

    def test_sdc_fragment_file_content(self, tmp_path: Path) -> None:
        """Written SDC file has correct content."""
        materializer = PatchMaterializer()
        sdc_lines = [
            "set_false_path -from [get_ports clk]",
            "set_max_delay 5.0 -from [get_ports din]",
        ]
        sdc_edit = SDCEdit(
            name="agent_timing.sdc",
            lines=sdc_lines,
        )
        patch = _make_patch(sdc_edits=[sdc_edit])

        attempt_dir = tmp_path / "attempt_001"
        ctx = materializer.materialize(
            patch=patch,
            attempt_dir=attempt_dir,
            stage_name="FLOORPLAN",
        )

        content = ctx.sdc_fragment_paths[0].read_text()
        expected = "\n".join(sdc_lines) + "\n"
        assert content == expected


class TestFullPipeline:
    """End-to-end tests for the full 8-step pipeline."""

    def test_full_pipeline_success(self, tmp_path: Path) -> None:
        """All 8 steps complete, context has all paths."""
        guard = _MockGuardAccept()
        materializer = PatchMaterializer(constraint_guard=guard)

        sdc_edit = SDCEdit(
            name="timing.sdc",
            lines=["set_false_path -from [get_ports reset]"],
        )
        tcl_edit = TclEdit(
            name="post_route.tcl",
            tool="openroad",
            hook={"type": "post_step", "step_id": "OpenROAD.DetailedRouting"},
            lines=["puts \"Post-routing hook\""],
        )
        patch = _make_patch(
            config_vars={"FP_CORE_UTIL": 50},
            sdc_edits=[sdc_edit],
            tcl_edits=[tcl_edit],
        )

        attempt_dir = tmp_path / "attempt_001"
        ctx = materializer.materialize(
            patch=patch,
            attempt_dir=attempt_dir,
            stage_name="FLOORPLAN",
        )

        # All 8 steps completed
        assert len(ctx.steps_completed) == 8
        assert "constraint_guard" in ctx.steps_completed  # not skipped

        # SDC fragment written
        assert len(ctx.sdc_fragment_paths) == 1
        assert ctx.sdc_fragment_paths[0].exists()

        # Tcl hook written
        assert len(ctx.tcl_hook_paths) == 1
        assert ctx.tcl_hook_paths[0].exists()

        # Config overrides applied
        assert ctx.resolved_config_vars == {"FP_CORE_UTIL": 50}

    def test_no_constraint_guard(self, tmp_path: Path) -> None:
        """When guard is None, step 3 is skipped."""
        materializer = PatchMaterializer()  # no guard
        patch = _make_patch()

        ctx = materializer.materialize(
            patch=patch,
            attempt_dir=tmp_path / "attempt_001",
            stage_name="FLOORPLAN",
        )

        assert "constraint_guard_skipped" in ctx.steps_completed
        assert "constraint_guard" not in ctx.steps_completed

    def test_empty_patch_passes(self, tmp_path: Path) -> None:
        """Patch with no edits passes all steps."""
        materializer = PatchMaterializer()
        patch = _make_patch(
            config_vars={},
            sdc_edits=[],
            tcl_edits=[],
        )

        ctx = materializer.materialize(
            patch=patch,
            attempt_dir=tmp_path / "attempt_001",
            stage_name="FLOORPLAN",
        )

        assert len(ctx.steps_completed) == 8
        assert ctx.sdc_fragment_paths == []
        assert ctx.tcl_hook_paths == []
        assert ctx.resolved_config_vars == {}

    def test_unknown_knob_passes_through(self, tmp_path: Path) -> None:
        """Unknown knobs (not in registry) pass validation."""
        materializer = PatchMaterializer()
        patch = _make_patch(
            config_vars={"CUSTOM_TOOL_KNOB": "some_value"},
        )

        # Should not raise
        ctx = materializer.materialize(
            patch=patch,
            attempt_dir=tmp_path / "attempt_001",
            stage_name="FLOORPLAN",
        )

        assert "knob_validation" in ctx.steps_completed
        assert ctx.resolved_config_vars == {
            "CUSTOM_TOOL_KNOB": "some_value",
        }

    def test_knob_wrong_type_rejected(self, tmp_path: Path) -> None:
        """Knob with wrong type rejected at step 2."""
        materializer = PatchMaterializer()
        # FP_CORE_UTIL expects int, not str
        patch = _make_patch(config_vars={"FP_CORE_UTIL": "forty-five"})

        with pytest.raises(EarlyRejectionError) as exc_info:
            materializer.materialize(
                patch=patch,
                attempt_dir=tmp_path / "attempt_001",
                stage_name="FLOORPLAN",
            )

        assert exc_info.value.rejection.reason_code == "knob_out_of_range"

    def test_multiple_sdc_fragments(self, tmp_path: Path) -> None:
        """Multiple SDC edits produce multiple fragment files."""
        materializer = PatchMaterializer()
        sdc_edits = [
            SDCEdit(name="timing.sdc", lines=["set_max_delay 5.0"]),
            SDCEdit(name="exceptions.sdc", lines=["set_false_path"]),
        ]
        patch = _make_patch(sdc_edits=sdc_edits)

        attempt_dir = tmp_path / "attempt_001"
        ctx = materializer.materialize(
            patch=patch,
            attempt_dir=attempt_dir,
            stage_name="FLOORPLAN",
        )

        assert len(ctx.sdc_fragment_paths) == 2
        names = {p.name for p in ctx.sdc_fragment_paths}
        assert names == {"timing.sdc", "exceptions.sdc"}
