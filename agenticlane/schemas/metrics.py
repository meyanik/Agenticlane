"""Metrics schemas for AgenticLane.

Defines the MetricsPayload (v3) and its sub-models for timing,
physical, routing, signoff, and runtime metrics.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from agenticlane.schemas.execution import ExecutionStatus


class TimingMetrics(BaseModel):
    """Per-corner timing metrics.

    setup_wns_ns is a dict mapping corner name to worst negative slack
    in nanoseconds. None means the metric was not extracted.
    """

    setup_wns_ns: dict[str, Optional[float]] = Field(
        default_factory=dict,
        description="Per-corner setup worst negative slack (ns). Corner name -> WNS.",
    )


class PhysicalMetrics(BaseModel):
    """Physical design metrics (area, utilization)."""

    core_area_um2: Optional[float] = Field(
        default=None,
        description="Core area in square micrometers",
    )
    utilization_pct: Optional[float] = Field(
        default=None,
        description="Core utilization percentage",
    )


class RouteMetrics(BaseModel):
    """Routing metrics."""

    congestion_overflow_pct: Optional[float] = Field(
        default=None,
        description="Congestion overflow percentage from global routing",
    )


class SignoffMetrics(BaseModel):
    """Signoff metrics (DRC, LVS)."""

    drc_count: Optional[int] = Field(
        default=None,
        description="Number of DRC violations",
    )
    lvs_pass: Optional[bool] = Field(
        default=None,
        description="Whether LVS check passed",
    )


class RuntimeMetrics(BaseModel):
    """Runtime performance metrics."""

    stage_seconds: Optional[float] = Field(
        default=None,
        description="Wall-clock time for the stage in seconds",
    )


class PowerMetrics(BaseModel):
    """Power analysis metrics."""

    total_power_mw: Optional[float] = Field(
        default=None,
        description="Total power consumption in milliwatts",
    )
    internal_power_mw: Optional[float] = Field(
        default=None,
        description="Internal (cell) power in milliwatts",
    )
    switching_power_mw: Optional[float] = Field(
        default=None,
        description="Switching (dynamic) power in milliwatts",
    )
    leakage_power_mw: Optional[float] = Field(
        default=None,
        description="Leakage (static) power in milliwatts",
    )
    leakage_pct: Optional[float] = Field(
        default=None,
        description="Leakage power as percentage of total power",
    )


class SynthesisMetrics(BaseModel):
    """Post-synthesis design statistics."""

    cell_count: Optional[int] = Field(
        default=None, description="Total cell count after synthesis"
    )
    net_count: Optional[int] = Field(
        default=None, description="Total net count"
    )
    area_estimate_um2: Optional[float] = Field(
        default=None, description="Estimated area from yosys stat"
    )


class MetricsPayload(BaseModel):
    """Canonical metrics payload (schema_version=3).

    Aggregates all metric categories for a single stage execution attempt.
    Null sub-metrics indicate missing or unextractable data.
    """

    schema_version: Literal[3] = Field(
        default=3, description="Schema version (must be 3)"
    )
    run_id: str = Field(description="Run identifier")
    branch_id: str = Field(description="Branch identifier")
    stage: str = Field(description="Stage name")
    attempt: int = Field(ge=1, description="Attempt number (1-indexed)")
    execution_status: ExecutionStatus = Field(
        description="Execution outcome status"
    )
    missing_metrics: list[str] = Field(
        default_factory=list,
        description="List of metric keys that could not be extracted",
    )
    constraints_digest_path: Optional[str] = Field(
        default=None,
        description="Relative path to the ConstraintDigest JSON file",
    )
    timing: Optional[TimingMetrics] = Field(
        default=None,
        description="Timing metrics (per-corner WNS)",
    )
    physical: Optional[PhysicalMetrics] = Field(
        default=None,
        description="Physical metrics (area, utilization)",
    )
    route: Optional[RouteMetrics] = Field(
        default=None,
        description="Routing metrics (congestion)",
    )
    signoff: Optional[SignoffMetrics] = Field(
        default=None,
        description="Signoff metrics (DRC, LVS)",
    )
    runtime: Optional[RuntimeMetrics] = Field(
        default=None,
        description="Runtime performance metrics",
    )
    synthesis: Optional[SynthesisMetrics] = Field(
        default=None,
        description="Synthesis metrics (cell count, area estimate)",
    )
    power: Optional[PowerMetrics] = Field(
        default=None,
        description="Power analysis metrics (total, internal, switching, leakage)",
    )
