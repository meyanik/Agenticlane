"""ConstraintGuard -- validates patches against constraint rules.

Prevents LLM agents from "cheating" by relaxing design constraints
(clock period, timing exceptions, etc.) through config vars, SDC edits,
or Tcl edits.

Includes the line-continuation preprocessor that joins backslash-
continued lines before any scanning takes place (spec lines 893-903).
"""

from __future__ import annotations

from dataclasses import dataclass

from agenticlane.config.models import ActionSpaceConfig, ConstraintsConfig
from agenticlane.orchestration.sdc_scanner import SDCScanner
from agenticlane.orchestration.tcl_scanner import TclScanner
from agenticlane.schemas.patch import Patch, PatchRejected

# ---------------------------------------------------------------------------
# Appendix B: locked_aspects -> deny commands
# ---------------------------------------------------------------------------

ASPECT_DENY_MAP: dict[str, list[str]] = {
    "clock_period": [
        "create_clock",
        "remove_clock",
        "create_generated_clock",
        "set_propagated_clock",
    ],
    "timing_exceptions": [
        "set_false_path",
        "set_multicycle_path",
        "set_disable_timing",
        "set_clock_groups",
        "group_path",
        "set_case_analysis",
    ],
    "max_min_delay": [
        "set_max_delay",
        "set_min_delay",
    ],
    "clock_uncertainty": [
        "set_clock_uncertainty",
        "set_clock_latency",
        "set_clock_transition",
    ],
}

# When *any* constraints are locked and Tcl is enabled, these extra
# commands are implicitly denied to close the "loader loophole".
TCL_CONSTRAINT_DENY: list[str] = ["read_sdc"]

# ---------------------------------------------------------------------------
# Line-continuation preprocessor (P2.2)
# ---------------------------------------------------------------------------


@dataclass
class PreprocessResult:
    """Result of line continuation preprocessing."""

    logical_lines: list[str]
    join_counts: list[int]  # how many physical lines each logical line spans


class LineContinuationError(Exception):
    """Raised when line continuation preprocessing fails."""

    def __init__(self, message: str, line_number: int = 0) -> None:
        super().__init__(message)
        self.line_number = line_number


def preprocess_lines(
    raw_text: str,
    *,
    max_joined_lines: int = 32,
    reject_unterminated: bool = True,
) -> PreprocessResult:
    """Join backslash-continued lines into logical lines.

    Algorithm (deterministic):
    1. Normalize newlines to ``\\n``
    2. Split into physical lines
    3. Iterate, building *logical_lines*:
       - Take current line *L* (without trailing newline)
       - While ``L.rstrip()`` ends with ``\\``:
         - Remove the trailing backslash
         - Append a single space
         - Concatenate next physical line (after ``lstrip``)
         - Increment join counter; reject if it exceeds *max_joined_lines*
       - Push final *L* to ``logical_lines``
    """
    # Step 1: normalize newlines
    text = raw_text.replace("\r\n", "\n").replace("\r", "\n")

    # Step 2: split into physical lines
    physical_lines = text.split("\n")

    # Step 3: join continuations
    logical_lines: list[str] = []
    join_counts: list[int] = []
    i = 0

    while i < len(physical_lines):
        line = physical_lines[i]
        joins = 1  # counts physical lines consumed

        while line.rstrip().endswith("\\"):
            # Check if there is a next line to consume
            if i + joins >= len(physical_lines):
                # Backslash at EOF -- unterminated continuation
                if reject_unterminated:
                    raise LineContinuationError(
                        f"Unterminated line continuation at physical line {i + joins}"
                        " (backslash at end of input)",
                        line_number=i + joins,
                    )
                # If not rejecting, strip the trailing backslash and break
                stripped = line.rstrip()
                line = stripped[:-1].rstrip()
                break

            # Remove trailing backslash: rstrip whitespace, drop '\',
            # then rstrip again to remove whitespace before the backslash.
            stripped = line.rstrip()
            line = stripped[:-1].rstrip()
            # Append a single space then the next physical line (lstripped)
            line = line + " " + physical_lines[i + joins].lstrip()
            joins += 1

            if joins > max_joined_lines:
                raise LineContinuationError(
                    f"Line continuation exceeds max_joined_lines ({max_joined_lines}) "
                    f"starting at physical line {i + 1}",
                    line_number=i + 1,
                )

        logical_lines.append(line)
        join_counts.append(joins)
        i += joins

    return PreprocessResult(logical_lines=logical_lines, join_counts=join_counts)


# ---------------------------------------------------------------------------
# ConstraintGuard (P2.1)
# ---------------------------------------------------------------------------


@dataclass
class GuardResult:
    """Outcome of a ConstraintGuard validation."""

    passed: bool
    rejection: PatchRejected | None = None


class ConstraintGuard:
    """Validates patches against constraint rules.

    Scans three channels:
    1. **config_vars** -- checks locked_vars
    2. **sdc_edits** -- SDC restricted dialect scanner
    3. **tcl_edits** -- Tcl restricted dialect scanner

    Parameters
    ----------
    constraints_config:
        The ``constraints`` section of the resolved config.
    action_space:
        The ``action_space`` section of the resolved config.
    """

    def __init__(
        self,
        constraints_config: ConstraintsConfig,
        action_space: ActionSpaceConfig,
    ) -> None:
        self._constraints = constraints_config
        self._action_space = action_space
        self._deny_commands = self._derive_deny_commands()

        # Initialise the SDC and Tcl dialect scanners
        self._sdc_scanner = SDCScanner(
            config=constraints_config.guard.sdc,
            deny_commands=self._deny_commands,
        )
        constraints_locked = bool(constraints_config.locked_aspects)
        self._tcl_scanner = TclScanner(
            config=constraints_config.guard.tcl,
            deny_commands=self._deny_commands,
            constraints_locked=constraints_locked,
        )

    # -- public API ---------------------------------------------------------

    def validate(self, patch: Patch) -> GuardResult:
        """Validate a patch.  Returns *GuardResult* with ``passed=True``
        or a rejection containing the offending channel and remediation hint.
        """
        guard_cfg = self._constraints.guard

        # Fast-path: guard disabled -> everything passes
        if not guard_cfg.enabled:
            return GuardResult(passed=True)

        # 1. Check config_vars for locked vars
        result = self._check_config_vars(patch)
        if result is not None:
            return result

        # 2. Check sdc_edits (placeholder for P2.3 -- SDC scanner)
        result = self._check_sdc_edits(patch)
        if result is not None:
            return result

        # 3. Check tcl_edits (placeholder for P2.4 -- Tcl scanner)
        result = self._check_tcl_edits(patch)
        if result is not None:
            return result

        return GuardResult(passed=True)

    # -- private helpers ----------------------------------------------------

    def _check_config_vars(self, patch: Patch) -> GuardResult | None:
        """Check if the patch modifies any locked config variables.

        Returns ``None`` if there is no violation (check passes).
        """
        if not patch.config_vars:
            return None

        locked = set(self._constraints.locked_vars)
        offending = [var for var in patch.config_vars if var in locked]

        if not offending:
            return None

        hint_vars = ", ".join(offending)
        return GuardResult(
            passed=False,
            rejection=PatchRejected(
                patch_id=patch.patch_id,
                stage=patch.stage,
                reason_code="locked_constraint",
                offending_channel="config_vars",
                offending_commands=offending,
                offending_lines=[],
                remediation_hint=(
                    f"The following config variables are locked and may not be "
                    f"modified: {hint_vars}. Remove them from your patch or "
                    f"propose changes to unlocked knobs instead."
                ),
            ),
        )

    def _check_sdc_edits(self, patch: Patch) -> GuardResult | None:
        """Validate SDC edits through the SDC restricted-dialect scanner.

        Each SDC edit's ``lines`` are preprocessed for line continuations
        and then scanned for deny-listed commands, forbidden tokens,
        semicolons, unsafe bracket expressions, etc.

        Returns ``None`` if there are no violations (check passes).
        """
        if not patch.sdc_edits:
            return None

        # SDC must be permitted by action_space
        if not self._action_space.permissions.sdc:
            return GuardResult(
                passed=False,
                rejection=PatchRejected(
                    patch_id=patch.patch_id,
                    stage=patch.stage,
                    reason_code="sdc_not_permitted",
                    offending_channel="sdc_edits",
                    offending_commands=[],
                    offending_lines=[],
                    remediation_hint=(
                        "SDC edits are not permitted by the current "
                        "action_space configuration. Remove sdc_edits "
                        "from your patch."
                    ),
                ),
            )

        guard_cfg = self._constraints.guard
        for sdc_edit in patch.sdc_edits:
            raw_text = "\n".join(sdc_edit.lines)
            if not raw_text.strip():
                continue

            # Preprocess line continuations
            try:
                pp = preprocess_lines(
                    raw_text,
                    max_joined_lines=guard_cfg.preprocess.max_joined_lines,
                    reject_unterminated=guard_cfg.preprocess.reject_unterminated_continuation,
                )
            except LineContinuationError as exc:
                return GuardResult(
                    passed=False,
                    rejection=PatchRejected(
                        patch_id=patch.patch_id,
                        stage=patch.stage,
                        reason_code="sdc_line_continuation_error",
                        offending_channel="sdc_edits",
                        offending_commands=[],
                        offending_lines=[exc.line_number],
                        remediation_hint=(
                            f"SDC edit '{sdc_edit.name}' has a line "
                            f"continuation error: {exc}. Fix the "
                            f"backslash continuations."
                        ),
                    ),
                )

            # Scan through the SDC scanner
            scan_result = self._sdc_scanner.scan(pp.logical_lines)
            if not scan_result.passed:
                offending_cmds = [
                    v.detail for v in scan_result.violations
                ]
                offending_lines = [
                    v.line_number for v in scan_result.violations
                ]
                first_v = scan_result.violations[0]
                return GuardResult(
                    passed=False,
                    rejection=PatchRejected(
                        patch_id=patch.patch_id,
                        stage=patch.stage,
                        reason_code="sdc_constraint_violation",
                        offending_channel="sdc_edits",
                        offending_commands=offending_cmds,
                        offending_lines=offending_lines,
                        remediation_hint=(
                            f"SDC edit '{sdc_edit.name}' violates the "
                            f"restricted SDC dialect: {first_v.detail} "
                            f"(line {first_v.line_number}: "
                            f"{first_v.line_text!r}). Remove the "
                            f"offending commands or use allowed "
                            f"alternatives."
                        ),
                    ),
                )

        return None

    def _check_tcl_edits(self, patch: Patch) -> GuardResult | None:
        """Validate Tcl edits through the Tcl restricted-dialect scanner.

        Each Tcl edit's ``lines`` are preprocessed for line continuations
        and then scanned for deny-listed commands, forbidden tokens,
        semicolons, etc.

        Returns ``None`` if there are no violations (check passes).
        """
        if not patch.tcl_edits:
            return None

        # Tcl must be permitted by action_space
        if not self._action_space.permissions.tcl:
            return GuardResult(
                passed=False,
                rejection=PatchRejected(
                    patch_id=patch.patch_id,
                    stage=patch.stage,
                    reason_code="tcl_not_permitted",
                    offending_channel="tcl_edits",
                    offending_commands=[],
                    offending_lines=[],
                    remediation_hint=(
                        "Tcl edits are not permitted by the current "
                        "action_space configuration. Remove tcl_edits "
                        "from your patch."
                    ),
                ),
            )

        guard_cfg = self._constraints.guard
        for tcl_edit in patch.tcl_edits:
            lines = getattr(tcl_edit, "lines", [])
            raw_text = "\n".join(lines)
            if not raw_text.strip():
                continue

            # Preprocess line continuations
            try:
                pp = preprocess_lines(
                    raw_text,
                    max_joined_lines=guard_cfg.preprocess.max_joined_lines,
                    reject_unterminated=guard_cfg.preprocess.reject_unterminated_continuation,
                )
            except LineContinuationError as exc:
                return GuardResult(
                    passed=False,
                    rejection=PatchRejected(
                        patch_id=patch.patch_id,
                        stage=patch.stage,
                        reason_code="tcl_line_continuation_error",
                        offending_channel="tcl_edits",
                        offending_commands=[],
                        offending_lines=[exc.line_number],
                        remediation_hint=(
                            f"Tcl edit '{tcl_edit.name}' has a line "
                            f"continuation error: {exc}. Fix the "
                            f"backslash continuations."
                        ),
                    ),
                )

            # Scan through the Tcl scanner
            scan_result = self._tcl_scanner.scan(pp.logical_lines)
            if not scan_result.passed:
                offending_cmds = [
                    v.detail for v in scan_result.violations
                ]
                offending_lines = [
                    v.line_number for v in scan_result.violations
                ]
                first_v = scan_result.violations[0]
                return GuardResult(
                    passed=False,
                    rejection=PatchRejected(
                        patch_id=patch.patch_id,
                        stage=patch.stage,
                        reason_code="tcl_constraint_violation",
                        offending_channel="tcl_edits",
                        offending_commands=offending_cmds,
                        offending_lines=offending_lines,
                        remediation_hint=(
                            f"Tcl edit '{tcl_edit.name}' violates the "
                            f"restricted Tcl dialect: {first_v.detail} "
                            f"(line {first_v.line_number}: "
                            f"{first_v.line_text!r}). Remove the "
                            f"offending commands or use allowed "
                            f"alternatives."
                        ),
                    ),
                )

        return None

    def _derive_deny_commands(self) -> list[str]:
        """Derive the deny command list from locked_aspects using ASPECT_DENY_MAP.

        When *any* constraints are locked and Tcl is enabled, ``read_sdc``
        is also denied (loader loophole closure).
        """
        deny: list[str] = []

        for aspect in self._constraints.locked_aspects:
            deny.extend(ASPECT_DENY_MAP.get(aspect, []))

        # Loader-loophole closure: if any aspect is locked and Tcl enabled
        if self._constraints.locked_aspects and self._action_space.tcl.enabled:
            deny.extend(TCL_CONSTRAINT_DENY)

        # Also include any explicitly configured deny_commands from guard config
        deny.extend(self._constraints.guard.sdc.deny_commands)
        deny.extend(self._constraints.guard.tcl.deny_commands)

        # Deduplicate while preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for cmd in deny:
            if cmd not in seen:
                seen.add(cmd)
                unique.append(cmd)

        return unique

    @property
    def deny_commands(self) -> list[str]:
        """Read-only access to the derived deny command list."""
        return list(self._deny_commands)
