"""Tests for the SDC restricted-dialect scanner (P2.3)."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from agenticlane.config.models import SDCGuardConfig
from agenticlane.orchestration.scan_types import ScanResult
from agenticlane.orchestration.sdc_scanner import SDCScanner

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def default_config() -> SDCGuardConfig:
    """Default SDC guard config with standard settings."""
    return SDCGuardConfig()


@pytest.fixture
def timing_locked_deny() -> list[str]:
    """Deny list derived from locked timing aspects."""
    return [
        "create_clock",
        "create_generated_clock",
        "set_clock_uncertainty",
        "set_clock_latency",
    ]


@pytest.fixture
def scanner(default_config: SDCGuardConfig, timing_locked_deny: list[str]) -> SDCScanner:
    """Scanner with default config and timing-locked deny list."""
    return SDCScanner(config=default_config, deny_commands=timing_locked_deny)


@pytest.fixture
def permissive_scanner() -> SDCScanner:
    """Scanner with no deny commands and no forbidden tokens."""
    config = SDCGuardConfig(
        deny_commands=[],
        forbid_tokens=[],
        reject_semicolons=False,
        reject_inline_comments=False,
    )
    return SDCScanner(config=config, deny_commands=[])


# ---------------------------------------------------------------------------
# Test: allowed SDC command passes
# ---------------------------------------------------------------------------


def test_allowed_sdc_command_passes(scanner: SDCScanner) -> None:
    """An allowed SDC command with valid bracket expressions passes."""
    lines = ["set_input_delay 1.0 -clock clk [get_ports in0]"]
    result = scanner.scan(lines)
    assert result.passed is True
    assert result.violations == []


# ---------------------------------------------------------------------------
# Test: denied command rejected
# ---------------------------------------------------------------------------


def test_denied_command_rejected(scanner: SDCScanner) -> None:
    """A denied command (create_clock) is rejected when timing is locked."""
    lines = ["create_clock -period 5 [get_ports clk]"]
    result = scanner.scan(lines)
    assert result.passed is False
    denied = [v for v in result.violations if v.violation_type == "denied_command"]
    assert len(denied) >= 1
    assert "create_clock" in denied[0].detail


# ---------------------------------------------------------------------------
# Test: semicolon rejected
# ---------------------------------------------------------------------------


def test_semicolon_rejected(scanner: SDCScanner) -> None:
    """Lines containing semicolons are rejected."""
    lines = ["set_false_path ; create_clock"]
    result = scanner.scan(lines)
    assert result.passed is False
    semi = [v for v in result.violations if v.violation_type == "semicolon"]
    assert len(semi) >= 1


# ---------------------------------------------------------------------------
# Test: inline comment rejected
# ---------------------------------------------------------------------------


def test_inline_comment_rejected(scanner: SDCScanner) -> None:
    """Lines with inline comments (# not at start) are rejected."""
    lines = ["set_input_delay 1.0 # comment"]
    result = scanner.scan(lines)
    assert result.passed is False
    ic = [v for v in result.violations if v.violation_type == "inline_comment"]
    assert len(ic) >= 1


# ---------------------------------------------------------------------------
# Test: allowed brackets
# ---------------------------------------------------------------------------


def test_allowed_brackets(scanner: SDCScanner) -> None:
    """Bracket expressions with allowed commands pass."""
    lines = [
        "set_input_delay 1.0 [get_ports in0]",
        "set_output_delay 0.5 [get_pins out0]",
        "set_false_path -from [all_inputs] -to [all_outputs]",
    ]
    result = scanner.scan(lines)
    assert result.passed is True


# ---------------------------------------------------------------------------
# Test: nested brackets rejected
# ---------------------------------------------------------------------------


def test_nested_brackets_rejected(scanner: SDCScanner) -> None:
    """Nested bracket expressions are rejected in restricted mode."""
    lines = ["set_input_delay 1.0 [get_ports [get_nets x]]"]
    result = scanner.scan(lines)
    assert result.passed is False
    nested = [v for v in result.violations if v.violation_type == "nested_bracket"]
    assert len(nested) >= 1


# ---------------------------------------------------------------------------
# Test: forbidden token eval
# ---------------------------------------------------------------------------


def test_forbidden_token_eval(scanner: SDCScanner) -> None:
    """The forbidden token 'eval' is rejected."""
    lines = ["eval create_clock -period 5"]
    result = scanner.scan(lines)
    assert result.passed is False
    ft = [v for v in result.violations if v.violation_type == "forbidden_token"]
    assert any("eval" in v.detail for v in ft)


# ---------------------------------------------------------------------------
# Test: forbidden token source
# ---------------------------------------------------------------------------


def test_forbidden_token_source(scanner: SDCScanner) -> None:
    """The forbidden token 'source' is rejected."""
    lines = ["source malicious.sdc"]
    result = scanner.scan(lines)
    assert result.passed is False
    ft = [v for v in result.violations if v.violation_type == "forbidden_token"]
    assert any("source" in v.detail for v in ft)


# ---------------------------------------------------------------------------
# Test: forbidden token exec
# ---------------------------------------------------------------------------


def test_forbidden_token_exec(scanner: SDCScanner) -> None:
    """The forbidden token 'exec' is rejected."""
    lines = ["exec rm -rf /"]
    result = scanner.scan(lines)
    assert result.passed is False
    ft = [v for v in result.violations if v.violation_type == "forbidden_token"]
    assert any("exec" in v.detail for v in ft)


# ---------------------------------------------------------------------------
# Test: empty line skipped
# ---------------------------------------------------------------------------


def test_empty_line_skipped(scanner: SDCScanner) -> None:
    """Empty and whitespace-only lines are skipped without violations."""
    lines = ["", "   ", "\t"]
    result = scanner.scan(lines)
    assert result.passed is True
    assert result.violations == []


# ---------------------------------------------------------------------------
# Test: comment line skipped
# ---------------------------------------------------------------------------


def test_comment_line_skipped(scanner: SDCScanner) -> None:
    """Full comment lines (starting with #) are skipped."""
    lines = ["# This is a comment", "  # Indented comment"]
    result = scanner.scan(lines)
    assert result.passed is True
    assert result.violations == []


# ---------------------------------------------------------------------------
# Test: forbidden token inside bracket content
# ---------------------------------------------------------------------------


def test_forbidden_in_bracket_content(scanner: SDCScanner) -> None:
    """Forbidden commands inside bracket expressions are rejected."""
    lines = ["set_input_delay 1.0 [exec rm]"]
    result = scanner.scan(lines)
    assert result.passed is False
    # Should be caught both as a forbidden bracket cmd and as dangerous content
    violations = result.violations
    assert len(violations) >= 1
    types = {v.violation_type for v in violations}
    assert "forbidden_bracket_cmd" in types or "dangerous_bracket_content" in types


# ---------------------------------------------------------------------------
# Test: dollar sign in bracket rejected
# ---------------------------------------------------------------------------


def test_dollar_in_bracket_rejected(scanner: SDCScanner) -> None:
    """Dollar signs ($) inside bracket expressions are rejected in restricted mode."""
    lines = ["set_input_delay 1.0 [get_ports $var]"]
    result = scanner.scan(lines)
    assert result.passed is False
    dangerous = [v for v in result.violations if v.violation_type == "dangerous_bracket_content"]
    assert any("$" in v.detail for v in dangerous)


# ---------------------------------------------------------------------------
# Test: empty deny commands passes everything
# ---------------------------------------------------------------------------


def test_deny_commands_empty_passes_everything(permissive_scanner: SDCScanner) -> None:
    """With empty deny list and no forbidden tokens, all commands pass."""
    lines = [
        "create_clock -period 5 [get_ports clk]",
        "set_input_delay 1.0 [get_ports in0]",
    ]
    result = permissive_scanner.scan(lines)
    assert result.passed is True


# ---------------------------------------------------------------------------
# Test: multiple violations all reported
# ---------------------------------------------------------------------------


def test_multiple_violations_all_reported(scanner: SDCScanner) -> None:
    """Multiple violations on different lines are all captured."""
    lines = [
        "create_clock -period 5 [get_ports clk]",  # denied command
        "set_false_path ; set_input_delay 1.0",  # semicolon
        "eval source malicious.sdc",  # forbidden tokens
    ]
    result = scanner.scan(lines)
    assert result.passed is False
    # We expect violations from all three lines
    line_numbers = {v.line_number for v in result.violations}
    assert 1 in line_numbers
    assert 2 in line_numbers
    assert 3 in line_numbers


# ---------------------------------------------------------------------------
# Test: property -- random SDC never crashes
# ---------------------------------------------------------------------------


@given(st.text())
@settings(max_examples=200)
def test_property_random_sdc_no_crash(text: str) -> None:
    """Hypothesis: no input crashes the SDC scanner.

    The scanner must always return a valid ScanResult regardless of
    how adversarial or nonsensical the input is.
    """
    config = SDCGuardConfig()
    deny = ["create_clock"]
    scanner = SDCScanner(config=config, deny_commands=deny)
    lines = text.splitlines()
    result = scanner.scan(lines)
    assert isinstance(result, ScanResult)
    assert isinstance(result.passed, bool)
    assert isinstance(result.violations, list)


# ---------------------------------------------------------------------------
# Additional edge-case tests
# ---------------------------------------------------------------------------


def test_line_numbers_are_one_indexed(scanner: SDCScanner) -> None:
    """Violation line numbers are 1-indexed."""
    lines = [
        "set_input_delay 1.0 [get_ports in0]",  # line 1 -- OK
        "create_clock -period 5",  # line 2 -- denied
    ]
    result = scanner.scan(lines)
    assert result.passed is False
    assert result.violations[0].line_number == 2


def test_line_text_preserved_in_violation(scanner: SDCScanner) -> None:
    """The original line text is preserved in the violation."""
    original = "create_clock -period 5 [get_ports clk]"
    lines = [original]
    result = scanner.scan(lines)
    assert result.passed is False
    assert result.violations[0].line_text == original


def test_allowed_bracket_cmds_all_pass(scanner: SDCScanner) -> None:
    """All default allowed bracket commands pass."""
    for cmd in [
        "get_ports", "get_pins", "get_nets", "get_cells",
        "get_clocks", "all_inputs", "all_outputs", "all_clocks",
    ]:
        lines = [f"set_input_delay 1.0 [{cmd} foo]"]
        result = scanner.scan(lines)
        assert result.passed is True, f"Expected [{cmd} foo] to pass"


def test_forbidden_bracket_cmd_custom(default_config: SDCGuardConfig) -> None:
    """A bracket command not in the allowlist is rejected."""
    scanner = SDCScanner(config=default_config, deny_commands=[])
    lines = ["set_input_delay 1.0 [some_random_cmd foo]"]
    result = scanner.scan(lines)
    assert result.passed is False
    fbc = [v for v in result.violations if v.violation_type == "forbidden_bracket_cmd"]
    assert len(fbc) >= 1
    assert "some_random_cmd" in fbc[0].detail
