"""Patch materialization pipeline for AgenticLane.

Enforces a strict 10-step order for processing and applying patches.
Steps 1-3 are "early rejection" -- if they fail, the EDA tool is never
called, saving physical budget.

Steps:
    1. Schema validation (Patch model valid)
    2. Knob range validation (config_vars within KnobSpec ranges)
    3. ConstraintGuard check (locked vars, SDC/Tcl scanning)
    4. Macro name resolution (resolve instance names)
    5. Grid snap (snap macro coordinates to placement grid)
    6. SDC materialization (write SDC fragments to files)
    7. Tcl materialization (write Tcl hooks to files)
    8. Config override application (apply config_vars to design config)
    9. LibreLane config assembly (combine all into executable config)
   10. Execution (run the stage via adapter)

Steps 9 and 10 are executed by the orchestrator, not this module.
This module handles steps 1-8.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from agenticlane.schemas.patch import Patch, PatchRejected

logger = logging.getLogger(__name__)


class EarlyRejectionError(Exception):
    """Raised when a patch fails early validation (steps 1-3).

    The ``rejection`` attribute contains a :class:`PatchRejected` with
    details about what went wrong and a remediation hint for the agent.
    """

    def __init__(self, rejection: PatchRejected) -> None:
        self.rejection = rejection
        super().__init__(f"Patch rejected: {rejection.reason_code}")


class ConstraintGuardProtocol(Protocol):
    """Minimal interface expected from a ConstraintGuard instance."""

    def validate(self, patch: Patch) -> _GuardResult:
        """Validate a patch against constraint rules."""
        ...


class _GuardResult(Protocol):
    """Minimal result interface returned by ConstraintGuard.validate."""

    @property
    def passed(self) -> bool: ...

    @property
    def rejection(self) -> PatchRejected | None: ...


@dataclass
class MaterializeContext:
    """Context accumulated through the pipeline steps.

    Each step may read and/or add to this context.  After all 8 steps
    complete, the orchestrator uses the context to assemble the final
    LibreLane config and run the stage.
    """

    patch: Patch
    attempt_dir: Path
    stage_name: str
    resolved_config_vars: dict[str, Any] = field(default_factory=dict)
    sdc_fragment_paths: list[Path] = field(default_factory=list)
    tcl_hook_paths: list[Path] = field(default_factory=list)
    design_config_overrides: dict[str, Any] = field(default_factory=dict)
    steps_completed: list[str] = field(default_factory=list)
    macro_cfg_path: Path | None = None
    resolved_macros: list[Any] = field(default_factory=list)


class PatchMaterializer:
    """Enforces the 10-step mandatory order for patch application.

    Steps 1-3 can raise :exc:`EarlyRejectionError`, which means the EDA
    tool is never invoked.  This saves physical attempt budget.

    Steps 4-8 prepare files and config overrides for execution.
    Steps 9-10 (config assembly and execution) are handled by the
    orchestrator using the :class:`MaterializeContext` returned here.
    """

    def __init__(
        self,
        *,
        constraint_guard: Any | None = None,
        core_bbox: Any | None = None,
        placement_site: Any | None = None,
        known_instances: set[str] | None = None,
        macro_sizes: dict[str, tuple[float, float]] | None = None,
        snap_config: Any | None = None,
        dbu_per_um: float = 1000.0,
    ) -> None:
        """Initialise the materializer.

        Args:
            constraint_guard: An optional ConstraintGuard instance for
                step 3.  If ``None``, step 3 is skipped.
            core_bbox: A :class:`CoreBBox` for macro resolution (step 4).
                If ``None``, macro resolution is skipped.
            placement_site: A :class:`PlacementSite` for grid snap.
                Required together with ``core_bbox`` for macro resolution.
            known_instances: Set of valid macro instance names (optional).
            macro_sizes: Dict of instance -> (width_um, height_um) for
                collision detection.
            snap_config: A :class:`SnapConfig` with grid-snap settings
                (enabled, rounding, max_iterations).
            dbu_per_um: Database units per micrometer (default 1000).
        """
        self._guard = constraint_guard
        self._core_bbox = core_bbox
        self._placement_site = placement_site
        self._known_instances = known_instances
        self._macro_sizes = macro_sizes
        self._snap_config = snap_config
        self._dbu_per_um = dbu_per_um

    def materialize(
        self,
        patch: Patch,
        attempt_dir: Path,
        stage_name: str,
    ) -> MaterializeContext:
        """Run steps 1-8 of the pipeline.

        Args:
            patch: The proposed patch to materialise.
            attempt_dir: Filesystem directory for this attempt.
            stage_name: Canonical stage name (e.g. ``"FLOORPLAN"``).

        Returns:
            A :class:`MaterializeContext` with all paths and overrides
            populated.

        Raises:
            EarlyRejectionError: If any of steps 1-3 fails validation.
        """
        ctx = MaterializeContext(
            patch=patch,
            attempt_dir=attempt_dir,
            stage_name=stage_name,
        )

        # Step 1: Schema validation
        self._step_schema_validation(ctx)

        # Step 2: Knob range validation
        self._step_knob_validation(ctx)

        # Step 3: ConstraintGuard
        self._step_constraint_guard(ctx)

        # Step 4: Macro resolution
        self._step_macro_resolution(ctx)

        # Step 5: Grid snap
        self._step_grid_snap(ctx)

        # Step 6: SDC materialization
        self._step_sdc_materialize(ctx)

        # Step 7: Tcl materialization
        self._step_tcl_materialize(ctx)

        # Step 8: Config overrides
        self._step_config_overrides(ctx)

        return ctx

    # ------------------------------------------------------------------
    # Step implementations
    # ------------------------------------------------------------------

    def _step_schema_validation(self, ctx: MaterializeContext) -> None:
        """Step 1: Validate patch schema.

        The Pydantic model already enforces most constraints, but we
        additionally require a non-empty ``patch_id``.
        """
        if not ctx.patch.patch_id:
            raise EarlyRejectionError(
                PatchRejected(
                    patch_id="",
                    stage=ctx.stage_name,
                    reason_code="invalid_schema",
                    offending_channel="patch",
                    remediation_hint="Patch must have a valid patch_id.",
                ),
            )
        ctx.steps_completed.append("schema_validation")

    def _step_knob_validation(self, ctx: MaterializeContext) -> None:
        """Step 2: Validate knob values against KnobSpec ranges.

        Each config_var is checked against the knob registry.  Unknown
        knobs are passed through (they may be tool-specific variables not
        in the registry).
        """
        from agenticlane.config.knobs import get_knob, validate_knob_value

        for knob_name, value in ctx.patch.config_vars.items():
            try:
                get_knob(knob_name)
            except KeyError:
                # Unknown knob -- pass through (may be tool-specific)
                continue

            try:
                validate_knob_value(knob_name, value)
            except (ValueError, TypeError) as exc:
                raise EarlyRejectionError(
                    PatchRejected(
                        patch_id=ctx.patch.patch_id,
                        stage=ctx.stage_name,
                        reason_code="knob_out_of_range",
                        offending_channel="config_vars",
                        offending_commands=[knob_name],
                        remediation_hint=str(exc),
                    ),
                ) from exc

        ctx.steps_completed.append("knob_validation")

    def _step_constraint_guard(self, ctx: MaterializeContext) -> None:
        """Step 3: Run ConstraintGuard.

        If no guard is configured, this step is recorded as skipped.
        """
        if self._guard is None:
            ctx.steps_completed.append("constraint_guard_skipped")
            return

        result = self._guard.validate(ctx.patch)
        if not result.passed:
            raise EarlyRejectionError(result.rejection)

        ctx.steps_completed.append("constraint_guard")

    def _step_macro_resolution(self, ctx: MaterializeContext) -> None:
        """Step 4: Resolve macro placements (hint->coords, validation).

        When ``core_bbox`` and ``placement_site`` are configured, runs the
        full resolution pipeline from :mod:`agenticlane.execution.grid_snap`.
        Otherwise the step is skipped.
        """
        if not ctx.patch.macro_placements:
            ctx.steps_completed.append("macro_resolution_skipped")
            return

        if self._core_bbox is None or self._placement_site is None:
            # No placement info available -- skip resolution
            ctx.steps_completed.append("macro_resolution_skipped")
            return

        from typing import Literal as _Lit

        from agenticlane.execution.grid_snap import resolve_macro_placements

        snap_enabled = True
        rounding: _Lit["nearest", "floor", "ceil"] = "nearest"
        max_iterations = 5
        if self._snap_config is not None:
            snap_enabled = self._snap_config.enabled
            rounding = self._snap_config.rounding
            max_iterations = self._snap_config.max_iterations

        try:
            resolved = resolve_macro_placements(
                placements=ctx.patch.macro_placements,
                core_bbox=self._core_bbox,
                site=self._placement_site,
                known_instances=self._known_instances,
                macro_sizes=self._macro_sizes,
                dbu_per_um=self._dbu_per_um,
                rounding=rounding,
                snap_enabled=snap_enabled,
                max_iterations=max_iterations,
            )
            ctx.resolved_macros = resolved
        except ValueError as exc:
            raise EarlyRejectionError(
                PatchRejected(
                    patch_id=ctx.patch.patch_id,
                    stage=ctx.stage_name,
                    reason_code="macro_placement_error",
                    offending_channel="macro_placements",
                    remediation_hint=str(exc),
                )
            ) from exc

        ctx.steps_completed.append("macro_resolution")

    def _step_grid_snap(self, ctx: MaterializeContext) -> None:
        """Step 5: Write MACRO_PLACEMENT_CFG file.

        Generates the MACRO_PLACEMENT_CFG text file from resolved macros
        produced by step 4.  If no resolved macros are present, the step
        is skipped.
        """
        if not ctx.resolved_macros:
            ctx.steps_completed.append("grid_snap_skipped")
            return

        from agenticlane.execution.macro_cfg import write_macro_cfg

        cfg_path = write_macro_cfg(
            macros=ctx.resolved_macros,
            output_dir=ctx.attempt_dir,
        )
        ctx.macro_cfg_path = cfg_path
        ctx.steps_completed.append("grid_snap")

    def _step_sdc_materialize(self, ctx: MaterializeContext) -> None:
        """Step 6: Write SDC fragments to files.

        Each :class:`SDCEdit` in the patch is written to a file under
        ``<attempt_dir>/constraints/``.
        """
        constraints_dir = ctx.attempt_dir / "constraints"
        constraints_dir.mkdir(parents=True, exist_ok=True)

        for sdc_edit in ctx.patch.sdc_edits:
            fragment_path = constraints_dir / sdc_edit.name
            content = (
                "\n".join(sdc_edit.lines) + "\n" if sdc_edit.lines else ""
            )
            fragment_path.write_text(content)
            ctx.sdc_fragment_paths.append(fragment_path)

        ctx.steps_completed.append("sdc_materialize")

    def _step_tcl_materialize(self, ctx: MaterializeContext) -> None:
        """Step 7: Write Tcl hooks to files.

        Each :class:`TclEdit` in the patch is written to a file under
        ``<attempt_dir>/constraints/``.
        """
        constraints_dir = ctx.attempt_dir / "constraints"
        constraints_dir.mkdir(parents=True, exist_ok=True)

        for tcl_edit in ctx.patch.tcl_edits:
            hook_path = constraints_dir / tcl_edit.name
            content = (
                "\n".join(tcl_edit.lines) + "\n" if tcl_edit.lines else ""
            )
            hook_path.write_text(content)
            ctx.tcl_hook_paths.append(hook_path)

        ctx.steps_completed.append("tcl_materialize")

    def _step_config_overrides(self, ctx: MaterializeContext) -> None:
        """Step 8: Apply config variable overrides.

        Copies all config_vars from the patch into the context for
        downstream assembly (step 9, handled by the orchestrator).
        """
        ctx.resolved_config_vars = dict(ctx.patch.config_vars)
        ctx.steps_completed.append("config_overrides")
