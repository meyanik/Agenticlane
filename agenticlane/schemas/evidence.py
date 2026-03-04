"""Evidence schemas for AgenticLane.

Defines the EvidencePack (v1) and its sub-models for errors/warnings,
spatial hotspots, and crash information distilled from stage execution.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class ErrorWarning(BaseModel):
    """A single error or warning extracted from EDA tool output."""

    source: str = Field(
        description="Source identifier (e.g., tool name, log file name)"
    )
    severity: Literal["error", "warning", "info"] = Field(
        description="Severity level"
    )
    message: str = Field(description="The error/warning message text")
    count: int = Field(
        default=1,
        ge=1,
        description="Number of occurrences of this message",
    )


class SpatialHotspot(BaseModel):
    """A spatial hotspot identified in the design.

    Represents a congestion or DRC hotspot in the placement/routing grid.
    """

    type: Literal["congestion", "drc"] = Field(
        description="Hotspot type"
    )
    grid_bin: dict[str, int] = Field(
        description="Grid bin coordinates with 'x' and 'y' integer keys",
    )
    region_label: str = Field(
        default="",
        description="Human-readable region label (e.g., NW quadrant)",
    )
    severity: float = Field(
        ge=0.0,
        le=1.0,
        description="Severity score normalized 0.0-1.0",
    )
    nearby_macros: list[str] = Field(
        default_factory=list,
        description="List of macro instance names near this hotspot",
    )
    # Coordinate bounds for the grid bin (Phase 4)
    x_min_um: Optional[float] = Field(
        default=None,
        description="Bin left edge in micrometers",
    )
    y_min_um: Optional[float] = Field(
        default=None,
        description="Bin bottom edge in micrometers",
    )
    x_max_um: Optional[float] = Field(
        default=None,
        description="Bin right edge in micrometers",
    )
    y_max_um: Optional[float] = Field(
        default=None,
        description="Bin top edge in micrometers",
    )


class CrashInfo(BaseModel):
    """Crash diagnostic information.

    Captured when a stage execution fails with tool_crash, timeout, or oom_killed.
    """

    crash_type: str = Field(
        description="Type of crash (e.g., tool_crash, timeout, oom_killed)",
    )
    stderr_tail: Optional[str] = Field(
        default=None,
        description="Last N lines of stderr output",
    )
    error_signature: Optional[str] = Field(
        default=None,
        description="Extracted error signature for deduplication",
    )


class EvidencePack(BaseModel):
    """Evidence pack (schema_version=1).

    Aggregates all distilled evidence from a single stage execution attempt.
    Used by agents and judges to understand what happened during execution.
    """

    schema_version: Literal[1] = Field(
        default=1, description="Schema version (must be 1)"
    )
    stage: str = Field(description="Stage name")
    attempt: int = Field(ge=1, description="Attempt number (1-indexed)")
    execution_status: str = Field(
        description="Execution outcome status string"
    )
    errors: list[ErrorWarning] = Field(
        default_factory=list,
        description="List of errors extracted from EDA tool output",
    )
    warnings: list[ErrorWarning] = Field(
        default_factory=list,
        description="List of warnings extracted from EDA tool output",
    )
    spatial_hotspots: list[SpatialHotspot] = Field(
        default_factory=list,
        description="Spatial hotspots (congestion, DRC) identified in the design",
    )
    crash_info: Optional[CrashInfo] = Field(
        default=None,
        description="Crash diagnostics (None if execution succeeded)",
    )
    missing_reports: list[str] = Field(
        default_factory=list,
        description="Expected report files that were not found",
    )
    stderr_tail: Optional[str] = Field(
        default=None,
        description="Last N lines of stderr (convenience copy from ExecutionResult)",
    )
    bounded_snippets: list[dict[str, str]] = Field(
        default_factory=list,
        description="Bounded-length log snippets for LLM context",
    )
