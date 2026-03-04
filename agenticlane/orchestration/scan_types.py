"""Shared types for SDC and Tcl scanners."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ScanViolation:
    """A single violation found by the scanner."""

    line_number: int  # 1-indexed
    line_text: str
    violation_type: str
    # Valid types: "denied_command", "forbidden_token", "semicolon",
    #   "inline_comment", "nested_bracket", "forbidden_bracket_cmd",
    #   "dangerous_bracket_content"
    detail: str


@dataclass
class ScanResult:
    """Result of scanning SDC/Tcl content."""

    passed: bool
    violations: list[ScanViolation] = field(default_factory=list)
