"""Tests for knowledge query builder."""

from __future__ import annotations

from agenticlane.knowledge.query_builder import build_query
from agenticlane.schemas.evidence import ErrorWarning, EvidencePack, SpatialHotspot
from agenticlane.schemas.metrics import (
    MetricsPayload,
    PhysicalMetrics,
    RouteMetrics,
    SignoffMetrics,
    TimingMetrics,
)


class TestBuildQuery:
    """Query construction from stage context."""

    def test_stage_only(self) -> None:
        q = build_query("SYNTH")
        assert "SYNTH" in q
        assert "optimization" in q

    def test_with_timing_violation(self) -> None:
        metrics = MetricsPayload(
            run_id="r1",
            branch_id="B0",
            stage="SYNTH",
            attempt=1,
            execution_status="success",
            timing=TimingMetrics(setup_wns_ns={"nom_tt_025C_1v80": -0.5}),
        )
        q = build_query("SYNTH", metrics=metrics)
        assert "setup timing violation" in q

    def test_with_congestion(self) -> None:
        metrics = MetricsPayload(
            run_id="r1",
            branch_id="B0",
            stage="ROUTE_GLOBAL",
            attempt=1,
            execution_status="success",
            route=RouteMetrics(congestion_overflow_pct=5.0),
        )
        q = build_query("ROUTE_GLOBAL", metrics=metrics)
        assert "congestion" in q

    def test_with_drc_violations(self) -> None:
        metrics = MetricsPayload(
            run_id="r1",
            branch_id="B0",
            stage="SIGNOFF",
            attempt=1,
            execution_status="success",
            signoff=SignoffMetrics(drc_count=42),
        )
        q = build_query("SIGNOFF", metrics=metrics)
        assert "DRC" in q

    def test_with_high_utilization(self) -> None:
        metrics = MetricsPayload(
            run_id="r1",
            branch_id="B0",
            stage="FLOORPLAN",
            attempt=1,
            execution_status="success",
            physical=PhysicalMetrics(utilization_pct=90.0),
        )
        q = build_query("FLOORPLAN", metrics=metrics)
        assert "high utilization" in q

    def test_with_low_utilization(self) -> None:
        metrics = MetricsPayload(
            run_id="r1",
            branch_id="B0",
            stage="FLOORPLAN",
            attempt=1,
            execution_status="success",
            physical=PhysicalMetrics(utilization_pct=20.0),
        )
        q = build_query("FLOORPLAN", metrics=metrics)
        assert "low utilization" in q

    def test_with_evidence_errors(self) -> None:
        evidence = EvidencePack(
            stage="SYNTH",
            attempt=1,
            execution_status="success",
            errors=[
                ErrorWarning(
                    source="yosys",
                    severity="error",
                    message="undriven wire foo",
                )
            ],
        )
        q = build_query("SYNTH", evidence=evidence)
        assert "undriven wire" in q

    def test_with_spatial_hotspots(self) -> None:
        evidence = EvidencePack(
            stage="PLACE_GLOBAL",
            attempt=1,
            execution_status="success",
            spatial_hotspots=[
                SpatialHotspot(
                    type="congestion",
                    grid_bin={"x": 1, "y": 1},
                    severity=0.9,
                )
            ],
        )
        q = build_query("PLACE_GLOBAL", evidence=evidence)
        assert "congestion hotspot" in q

    def test_no_metrics_no_evidence(self) -> None:
        q = build_query("CTS")
        assert "CTS" in q
        assert len(q) > 5

    def test_positive_timing_no_violation_keyword(self) -> None:
        metrics = MetricsPayload(
            run_id="r1",
            branch_id="B0",
            stage="SYNTH",
            attempt=1,
            execution_status="success",
            timing=TimingMetrics(setup_wns_ns={"nom": 0.5}),
        )
        q = build_query("SYNTH", metrics=metrics)
        assert "timing violation" not in q
