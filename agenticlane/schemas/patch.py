"""Patch schemas for AgenticLane.

Defines the Patch (v5) and PatchRejected (v1) models, along with
sub-models for macro placements, SDC edits, and Tcl edits.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class MacroPlacement(BaseModel):
    """A single macro placement directive.

    Can specify either a location hint (NW/NE/SW/SE/CENTER/PERIPHERY)
    or explicit x/y coordinates in micrometers.
    """

    instance: str = Field(description="Macro instance name (e.g., U_SRAM_0)")
    location_hint: Optional[str] = Field(
        default=None,
        description="Coarse placement hint: NW, NE, SW, SE, CENTER, PERIPHERY",
    )
    x_um: Optional[float] = Field(
        default=None, description="Explicit X coordinate in micrometers"
    )
    y_um: Optional[float] = Field(
        default=None, description="Explicit Y coordinate in micrometers"
    )
    orientation: str = Field(
        default="N",
        description="Orientation (N, S, E, W, FN, FS, FE, FW)",
    )


class SDCEdit(BaseModel):
    """A single SDC file edit.

    Currently only supports append_lines mode: lines are appended
    to the named SDC file.
    """

    name: str = Field(description="SDC file name (e.g., agent_floorplan.sdc)")
    mode: Literal["append_lines"] = Field(
        default="append_lines",
        description="Edit mode (currently only append_lines)",
    )
    lines: list[str] = Field(
        default_factory=list,
        description="SDC lines to append",
    )


class TclEdit(BaseModel):
    """A single Tcl hook edit.

    Defines a Tcl snippet to inject at a specific hook point
    in the LibreLane flow.
    """

    name: str = Field(
        default="agent_hook.tcl",
        description="Tcl file name (e.g., post_gp_fix.tcl)",
    )
    tool: str = Field(
        default="openroad",
        description="EDA tool name (e.g., openroad)",
    )
    hook: dict[str, str] = Field(
        default_factory=lambda: {"type": "post", "step_id": "auto"},
        description="Hook definition with 'type' and 'step_id' keys",
    )

    @field_validator("hook", mode="before")
    @classmethod
    def _coerce_hook(cls, v: Any) -> dict[str, str]:
        """Coerce a bare string hook to dict format.

        Gemini sometimes returns ``"pre_signoff"`` instead of
        ``{"type": "pre", "step_id": "signoff"}``.
        """
        if isinstance(v, str):
            return {"type": "post", "step_id": v}
        return dict(v)  # type: ignore[arg-type]
    mode: Literal["append_lines"] = Field(
        default="append_lines",
        description="Edit mode (currently only append_lines)",
    )
    lines: list[str] = Field(
        default_factory=list,
        description="Tcl lines to append",
    )


class Patch(BaseModel):
    """Patch proposal (schema_version=5).

    Structured proposal from a worker agent that modifies allowed inputs:
    config variables, macro placements, SDC fragments, Tcl hooks, or RTL ECO.
    """

    schema_version: Literal[5] = Field(
        default=5, description="Schema version (must be 5)"
    )

    @field_validator("schema_version", mode="before")
    @classmethod
    def _coerce_schema_version(cls, v: Any) -> int:
        """Coerce string '5' to int 5 (Gemini sometimes returns strings)."""
        if isinstance(v, str):
            return int(v)
        return int(v)

    patch_id: str = Field(
        default="auto",
        description="Unique patch identifier (UUID or hash)",
    )
    stage: str = Field(
        default="UNKNOWN",
        description="Target stage name (e.g., FLOORPLAN)",
    )
    types: list[
        Literal[
            "config_vars",
            "macro_placements",
            "sdc_edits",
            "tcl_edits",
            "rtl_changes",
        ]
    ] = Field(
        default_factory=list,
        description="List of patch channel types included",
    )
    config_vars: dict[str, Any] = Field(
        default_factory=dict,
        description="Config variable overrides (knob name -> value)",
    )
    macro_placements: list[MacroPlacement] = Field(
        default_factory=list,
        description="Macro placement directives",
    )
    sdc_edits: list[SDCEdit] = Field(
        default_factory=list,
        description="SDC file edits",
    )
    tcl_edits: list[TclEdit] = Field(
        default_factory=list,
        description="Tcl hook edits",
    )
    rtl_changes: Optional[Any] = Field(
        default=None,
        description="RTL ECO changes (reserved for future use)",
    )
    declared_constraint_changes: dict[str, Any] = Field(
        default_factory=dict,
        description="Constraints the agent declares it is changing (for audit)",
    )
    rationale: str = Field(
        default="",
        description="Agent's rationale for the proposed changes",
    )


class PatchRejected(BaseModel):
    """Patch rejection record (schema_version=1).

    Produced by ConstraintGuard when a patch violates safety rules.
    Does not burn a physical attempt budget.
    """

    schema_version: Literal[1] = Field(
        default=1, description="Schema version (must be 1)"
    )

    @field_validator("schema_version", mode="before")
    @classmethod
    def _coerce_schema_version(cls, v: Any) -> int:
        """Coerce string '1' to int 1 (Gemini sometimes returns strings)."""
        if isinstance(v, str):
            return int(v)
        return int(v)

    patch_id: str = Field(
        description="ID of the rejected patch"
    )
    stage: str = Field(
        description="Stage where the patch was proposed"
    )
    reason_code: str = Field(
        description="Machine-readable reason code (e.g., locked_constraint_backdoor)",
    )
    offending_channel: str = Field(
        description="Which channel violated rules (config_vars, sdc_edits, tcl_edits)",
    )
    offending_commands: list[str] = Field(
        default_factory=list,
        description="List of forbidden commands found",
    )
    offending_lines: list[int] = Field(
        default_factory=list,
        description="Line numbers (1-indexed) of violations",
    )
    remediation_hint: str = Field(
        default="",
        description="Human-readable hint for the agent to fix the patch",
    )
