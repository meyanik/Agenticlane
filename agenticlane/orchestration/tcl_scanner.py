"""Tcl restricted-dialect scanner for ConstraintGuard.

Validates Tcl content against a configurable deny-list and forbidden
token set.  Key differences from the SDC scanner:

* ``read_sdc`` is always denied when constraints are locked (closes the
  "read_sdc loophole" described in the spec).
* No bracket-expression allowlisting -- Tcl brackets have different
  semantics than SDC brackets, so we do NOT apply the SDC bracket
  allowlist rules here.
* ``source`` and file-IO commands are denied in restricted mode.
"""

from __future__ import annotations

import re

from agenticlane.config.models import TclGuardConfig
from agenticlane.orchestration.scan_types import ScanResult, ScanViolation


class TclScanner:
    """Scans Tcl content for unsafe commands.

    In *restricted_freeform* mode the scanner rejects ``eval``,
    ``source``, ``exec``, ``open``, ``puts``, ``file``, ``glob`` as
    forbidden tokens (substring match, same as the SDC scanner).  It
    also rejects ``read_sdc`` whenever constraints are locked to
    prevent the agent from reimporting an unrestricted constraint file.
    """

    def __init__(
        self,
        config: TclGuardConfig,
        deny_commands: list[str],
        *,
        constraints_locked: bool = True,
    ) -> None:
        """Initialise the scanner.

        Args:
            config: Tcl guard configuration.
            deny_commands: Combined deny list (from config + derived
                from locked_aspects).
            constraints_locked: When ``True``, ``read_sdc`` is
                automatically added to the deny list.
        """
        self._config = config
        self._deny_commands: set[str] = set(deny_commands) | set(config.deny_commands)
        self._forbid_tokens: list[str] = list(config.forbid_tokens)
        # Pre-compile word-boundary regexes for forbidden tokens so that
        # e.g. "puts" matches the command ``puts`` but NOT a substring
        # inside ``all_inputs`` or ``all_outputs``.
        self._forbid_token_patterns: list[tuple[str, re.Pattern[str]]] = [
            (ft, re.compile(r"(?<!\w)" + re.escape(ft) + r"(?!\w)"))
            for ft in self._forbid_tokens
        ]
        self._reject_semicolons: bool = config.reject_semicolons
        self._ignore_comment_lines: bool = config.ignore_comment_lines

        # Close the read_sdc loophole when constraints are locked.
        if constraints_locked:
            self._deny_commands.add("read_sdc")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan(self, logical_lines: list[str]) -> ScanResult:
        """Scan pre-processed logical lines for violations.

        Args:
            logical_lines: Lines after line-continuation joining.

        Returns:
            A :class:`ScanResult` with ``passed=True`` if no violations
            were found, or ``passed=False`` with the full violation list.
        """
        violations: list[ScanViolation] = []
        for idx, raw_line in enumerate(logical_lines):
            line_num = idx + 1  # 1-indexed
            violations.extend(self._scan_line(line_num, raw_line))
        return ScanResult(passed=len(violations) == 0, violations=violations)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _scan_line(self, line_num: int, line: str) -> list[ScanViolation]:
        """Scan a single logical line and return any violations."""
        violations: list[ScanViolation] = []

        stripped = line.strip()

        # Skip empty lines.
        if not stripped:
            return violations

        # Skip full comment lines.
        if self._ignore_comment_lines and stripped.startswith("#"):
            return violations

        # --- Semicolon check ---
        if self._reject_semicolons and ";" in stripped:
            violations.append(
                ScanViolation(
                    line_number=line_num,
                    line_text=line,
                    violation_type="semicolon",
                    detail="Semicolons are not allowed in Tcl content",
                )
            )

        # --- Command token extraction ---
        tokens = stripped.split()
        if tokens:
            cmd_token = tokens[0]
            if cmd_token in self._deny_commands:
                violations.append(
                    ScanViolation(
                        line_number=line_num,
                        line_text=line,
                        violation_type="denied_command",
                        detail=f"Command '{cmd_token}' is denied",
                    )
                )

        # --- Forbidden token check (word-boundary match) ---
        for ft, pattern in self._forbid_token_patterns:
            if pattern.search(stripped):
                violations.append(
                    ScanViolation(
                        line_number=line_num,
                        line_text=line,
                        violation_type="forbidden_token",
                        detail=f"Forbidden token '{ft}' found",
                    )
                )

        return violations
