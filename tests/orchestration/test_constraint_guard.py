"""Tests for ConstraintGuard validator (P2.1).

Covers:
- test_valid_patch_passes
- test_locked_var_rejected
- test_locked_var_reason_code
- test_remediation_hint_present
- test_guard_disabled_passes_everything
- test_deny_commands_derived_from_locked_aspects
- test_multiple_locked_vars
- test_empty_patch_passes
- test_config_vars_with_allowed_knob
"""

from __future__ import annotations

from agenticlane.config.models import (
    ActionSpaceConfig,
    ConstraintsConfig,
    GuardConfig,
    PermissionsConfig,
    TclConfig,
)
from agenticlane.orchestration.constraint_guard import (
    ASPECT_DENY_MAP,
    ConstraintGuard,
)
from agenticlane.schemas.patch import Patch, SDCEdit, TclEdit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_patch(
    config_vars: dict | None = None,
    stage: str = "FLOORPLAN",
    sdc_edits: list[SDCEdit] | None = None,
    tcl_edits: list[TclEdit] | None = None,
) -> Patch:
    """Create a minimal Patch for testing."""
    types: list[str] = []
    if config_vars:
        types.append("config_vars")
    if sdc_edits:
        types.append("sdc_edits")
    if tcl_edits:
        types.append("tcl_edits")
    return Patch(
        patch_id="test-patch-001",
        stage=stage,
        types=types,
        config_vars=config_vars or {},
        sdc_edits=sdc_edits or [],
        tcl_edits=tcl_edits or [],
    )


def _make_guard(
    locked_vars: list[str] | None = None,
    locked_aspects: list[str] | None = None,
    guard_enabled: bool = True,
    tcl_enabled: bool = False,
) -> ConstraintGuard:
    """Create a ConstraintGuard with configurable locked_vars."""
    constraints = ConstraintsConfig(
        locked_vars=locked_vars if locked_vars is not None else ["CLOCK_PERIOD"],
        locked_aspects=locked_aspects
        if locked_aspects is not None
        else [
            "clock_period",
            "timing_exceptions",
            "max_min_delay",
            "clock_uncertainty",
        ],
        guard=GuardConfig(enabled=guard_enabled),
    )
    action_space = ActionSpaceConfig(
        tcl=TclConfig(enabled=tcl_enabled),
    )
    return ConstraintGuard(constraints, action_space)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestConstraintGuardValidator:
    """P2.1 ConstraintGuard validator tests."""

    def test_valid_patch_passes(self) -> None:
        """Patch with allowed knobs passes validation."""
        guard = _make_guard()
        patch = _make_patch(config_vars={"FP_CORE_UTIL": 50})
        result = guard.validate(patch)
        assert result.passed is True
        assert result.rejection is None

    def test_locked_var_rejected(self) -> None:
        """Patch modifying CLOCK_PERIOD is rejected when it is locked."""
        guard = _make_guard(locked_vars=["CLOCK_PERIOD"])
        patch = _make_patch(config_vars={"CLOCK_PERIOD": 5.0})
        result = guard.validate(patch)
        assert result.passed is False
        assert result.rejection is not None
        assert "CLOCK_PERIOD" in result.rejection.offending_commands

    def test_locked_var_reason_code(self) -> None:
        """Rejection has 'locked_constraint' reason_code."""
        guard = _make_guard(locked_vars=["CLOCK_PERIOD"])
        patch = _make_patch(config_vars={"CLOCK_PERIOD": 5.0})
        result = guard.validate(patch)
        assert result.rejection is not None
        assert result.rejection.reason_code == "locked_constraint"

    def test_remediation_hint_present(self) -> None:
        """Rejection includes a helpful remediation hint."""
        guard = _make_guard(locked_vars=["CLOCK_PERIOD"])
        patch = _make_patch(config_vars={"CLOCK_PERIOD": 5.0})
        result = guard.validate(patch)
        assert result.rejection is not None
        assert len(result.rejection.remediation_hint) > 0
        assert "CLOCK_PERIOD" in result.rejection.remediation_hint

    def test_guard_disabled_passes_everything(self) -> None:
        """When guard.enabled=False, everything passes -- even locked vars."""
        guard = _make_guard(locked_vars=["CLOCK_PERIOD"], guard_enabled=False)
        patch = _make_patch(config_vars={"CLOCK_PERIOD": 5.0})
        result = guard.validate(patch)
        assert result.passed is True
        assert result.rejection is None

    def test_deny_commands_derived_from_locked_aspects(self) -> None:
        """Locked clock_period aspect -> create_clock is in deny list."""
        guard = _make_guard(locked_aspects=["clock_period"])
        deny = guard.deny_commands
        assert "create_clock" in deny
        assert "remove_clock" in deny
        assert "create_generated_clock" in deny
        assert "set_propagated_clock" in deny

    def test_deny_commands_all_aspects(self) -> None:
        """All four default locked aspects produce the full deny list."""
        guard = _make_guard()
        deny = guard.deny_commands
        # Flatten all expected commands from ASPECT_DENY_MAP for the four default aspects
        expected = set()
        for aspect in ["clock_period", "timing_exceptions", "max_min_delay", "clock_uncertainty"]:
            expected.update(ASPECT_DENY_MAP[aspect])
        for cmd in expected:
            assert cmd in deny, f"{cmd} should be in deny list"

    def test_deny_commands_includes_read_sdc_when_tcl_enabled(self) -> None:
        """When Tcl is enabled and aspects are locked, read_sdc is denied."""
        guard = _make_guard(
            locked_aspects=["clock_period"],
            tcl_enabled=True,
        )
        deny = guard.deny_commands
        assert "read_sdc" in deny

    def test_deny_commands_excludes_read_sdc_when_tcl_disabled(self) -> None:
        """When Tcl is disabled, read_sdc is NOT in the deny list."""
        guard = _make_guard(
            locked_aspects=["clock_period"],
            tcl_enabled=False,
        )
        deny = guard.deny_commands
        assert "read_sdc" not in deny

    def test_multiple_locked_vars(self) -> None:
        """Two locked vars, both checked -- modifying either rejected."""
        guard = _make_guard(locked_vars=["CLOCK_PERIOD", "CLOCK_PORT"])

        # Modifying first locked var
        patch1 = _make_patch(config_vars={"CLOCK_PERIOD": 5.0})
        result1 = guard.validate(patch1)
        assert result1.passed is False
        assert result1.rejection is not None
        assert "CLOCK_PERIOD" in result1.rejection.offending_commands

        # Modifying second locked var
        patch2 = _make_patch(config_vars={"CLOCK_PORT": "new_clk"})
        result2 = guard.validate(patch2)
        assert result2.passed is False
        assert result2.rejection is not None
        assert "CLOCK_PORT" in result2.rejection.offending_commands

    def test_multiple_locked_vars_both_in_patch(self) -> None:
        """Patch modifying both locked vars lists both in offending_commands."""
        guard = _make_guard(locked_vars=["CLOCK_PERIOD", "CLOCK_PORT"])
        patch = _make_patch(config_vars={"CLOCK_PERIOD": 5.0, "CLOCK_PORT": "x"})
        result = guard.validate(patch)
        assert result.passed is False
        assert result.rejection is not None
        assert "CLOCK_PERIOD" in result.rejection.offending_commands
        assert "CLOCK_PORT" in result.rejection.offending_commands

    def test_empty_patch_passes(self) -> None:
        """Empty patch (no config_vars, no sdc, no tcl) always passes."""
        guard = _make_guard()
        patch = _make_patch(config_vars={})
        result = guard.validate(patch)
        assert result.passed is True
        assert result.rejection is None

    def test_config_vars_with_allowed_knob(self) -> None:
        """FP_CORE_UTIL is not locked -- modifying it passes."""
        guard = _make_guard(locked_vars=["CLOCK_PERIOD"])
        patch = _make_patch(config_vars={"FP_CORE_UTIL": 60})
        result = guard.validate(patch)
        assert result.passed is True

    def test_rejection_offending_channel_is_config_vars(self) -> None:
        """Rejection from config_vars sets offending_channel correctly."""
        guard = _make_guard()
        patch = _make_patch(config_vars={"CLOCK_PERIOD": 5.0})
        result = guard.validate(patch)
        assert result.rejection is not None
        assert result.rejection.offending_channel == "config_vars"

    def test_rejection_patch_id_matches(self) -> None:
        """Rejection records the original patch_id."""
        guard = _make_guard()
        patch = _make_patch(config_vars={"CLOCK_PERIOD": 5.0})
        result = guard.validate(patch)
        assert result.rejection is not None
        assert result.rejection.patch_id == "test-patch-001"

    def test_rejection_stage_matches(self) -> None:
        """Rejection records the original stage."""
        guard = _make_guard()
        patch = _make_patch(config_vars={"CLOCK_PERIOD": 5.0}, stage="PLACE_GLOBAL")
        result = guard.validate(patch)
        assert result.rejection is not None
        assert result.rejection.stage == "PLACE_GLOBAL"

    def test_no_locked_aspects_empty_deny_list(self) -> None:
        """When no aspects are locked, deny list is empty (excluding Tcl)."""
        guard = _make_guard(locked_aspects=[], tcl_enabled=False)
        assert guard.deny_commands == []

    def test_mixed_locked_and_unlocked_vars(self) -> None:
        """Patch with both a locked and an unlocked var is rejected."""
        guard = _make_guard(locked_vars=["CLOCK_PERIOD"])
        patch = _make_patch(config_vars={"FP_CORE_UTIL": 60, "CLOCK_PERIOD": 5.0})
        result = guard.validate(patch)
        assert result.passed is False
        assert "CLOCK_PERIOD" in result.rejection.offending_commands  # type: ignore[union-attr]
        # FP_CORE_UTIL is not in offending_commands
        assert "FP_CORE_UTIL" not in result.rejection.offending_commands  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# SDC/Tcl Scanner Integration Tests
# ---------------------------------------------------------------------------


def _make_guard_with_sdc_tcl(
    locked_aspects: list[str] | None = None,
    sdc_permitted: bool = True,
    tcl_permitted: bool = False,
    tcl_enabled: bool = False,
) -> ConstraintGuard:
    """Create a ConstraintGuard with SDC/Tcl scanning enabled."""
    constraints = ConstraintsConfig(
        locked_vars=["CLOCK_PERIOD"],
        locked_aspects=locked_aspects
        if locked_aspects is not None
        else ["clock_period", "timing_exceptions", "max_min_delay", "clock_uncertainty"],
        guard=GuardConfig(enabled=True),
    )
    action_space = ActionSpaceConfig(
        permissions=PermissionsConfig(
            sdc=sdc_permitted,
            tcl=tcl_permitted,
        ),
        tcl=TclConfig(enabled=tcl_enabled),
    )
    return ConstraintGuard(constraints, action_space)


class TestConstraintGuardSDCScanning:
    """SDC edit scanning through ConstraintGuard."""

    def test_valid_sdc_edit_passes(self) -> None:
        """SDC edit with allowed commands passes validation."""
        guard = _make_guard_with_sdc_tcl()
        patch = _make_patch(sdc_edits=[
            SDCEdit(
                name="agent_fp.sdc",
                lines=["set_input_delay -clock clk 1.0 [get_ports data_in]"],
            ),
        ])
        result = guard.validate(patch)
        assert result.passed is True

    def test_denied_command_rejected(self) -> None:
        """SDC edit with create_clock (locked) is rejected."""
        guard = _make_guard_with_sdc_tcl()
        patch = _make_patch(sdc_edits=[
            SDCEdit(
                name="agent_fp.sdc",
                lines=["create_clock -period 5 -name clk [get_ports clk]"],
            ),
        ])
        result = guard.validate(patch)
        assert result.passed is False
        assert result.rejection is not None
        assert result.rejection.offending_channel == "sdc_edits"
        assert result.rejection.reason_code == "sdc_constraint_violation"

    def test_forbidden_token_eval_rejected(self) -> None:
        """SDC edit with 'eval' token is rejected."""
        guard = _make_guard_with_sdc_tcl()
        patch = _make_patch(sdc_edits=[
            SDCEdit(
                name="agent_fp.sdc",
                lines=["eval create_clock -period 5"],
            ),
        ])
        result = guard.validate(patch)
        assert result.passed is False
        assert result.rejection is not None
        assert "forbidden" in result.rejection.reason_code.lower() or \
               "constraint" in result.rejection.reason_code.lower()

    def test_semicolon_rejected(self) -> None:
        """SDC edit with semicolons is rejected."""
        guard = _make_guard_with_sdc_tcl()
        patch = _make_patch(sdc_edits=[
            SDCEdit(
                name="agent_fp.sdc",
                lines=["set_input_delay 1.0 ; create_clock -period 5"],
            ),
        ])
        result = guard.validate(patch)
        assert result.passed is False

    def test_sdc_not_permitted_rejected(self) -> None:
        """SDC edit when permissions.sdc=False is rejected."""
        guard = _make_guard_with_sdc_tcl(sdc_permitted=False)
        patch = _make_patch(sdc_edits=[
            SDCEdit(
                name="agent_fp.sdc",
                lines=["set_input_delay 1.0 [get_ports data_in]"],
            ),
        ])
        result = guard.validate(patch)
        assert result.passed is False
        assert result.rejection is not None
        assert result.rejection.reason_code == "sdc_not_permitted"

    def test_empty_sdc_edit_passes(self) -> None:
        """SDC edit with empty lines passes."""
        guard = _make_guard_with_sdc_tcl()
        patch = _make_patch(sdc_edits=[
            SDCEdit(name="agent_fp.sdc", lines=[]),
        ])
        result = guard.validate(patch)
        assert result.passed is True

    def test_multiple_sdc_edits_second_fails(self) -> None:
        """Multiple SDC edits — second one has violation."""
        guard = _make_guard_with_sdc_tcl()
        patch = _make_patch(sdc_edits=[
            SDCEdit(
                name="agent_ok.sdc",
                lines=["set_input_delay 1.0 [get_ports clk]"],
            ),
            SDCEdit(
                name="agent_bad.sdc",
                lines=["create_clock -period 5 -name clk [get_ports clk]"],
            ),
        ])
        result = guard.validate(patch)
        assert result.passed is False
        assert "agent_bad.sdc" in result.rejection.remediation_hint  # type: ignore[union-attr]

    def test_sdc_no_locked_aspects_allows_create_clock(self) -> None:
        """When no aspects are locked, create_clock is allowed."""
        guard = _make_guard_with_sdc_tcl(locked_aspects=[])
        patch = _make_patch(sdc_edits=[
            SDCEdit(
                name="agent_fp.sdc",
                lines=["create_clock -period 10 -name clk [get_ports clk]"],
            ),
        ])
        result = guard.validate(patch)
        assert result.passed is True

    def test_sdc_inline_comment_rejected(self) -> None:
        """Inline comments in SDC are rejected."""
        guard = _make_guard_with_sdc_tcl()
        patch = _make_patch(sdc_edits=[
            SDCEdit(
                name="agent_fp.sdc",
                lines=["set_input_delay 1.0 [get_ports data_in] # comment here"],
            ),
        ])
        result = guard.validate(patch)
        assert result.passed is False

    def test_sdc_line_continuation_joined(self) -> None:
        """SDC lines with backslash continuation are properly joined."""
        guard = _make_guard_with_sdc_tcl()
        # This is a valid command split across lines
        patch = _make_patch(sdc_edits=[
            SDCEdit(
                name="agent_fp.sdc",
                lines=[
                    "set_input_delay \\",
                    "  1.0 [get_ports data_in]",
                ],
            ),
        ])
        result = guard.validate(patch)
        assert result.passed is True


class TestConstraintGuardTclScanning:
    """Tcl edit scanning through ConstraintGuard."""

    def test_tcl_not_permitted_rejected(self) -> None:
        """Tcl edit when permissions.tcl=False is rejected."""
        guard = _make_guard_with_sdc_tcl(tcl_permitted=False)
        patch = _make_patch(tcl_edits=[
            TclEdit(
                name="post_gp.tcl",
                lines=["set_placement_padding -global -left 2 -right 2"],
            ),
        ])
        result = guard.validate(patch)
        assert result.passed is False
        assert result.rejection is not None
        assert result.rejection.reason_code == "tcl_not_permitted"

    def test_valid_tcl_edit_passes(self) -> None:
        """Valid Tcl edit with permitted actions passes."""
        guard = _make_guard_with_sdc_tcl(tcl_permitted=True, tcl_enabled=True)
        patch = _make_patch(tcl_edits=[
            TclEdit(
                name="post_gp.tcl",
                lines=["set_placement_padding -global -left 2 -right 2"],
            ),
        ])
        result = guard.validate(patch)
        assert result.passed is True

    def test_tcl_read_sdc_rejected(self) -> None:
        """read_sdc command in Tcl is rejected when constraints locked."""
        guard = _make_guard_with_sdc_tcl(tcl_permitted=True, tcl_enabled=True)
        patch = _make_patch(tcl_edits=[
            TclEdit(
                name="post_gp.tcl",
                lines=["read_sdc constraints.sdc"],
            ),
        ])
        result = guard.validate(patch)
        assert result.passed is False
        assert result.rejection is not None
        assert result.rejection.offending_channel == "tcl_edits"

    def test_tcl_exec_rejected(self) -> None:
        """exec command in Tcl is rejected (forbidden token)."""
        guard = _make_guard_with_sdc_tcl(tcl_permitted=True, tcl_enabled=True)
        patch = _make_patch(tcl_edits=[
            TclEdit(
                name="post_gp.tcl",
                lines=["exec rm -rf /tmp/something"],
            ),
        ])
        result = guard.validate(patch)
        assert result.passed is False

    def test_tcl_source_rejected(self) -> None:
        """source command in Tcl is rejected (forbidden token)."""
        guard = _make_guard_with_sdc_tcl(tcl_permitted=True, tcl_enabled=True)
        patch = _make_patch(tcl_edits=[
            TclEdit(
                name="post_gp.tcl",
                lines=["source external.tcl"],
            ),
        ])
        result = guard.validate(patch)
        assert result.passed is False

    def test_empty_tcl_edit_passes(self) -> None:
        """Tcl edit with empty lines passes."""
        guard = _make_guard_with_sdc_tcl(tcl_permitted=True, tcl_enabled=True)
        patch = _make_patch(tcl_edits=[
            TclEdit(name="post_gp.tcl", lines=[]),
        ])
        result = guard.validate(patch)
        assert result.passed is True

    def test_tcl_read_sdc_allowed_when_unlocked(self) -> None:
        """read_sdc is allowed when no aspects are locked."""
        guard = _make_guard_with_sdc_tcl(
            locked_aspects=[], tcl_permitted=True, tcl_enabled=True
        )
        patch = _make_patch(tcl_edits=[
            TclEdit(
                name="post_gp.tcl",
                lines=["read_sdc constraints.sdc"],
            ),
        ])
        result = guard.validate(patch)
        assert result.passed is True
