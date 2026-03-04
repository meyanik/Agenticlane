"""SDC restricted-dialect scanner for ConstraintGuard.

Validates SDC content against a configurable deny-list, bracket expression
allowlist, and forbidden token set.  Every public method is deterministic
and will never raise on any input -- violations are returned as data.
"""

from __future__ import annotations

import re

from agenticlane.config.models import SDCGuardConfig
from agenticlane.orchestration.scan_types import ScanResult, ScanViolation


class SDCScanner:
    """Scans SDC content for constraint-violating commands.

    The scanner enforces the restricted SDC dialect defined in the
    AgenticLane spec:

    * Deny-listed commands (derived from locked aspects)
    * Forbidden tokens (``eval``, ``source``, ``exec``, ...)
    * Semicolon rejection
    * Inline comment rejection
    * Bracket expression safety (allowlisted commands only, no nesting,
      no ``$`` or dangerous tokens inside brackets)
    """

    # Regex for non-nested bracket expressions: matches [...] where
    # the content does not contain [ or ].
    _BRACKET_RE = re.compile(r"\[([^\[\]]*)\]")

    # Regex to detect nested brackets: a [ inside bracket content.
    _NESTED_BRACKET_RE = re.compile(r"\[[^\]]*\[")

    def __init__(self, config: SDCGuardConfig, deny_commands: list[str]) -> None:
        """Initialise the scanner.

        Args:
            config: SDC guard configuration.
            deny_commands: Combined deny list (from config + derived from
                locked_aspects via Appendix B mapping).
        """
        self._config = config
        self._deny_commands: set[str] = set(deny_commands) | set(config.deny_commands)
        self._allow_bracket_cmds: set[str] = set(config.allow_bracket_cmds)
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
        self._reject_inline_comments: bool = config.reject_inline_comments

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

        # Strip trailing whitespace / newline for cleaner matching but
        # preserve leading whitespace for the first-token extraction.
        stripped = line.strip()

        # Skip empty lines.
        if not stripped:
            return violations

        # Skip full comment lines (first non-space char is #).
        if self._ignore_comment_lines and stripped.startswith("#"):
            return violations

        # --- Inline comment check ---
        if self._reject_inline_comments:
            # Reject if there is a '#' that is NOT at position 0 of the
            # stripped line.  We already skipped pure comment lines above.
            hash_idx = stripped.find("#")
            if hash_idx > 0:
                violations.append(
                    ScanViolation(
                        line_number=line_num,
                        line_text=line,
                        violation_type="inline_comment",
                        detail=f"Inline comment detected at position {hash_idx}",
                    )
                )

        # --- Semicolon check ---
        if self._reject_semicolons and ";" in stripped:
            violations.append(
                ScanViolation(
                    line_number=line_num,
                    line_text=line,
                    violation_type="semicolon",
                    detail="Semicolons are not allowed in SDC content",
                )
            )

        # --- Command token extraction ---
        tokens = stripped.split()
        if tokens:
            cmd_token = tokens[0]
            # Deny-listed command check.
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
        # Uses word-boundary regex so that e.g. "puts" matches the
        # standalone command but not as a substring of "all_inputs".
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

        # --- Bracket expression checks ---
        violations.extend(self._check_brackets(line_num, line))

        return violations

    def _check_brackets(self, line_num: int, line: str) -> list[ScanViolation]:
        """Check bracket expressions ``[cmd args...]`` for safety.

        Rules (restricted mode):
        1. Find all ``[...]`` with no nesting.
        2. For each bracket content:
           - Extract first token; must be in ``allow_bracket_cmds``.
           - Reject if content contains any deny-command token.
           - Reject if content contains ``;``, ``eval``, ``source``,
             ``exec``, or ``$``.
        3. If nested brackets are detected, reject.
        """
        violations: list[ScanViolation] = []

        # --- Nested bracket detection ---
        if self._NESTED_BRACKET_RE.search(line):
            violations.append(
                ScanViolation(
                    line_number=line_num,
                    line_text=line,
                    violation_type="nested_bracket",
                    detail="Nested bracket expressions are not allowed",
                )
            )

        # --- Non-nested bracket content checks ---
        for match in self._BRACKET_RE.finditer(line):
            content = match.group(1).strip()
            if not content:
                continue

            inner_tokens = content.split()
            bracket_cmd = inner_tokens[0] if inner_tokens else ""

            # Allowlist check for bracket command.
            if bracket_cmd and bracket_cmd not in self._allow_bracket_cmds:
                violations.append(
                    ScanViolation(
                        line_number=line_num,
                        line_text=line,
                        violation_type="forbidden_bracket_cmd",
                        detail=(
                            f"Bracket command '{bracket_cmd}' is not in the "
                            f"allowed set"
                        ),
                    )
                )

            # Deny-command inside bracket content.
            for dc in self._deny_commands:
                if dc in inner_tokens:
                    violations.append(
                        ScanViolation(
                            line_number=line_num,
                            line_text=line,
                            violation_type="dangerous_bracket_content",
                            detail=(
                                f"Denied command '{dc}' found inside bracket "
                                f"expression"
                            ),
                        )
                    )

            # Dangerous characters / tokens inside bracket content.
            # For single-char tokens (`;`, `$`) use simple containment;
            # for word tokens use word-boundary regex to avoid false
            # positives on compound identifiers.
            dangerous_chars = [";", "$"]
            dangerous_words = ["eval", "source", "exec"]
            for d in dangerous_chars:
                if d in content:
                    violations.append(
                        ScanViolation(
                            line_number=line_num,
                            line_text=line,
                            violation_type="dangerous_bracket_content",
                            detail=(
                                f"Dangerous token '{d}' found inside bracket "
                                f"expression"
                            ),
                        )
                    )
            for dw in dangerous_words:
                pat = re.compile(r"(?<!\w)" + re.escape(dw) + r"(?!\w)")
                if pat.search(content):
                    violations.append(
                        ScanViolation(
                            line_number=line_num,
                            line_text=line,
                            violation_type="dangerous_bracket_content",
                            detail=(
                                f"Dangerous token '{dw}' found inside bracket "
                                f"expression"
                            ),
                        )
                    )

        return violations
