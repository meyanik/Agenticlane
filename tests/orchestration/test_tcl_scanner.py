"""Tests for the Tcl restricted-dialect scanner (P2.4)."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from agenticlane.config.models import TclGuardConfig
from agenticlane.orchestration.scan_types import ScanResult
from agenticlane.orchestration.tcl_scanner import TclScanner

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def default_config() -> TclGuardConfig:
    """Default Tcl guard config with standard settings."""
    return TclGuardConfig()


@pytest.fixture
def locked_scanner(default_config: TclGuardConfig) -> TclScanner:
    """Scanner with constraints locked (default)."""
    return TclScanner(config=default_config, deny_commands=[], constraints_locked=True)


@pytest.fixture
def unlocked_scanner(default_config: TclGuardConfig) -> TclScanner:
    """Scanner with constraints NOT locked."""
    return TclScanner(config=default_config, deny_commands=[], constraints_locked=False)


# ---------------------------------------------------------------------------
# Test: read_sdc rejected when constraints locked
# ---------------------------------------------------------------------------


def test_read_sdc_rejected(locked_scanner: TclScanner) -> None:
    """read_sdc is rejected when constraints are locked."""
    lines = ["read_sdc constraints.sdc"]
    result = locked_scanner.scan(lines)
    assert result.passed is False
    denied = [v for v in result.violations if v.violation_type == "denied_command"]
    assert len(denied) >= 1
    assert "read_sdc" in denied[0].detail


# ---------------------------------------------------------------------------
# Test: safe Tcl command passes
# ---------------------------------------------------------------------------


def test_safe_tcl_command_passes(default_config: TclGuardConfig) -> None:
    """A safe Tcl command ('set var 5') passes in restricted mode.

    Note: 'set' is not in the forbid_tokens list by default, so this
    should pass cleanly.
    """
    scanner = TclScanner(config=default_config, deny_commands=[], constraints_locked=True)
    lines = ["set var 5"]
    result = scanner.scan(lines)
    assert result.passed is True
    assert result.violations == []


# ---------------------------------------------------------------------------
# Test: file write rejected
# ---------------------------------------------------------------------------


def test_file_write_rejected(locked_scanner: TclScanner) -> None:
    """'open file.txt w' is rejected (forbidden token 'open')."""
    lines = ["open file.txt w"]
    result = locked_scanner.scan(lines)
    assert result.passed is False
    ft = [v for v in result.violations if v.violation_type == "forbidden_token"]
    assert any("open" in v.detail for v in ft)


# ---------------------------------------------------------------------------
# Test: exec rejected
# ---------------------------------------------------------------------------


def test_exec_rejected(locked_scanner: TclScanner) -> None:
    """'exec rm -rf /' is rejected."""
    lines = ["exec rm -rf /"]
    result = locked_scanner.scan(lines)
    assert result.passed is False
    ft = [v for v in result.violations if v.violation_type == "forbidden_token"]
    assert any("exec" in v.detail for v in ft)


# ---------------------------------------------------------------------------
# Test: source rejected
# ---------------------------------------------------------------------------


def test_source_rejected(locked_scanner: TclScanner) -> None:
    """'source external.tcl' is rejected."""
    lines = ["source external.tcl"]
    result = locked_scanner.scan(lines)
    assert result.passed is False
    ft = [v for v in result.violations if v.violation_type == "forbidden_token"]
    assert any("source" in v.detail for v in ft)


# ---------------------------------------------------------------------------
# Test: semicolon rejected
# ---------------------------------------------------------------------------


def test_semicolon_rejected(locked_scanner: TclScanner) -> None:
    """Lines with semicolons are rejected."""
    lines = ["set x 5 ; set y 10"]
    result = locked_scanner.scan(lines)
    assert result.passed is False
    semi = [v for v in result.violations if v.violation_type == "semicolon"]
    assert len(semi) >= 1


# ---------------------------------------------------------------------------
# Test: comment line skipped
# ---------------------------------------------------------------------------


def test_comment_line_skipped(locked_scanner: TclScanner) -> None:
    """Full comment lines are skipped."""
    lines = ["# This is a Tcl comment", "  # Indented comment"]
    result = locked_scanner.scan(lines)
    assert result.passed is True
    assert result.violations == []


# ---------------------------------------------------------------------------
# Test: empty lines pass
# ---------------------------------------------------------------------------


def test_empty_lines_pass(locked_scanner: TclScanner) -> None:
    """Empty and whitespace-only lines pass through."""
    lines = ["", "   ", "\t", "  \t  "]
    result = locked_scanner.scan(lines)
    assert result.passed is True
    assert result.violations == []


# ---------------------------------------------------------------------------
# Test: constraints_locked=False allows read_sdc
# ---------------------------------------------------------------------------


def test_constraints_not_locked_allows_read_sdc(unlocked_scanner: TclScanner) -> None:
    """read_sdc is allowed when constraints are NOT locked."""
    lines = ["read_sdc constraints.sdc"]
    result = unlocked_scanner.scan(lines)
    # read_sdc should not be denied, but 'file' is a forbidden token --
    # however 'read_sdc constraints.sdc' does NOT contain any default
    # forbidden tokens, so it should pass.
    assert result.passed is True
    assert result.violations == []


# ---------------------------------------------------------------------------
# Test: multiple forbidden tokens on same line
# ---------------------------------------------------------------------------


def test_multiple_forbidden_tokens_detected(locked_scanner: TclScanner) -> None:
    """Multiple forbidden tokens on the same line are all reported."""
    lines = ["eval exec source"]
    result = locked_scanner.scan(lines)
    assert result.passed is False
    ft = [v for v in result.violations if v.violation_type == "forbidden_token"]
    details = [v.detail for v in ft]
    assert any("eval" in d for d in details)
    assert any("exec" in d for d in details)
    assert any("source" in d for d in details)


# ---------------------------------------------------------------------------
# Test: line numbers are 1-indexed
# ---------------------------------------------------------------------------


def test_line_numbers_one_indexed(locked_scanner: TclScanner) -> None:
    """Violation line numbers are 1-indexed."""
    lines = [
        "set x 5",  # line 1 -- OK
        "exec rm /",  # line 2 -- violation
    ]
    result = locked_scanner.scan(lines)
    assert result.passed is False
    assert result.violations[0].line_number == 2


# ---------------------------------------------------------------------------
# Test: puts rejected
# ---------------------------------------------------------------------------


def test_puts_rejected(locked_scanner: TclScanner) -> None:
    """'puts' is a forbidden token and is rejected."""
    lines = ["puts stdout hello"]
    result = locked_scanner.scan(lines)
    assert result.passed is False
    ft = [v for v in result.violations if v.violation_type == "forbidden_token"]
    assert any("puts" in v.detail for v in ft)


# ---------------------------------------------------------------------------
# Test: glob rejected
# ---------------------------------------------------------------------------


def test_glob_rejected(locked_scanner: TclScanner) -> None:
    """'glob' is a forbidden token and is rejected."""
    lines = ["glob *.tcl"]
    result = locked_scanner.scan(lines)
    assert result.passed is False
    ft = [v for v in result.violations if v.violation_type == "forbidden_token"]
    assert any("glob" in v.detail for v in ft)


# ---------------------------------------------------------------------------
# Test: file rejected
# ---------------------------------------------------------------------------


def test_file_rejected(locked_scanner: TclScanner) -> None:
    """'file' is a forbidden token and is rejected."""
    lines = ["file exists /tmp/foo"]
    result = locked_scanner.scan(lines)
    assert result.passed is False
    ft = [v for v in result.violations if v.violation_type == "forbidden_token"]
    assert any("file" in v.detail for v in ft)


# ---------------------------------------------------------------------------
# Test: deny_commands from config are honoured
# ---------------------------------------------------------------------------


def test_deny_commands_from_config() -> None:
    """deny_commands in the TclGuardConfig are honoured."""
    config = TclGuardConfig(deny_commands=["custom_bad_cmd"])
    scanner = TclScanner(config=config, deny_commands=[], constraints_locked=False)
    lines = ["custom_bad_cmd arg1"]
    result = scanner.scan(lines)
    assert result.passed is False
    denied = [v for v in result.violations if v.violation_type == "denied_command"]
    assert len(denied) >= 1
    assert "custom_bad_cmd" in denied[0].detail


# ---------------------------------------------------------------------------
# Test: property -- random Tcl never crashes
# ---------------------------------------------------------------------------


@given(st.text())
@settings(max_examples=200)
def test_property_random_tcl_no_crash(text: str) -> None:
    """Hypothesis: no input crashes the Tcl scanner."""
    config = TclGuardConfig()
    scanner = TclScanner(config=config, deny_commands=[], constraints_locked=True)
    lines = text.splitlines()
    result = scanner.scan(lines)
    assert isinstance(result, ScanResult)
    assert isinstance(result.passed, bool)
    assert isinstance(result.violations, list)
