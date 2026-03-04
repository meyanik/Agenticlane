"""Constraint digest schemas for AgenticLane.

Defines the ConstraintDigest (v1) and its sub-models for clock definitions,
exception counts, delay counts, and uncertainty counts.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ClockDefinition(BaseModel):
    """A single clock definition extracted from SDC constraints."""

    name: str = Field(description="Clock name (e.g., core_clk)")
    period_ns: float = Field(
        gt=0.0, description="Clock period in nanoseconds"
    )
    targets: list[str] = Field(
        default_factory=list,
        description="List of port/pin targets for this clock",
    )


class ExceptionCounts(BaseModel):
    """Counts of timing exception constraints."""

    false_path_count: int = Field(
        default=0, ge=0, description="Number of set_false_path commands"
    )
    multicycle_path_count: int = Field(
        default=0, ge=0, description="Number of set_multicycle_path commands"
    )
    disable_timing_count: int = Field(
        default=0, ge=0, description="Number of set_disable_timing commands"
    )


class DelayCounts(BaseModel):
    """Counts of delay constraint commands."""

    set_max_delay_count: int = Field(
        default=0, ge=0, description="Number of set_max_delay commands"
    )
    set_min_delay_count: int = Field(
        default=0, ge=0, description="Number of set_min_delay commands"
    )


class UncertaintyCounts(BaseModel):
    """Counts of clock uncertainty constraint commands."""

    set_clock_uncertainty_count: int = Field(
        default=0, ge=0, description="Number of set_clock_uncertainty commands"
    )


class ConstraintDigest(BaseModel):
    """Constraint digest (schema_version=1).

    Distilled fingerprint of applied timing constraints.
    Used for anti-cheat scoring and constraint change auditing.
    When opaque=True, the SDC was not parseable (e.g., Tcl expert mode)
    and constraint counts may be unreliable.
    """

    schema_version: Literal[1] = Field(
        default=1, description="Schema version (must be 1)"
    )
    opaque: bool = Field(
        default=False,
        description="True if constraints could not be fully parsed",
    )
    clocks: list[ClockDefinition] = Field(
        default_factory=list,
        description="List of clock definitions found in SDC",
    )
    exceptions: ExceptionCounts = Field(
        default_factory=ExceptionCounts,
        description="Timing exception counts",
    )
    delays: DelayCounts = Field(
        default_factory=DelayCounts,
        description="Delay constraint counts",
    )
    uncertainty: UncertaintyCounts = Field(
        default_factory=UncertaintyCounts,
        description="Clock uncertainty counts",
    )
    notes: list[str] = Field(
        default_factory=list,
        description="Free-form notes about constraint parsing",
    )
