"""Tests for the specialist agents subsystem.

Covers: BaseSpecialist, TimingSpecialist, RoutabilitySpecialist, DRCSpecialist,
SpecialistAdvice schema, prompt rendering, domain context extraction, and
orchestrator integration with plateau detection.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agenticlane.agents.mock_llm import MockLLMProvider
from agenticlane.agents.specialists import (
    BaseSpecialist,
    DRCSpecialist,
    RoutabilitySpecialist,
    TimingSpecialist,
)
from agenticlane.config.models import AgenticLaneConfig
from agenticlane.schemas.evidence import (
    ErrorWarning,
    EvidencePack,
    SpatialHotspot,
)
from agenticlane.schemas.metrics import (
    MetricsPayload,
    PhysicalMetrics,
    RouteMetrics,
    SignoffMetrics,
    TimingMetrics,
)
from agenticlane.schemas.specialist import KnobRecommendation, SpecialistAdvice

# ------------------------------------------------------------------ #
# Fixtures
# ------------------------------------------------------------------ #


@pytest.fixture()
def config() -> AgenticLaneConfig:
    """Minimal AgenticLane config for specialist tests."""
    return AgenticLaneConfig()


@pytest.fixture()
def mock_llm(tmp_path: Path) -> MockLLMProvider:
    """MockLLMProvider with log dir."""
    return MockLLMProvider(log_dir=tmp_path)


@pytest.fixture()
def timing_metrics() -> MetricsPayload:
    """Metrics with timing violations."""
    return MetricsPayload(
        run_id="test",
        branch_id="B0",
        stage="CTS",
        attempt=1,
        execution_status="success",
        timing=TimingMetrics(setup_wns_ns={"nom_tt_025C_1v80": -0.35, "max_ss_100C_1v60": -1.20}),
        physical=PhysicalMetrics(core_area_um2=50000.0, utilization_pct=55.0),
    )


@pytest.fixture()
def congestion_metrics() -> MetricsPayload:
    """Metrics with congestion overflow."""
    return MetricsPayload(
        run_id="test",
        branch_id="B0",
        stage="ROUTE_GLOBAL",
        attempt=1,
        execution_status="success",
        route=RouteMetrics(congestion_overflow_pct=12.5),
        physical=PhysicalMetrics(core_area_um2=50000.0, utilization_pct=70.0),
    )


@pytest.fixture()
def drc_metrics() -> MetricsPayload:
    """Metrics with DRC violations."""
    return MetricsPayload(
        run_id="test",
        branch_id="B0",
        stage="SIGNOFF",
        attempt=1,
        execution_status="success",
        signoff=SignoffMetrics(drc_count=42, lvs_pass=False),
        physical=PhysicalMetrics(core_area_um2=50000.0, utilization_pct=60.0),
    )


@pytest.fixture()
def timing_evidence() -> EvidencePack:
    """Evidence with timing-related warnings."""
    return EvidencePack(
        stage="CTS",
        attempt=1,
        execution_status="success",
        errors=[
            ErrorWarning(source="openroad", severity="error", message="Setup timing violated on path clk->reg_a"),
        ],
        warnings=[
            ErrorWarning(source="openroad", severity="warning", message="Clock skew exceeds threshold"),
        ],
    )


@pytest.fixture()
def congestion_evidence() -> EvidencePack:
    """Evidence with congestion hotspots."""
    return EvidencePack(
        stage="ROUTE_GLOBAL",
        attempt=1,
        execution_status="success",
        spatial_hotspots=[
            SpatialHotspot(
                type="congestion",
                grid_bin={"x": 3, "y": 5},
                severity=0.8,
                region_label="NE quadrant",
                nearby_macros=["U_SRAM_0"],
            ),
            SpatialHotspot(
                type="congestion",
                grid_bin={"x": 1, "y": 2},
                severity=0.6,
                region_label="SW quadrant",
            ),
        ],
        warnings=[
            ErrorWarning(source="grt", severity="warning", message="Routing overflow in metal3"),
        ],
    )


@pytest.fixture()
def drc_evidence() -> EvidencePack:
    """Evidence with DRC hotspots."""
    return EvidencePack(
        stage="SIGNOFF",
        attempt=1,
        execution_status="success",
        spatial_hotspots=[
            SpatialHotspot(
                type="drc",
                grid_bin={"x": 2, "y": 4},
                severity=0.9,
                region_label="NW quadrant",
            ),
        ],
        errors=[
            ErrorWarning(source="magic", severity="error", message="Metal spacing violation: 42 occurrences"),
        ],
    )


def _make_advice(
    specialist_type: str = "timing",
    **kwargs: Any,
) -> SpecialistAdvice:
    """Helper to build a SpecialistAdvice for mock responses."""
    defaults = {
        "specialist_type": specialist_type,
        "focus_areas": ["test_area_1", "test_area_2"],
        "recommended_knobs": {"PL_TARGET_DENSITY": 0.55},
        "strategy_summary": "Test strategy for breaking plateau",
        "confidence": 0.75,
        "stage": "CTS",
    }
    defaults.update(kwargs)
    return SpecialistAdvice(**defaults)


# ------------------------------------------------------------------ #
# SpecialistAdvice schema tests
# ------------------------------------------------------------------ #


class TestSpecialistAdviceSchema:
    """Tests for the SpecialistAdvice Pydantic model."""

    def test_minimal_construction(self) -> None:
        advice = SpecialistAdvice(specialist_type="timing")
        assert advice.specialist_type == "timing"
        assert advice.focus_areas == []
        assert advice.recommended_knobs == {}
        assert advice.confidence == 0.5

    def test_full_construction(self) -> None:
        advice = SpecialistAdvice(
            specialist_type="drc",
            focus_areas=["spacing_violations", "density"],
            recommended_knobs={"CELL_PAD": 4, "FP_CORE_UTIL": 40},
            strategy_summary="Reduce density and increase cell padding",
            confidence=0.85,
            stage="SIGNOFF",
            detailed_recommendations=[
                KnobRecommendation(
                    knob_name="CELL_PAD",
                    current_value=2,
                    recommended_value=4,
                    rationale="Increase spacing between cells",
                ),
            ],
        )
        assert advice.specialist_type == "drc"
        assert len(advice.focus_areas) == 2
        assert advice.recommended_knobs["CELL_PAD"] == 4
        assert advice.confidence == 0.85
        assert len(advice.detailed_recommendations) == 1

    def test_confidence_bounds(self) -> None:
        with pytest.raises(ValueError):
            SpecialistAdvice(specialist_type="timing", confidence=1.5)
        with pytest.raises(ValueError):
            SpecialistAdvice(specialist_type="timing", confidence=-0.1)

    def test_json_round_trip(self) -> None:
        advice = _make_advice("routability", confidence=0.9)
        json_str = advice.model_dump_json()
        restored = SpecialistAdvice.model_validate_json(json_str)
        assert restored.specialist_type == "routability"
        assert restored.confidence == 0.9
        assert restored.recommended_knobs == {"PL_TARGET_DENSITY": 0.55}


# ------------------------------------------------------------------ #
# TimingSpecialist tests
# ------------------------------------------------------------------ #


class TestTimingSpecialist:
    """Tests for TimingSpecialist."""

    def test_specialist_type(self, mock_llm: MockLLMProvider, config: AgenticLaneConfig) -> None:
        specialist = TimingSpecialist(llm_provider=mock_llm, config=config)
        assert specialist.specialist_type == "timing"

    def test_domain_context_with_violations(
        self,
        mock_llm: MockLLMProvider,
        config: AgenticLaneConfig,
        timing_metrics: MetricsPayload,
        timing_evidence: EvidencePack,
    ) -> None:
        specialist = TimingSpecialist(llm_provider=mock_llm, config=config)
        ctx = specialist._get_domain_context(timing_metrics, timing_evidence)

        assert ctx["has_timing_violations"] is True
        assert ctx["worst_wns"] == -1.20
        assert len(ctx["wns_by_corner"]) == 2
        assert ctx["utilization_pct"] == 55.0
        assert len(ctx["timing_errors"]) == 1
        assert len(ctx["timing_warnings"]) == 1
        assert len(ctx["timing_knobs"]) > 0

    def test_domain_context_without_timing(
        self,
        mock_llm: MockLLMProvider,
        config: AgenticLaneConfig,
    ) -> None:
        metrics = MetricsPayload(
            run_id="test", branch_id="B0", stage="SYNTH",
            attempt=1, execution_status="success",
        )
        evidence = EvidencePack(stage="SYNTH", attempt=1, execution_status="success")
        specialist = TimingSpecialist(llm_provider=mock_llm, config=config)
        ctx = specialist._get_domain_context(metrics, evidence)

        assert ctx["has_timing_violations"] is False
        assert ctx["worst_wns"] is None
        assert ctx["wns_by_corner"] == {}

    async def test_analyze_returns_advice(
        self,
        mock_llm: MockLLMProvider,
        config: AgenticLaneConfig,
        timing_metrics: MetricsPayload,
        timing_evidence: EvidencePack,
    ) -> None:
        advice = _make_advice("timing")
        mock_llm.set_response(advice)

        specialist = TimingSpecialist(llm_provider=mock_llm, config=config)
        result = await specialist.analyze(
            stage="CTS",
            metrics=timing_metrics,
            evidence=timing_evidence,
            history=[0.5, 0.51, 0.505, 0.508, 0.507],
        )
        assert result is not None
        assert result.specialist_type == "timing"
        assert result.stage == "CTS"

    async def test_analyze_returns_none_on_failure(
        self,
        mock_llm: MockLLMProvider,
        config: AgenticLaneConfig,
        timing_metrics: MetricsPayload,
        timing_evidence: EvidencePack,
    ) -> None:
        mock_llm.set_failure(count=100)
        specialist = TimingSpecialist(llm_provider=mock_llm, config=config)
        result = await specialist.analyze(
            stage="CTS",
            metrics=timing_metrics,
            evidence=timing_evidence,
            history=[0.5, 0.51, 0.505],
        )
        assert result is None


# ------------------------------------------------------------------ #
# RoutabilitySpecialist tests
# ------------------------------------------------------------------ #


class TestRoutabilitySpecialist:
    """Tests for RoutabilitySpecialist."""

    def test_specialist_type(self, mock_llm: MockLLMProvider, config: AgenticLaneConfig) -> None:
        specialist = RoutabilitySpecialist(llm_provider=mock_llm, config=config)
        assert specialist.specialist_type == "routability"

    def test_domain_context_with_congestion(
        self,
        mock_llm: MockLLMProvider,
        config: AgenticLaneConfig,
        congestion_metrics: MetricsPayload,
        congestion_evidence: EvidencePack,
    ) -> None:
        specialist = RoutabilitySpecialist(llm_provider=mock_llm, config=config)
        ctx = specialist._get_domain_context(congestion_metrics, congestion_evidence)

        assert ctx["has_congestion"] is True
        assert ctx["congestion_overflow_pct"] == 12.5
        assert ctx["utilization_pct"] == 70.0
        assert len(ctx["congestion_hotspots"]) == 2
        assert ctx["hotspot_count"] == 2
        assert len(ctx["route_warnings"]) == 1
        assert len(ctx["routability_knobs"]) > 0

    def test_domain_context_no_congestion(
        self,
        mock_llm: MockLLMProvider,
        config: AgenticLaneConfig,
    ) -> None:
        metrics = MetricsPayload(
            run_id="test", branch_id="B0", stage="ROUTE_GLOBAL",
            attempt=1, execution_status="success",
        )
        evidence = EvidencePack(stage="ROUTE_GLOBAL", attempt=1, execution_status="success")
        specialist = RoutabilitySpecialist(llm_provider=mock_llm, config=config)
        ctx = specialist._get_domain_context(metrics, evidence)

        assert ctx["has_congestion"] is False
        assert ctx["congestion_overflow_pct"] is None
        assert ctx["congestion_hotspots"] == []

    async def test_analyze_returns_advice(
        self,
        mock_llm: MockLLMProvider,
        config: AgenticLaneConfig,
        congestion_metrics: MetricsPayload,
        congestion_evidence: EvidencePack,
    ) -> None:
        advice = _make_advice("routability")
        mock_llm.set_response(advice)

        specialist = RoutabilitySpecialist(llm_provider=mock_llm, config=config)
        result = await specialist.analyze(
            stage="ROUTE_GLOBAL",
            metrics=congestion_metrics,
            evidence=congestion_evidence,
            history=[0.4, 0.42, 0.41, 0.415, 0.413],
            plateau_info={"window": [0.41, 0.415, 0.413], "mean": 0.4126, "range": 0.005},
        )
        assert result is not None
        assert result.specialist_type == "routability"
        assert result.plateau_info is not None


# ------------------------------------------------------------------ #
# DRCSpecialist tests
# ------------------------------------------------------------------ #


class TestDRCSpecialist:
    """Tests for DRCSpecialist."""

    def test_specialist_type(self, mock_llm: MockLLMProvider, config: AgenticLaneConfig) -> None:
        specialist = DRCSpecialist(llm_provider=mock_llm, config=config)
        assert specialist.specialist_type == "drc"

    def test_domain_context_with_violations(
        self,
        mock_llm: MockLLMProvider,
        config: AgenticLaneConfig,
        drc_metrics: MetricsPayload,
        drc_evidence: EvidencePack,
    ) -> None:
        specialist = DRCSpecialist(llm_provider=mock_llm, config=config)
        ctx = specialist._get_domain_context(drc_metrics, drc_evidence)

        assert ctx["has_drc_violations"] is True
        assert ctx["drc_count"] == 42
        assert ctx["lvs_pass"] is False
        assert len(ctx["drc_hotspots"]) == 1
        assert ctx["drc_hotspot_count"] == 1
        assert len(ctx["drc_errors"]) == 1
        assert len(ctx["drc_knobs"]) > 0

    def test_domain_context_no_violations(
        self,
        mock_llm: MockLLMProvider,
        config: AgenticLaneConfig,
    ) -> None:
        metrics = MetricsPayload(
            run_id="test", branch_id="B0", stage="SIGNOFF",
            attempt=1, execution_status="success",
        )
        evidence = EvidencePack(stage="SIGNOFF", attempt=1, execution_status="success")
        specialist = DRCSpecialist(llm_provider=mock_llm, config=config)
        ctx = specialist._get_domain_context(metrics, evidence)

        assert ctx["has_drc_violations"] is False
        assert ctx["drc_count"] is None
        assert ctx["drc_hotspots"] == []

    async def test_analyze_returns_advice(
        self,
        mock_llm: MockLLMProvider,
        config: AgenticLaneConfig,
        drc_metrics: MetricsPayload,
        drc_evidence: EvidencePack,
    ) -> None:
        advice = _make_advice("drc")
        mock_llm.set_response(advice)

        specialist = DRCSpecialist(llm_provider=mock_llm, config=config)
        result = await specialist.analyze(
            stage="SIGNOFF",
            metrics=drc_metrics,
            evidence=drc_evidence,
            history=[0.3, 0.31, 0.305, 0.308, 0.307],
        )
        assert result is not None
        assert result.specialist_type == "drc"


# ------------------------------------------------------------------ #
# BaseSpecialist prompt rendering tests
# ------------------------------------------------------------------ #


class TestSpecialistPromptRendering:
    """Tests for template rendering in specialists."""

    def test_timing_prompt_renders(
        self,
        mock_llm: MockLLMProvider,
        config: AgenticLaneConfig,
        timing_metrics: MetricsPayload,
        timing_evidence: EvidencePack,
    ) -> None:
        specialist = TimingSpecialist(llm_provider=mock_llm, config=config)
        context = specialist._build_context(
            stage="CTS",
            metrics=timing_metrics,
            evidence=timing_evidence,
            history=[0.5, 0.51, 0.505],
            plateau_info={"window": [0.5, 0.51, 0.505], "mean": 0.505, "range": 0.01},
        )
        prompt = specialist._render_prompt(context)
        assert "timing specialist" in prompt.lower()
        assert "CTS" in prompt
        assert "Setup WNS" in prompt or "WNS" in prompt

    def test_routability_prompt_renders(
        self,
        mock_llm: MockLLMProvider,
        config: AgenticLaneConfig,
        congestion_metrics: MetricsPayload,
        congestion_evidence: EvidencePack,
    ) -> None:
        specialist = RoutabilitySpecialist(llm_provider=mock_llm, config=config)
        context = specialist._build_context(
            stage="ROUTE_GLOBAL",
            metrics=congestion_metrics,
            evidence=congestion_evidence,
            history=[0.4, 0.42],
            plateau_info=None,
        )
        prompt = specialist._render_prompt(context)
        assert "routability specialist" in prompt.lower()
        assert "ROUTE_GLOBAL" in prompt

    def test_drc_prompt_renders(
        self,
        mock_llm: MockLLMProvider,
        config: AgenticLaneConfig,
        drc_metrics: MetricsPayload,
        drc_evidence: EvidencePack,
    ) -> None:
        specialist = DRCSpecialist(llm_provider=mock_llm, config=config)
        context = specialist._build_context(
            stage="SIGNOFF",
            metrics=drc_metrics,
            evidence=drc_evidence,
            history=[0.3, 0.31],
            plateau_info=None,
        )
        prompt = specialist._render_prompt(context)
        assert "drc specialist" in prompt.lower()
        assert "SIGNOFF" in prompt

    def test_fallback_template_used_for_unknown_type(
        self,
        mock_llm: MockLLMProvider,
        config: AgenticLaneConfig,
    ) -> None:
        """Verify base template is used when specialist template is missing."""

        class FakeSpecialist(BaseSpecialist):
            specialist_type = "nonexistent"  # type: ignore[assignment]

            def _get_domain_context(self, metrics: MetricsPayload, evidence: EvidencePack) -> dict:
                return {}

        specialist = FakeSpecialist(llm_provider=mock_llm, config=config)
        metrics = MetricsPayload(
            run_id="test", branch_id="B0", stage="SYNTH",
            attempt=1, execution_status="success",
        )
        evidence = EvidencePack(stage="SYNTH", attempt=1, execution_status="success")
        context = specialist._build_context(
            stage="SYNTH", metrics=metrics, evidence=evidence,
            history=[0.5], plateau_info=None,
        )
        prompt = specialist._render_prompt(context)
        # Should render from specialist_base.j2 fallback
        assert "specialist" in prompt.lower()
        assert "SYNTH" in prompt


# ------------------------------------------------------------------ #
# Orchestrator integration: _consult_specialists
# ------------------------------------------------------------------ #


class TestConsultSpecialists:
    """Tests for the _consult_specialists orchestrator helper."""

    async def test_consult_with_timing_metrics(
        self,
        mock_llm: MockLLMProvider,
        config: AgenticLaneConfig,
        timing_metrics: MetricsPayload,
        timing_evidence: EvidencePack,
    ) -> None:
        from agenticlane.orchestration.orchestrator import (
            _consult_specialists,
            _create_specialists,
        )

        advice = _make_advice("timing")
        mock_llm.set_response(advice)

        specialists = _create_specialists(mock_llm, config)
        results = await _consult_specialists(
            specialists=specialists,
            stage_name="CTS",
            metrics=timing_metrics,
            evidence=timing_evidence,
            scores=[0.5, 0.51, 0.505, 0.508, 0.507],
            plateau_info={"window": [0.505, 0.508, 0.507], "mean": 0.5067, "range": 0.003},
        )
        # At minimum the timing specialist should be consulted for CTS stage
        assert len(results) >= 1
        # All returned items should be SpecialistAdvice
        for r in results:
            assert isinstance(r, SpecialistAdvice)

    async def test_consult_returns_empty_on_none_metrics(
        self,
        mock_llm: MockLLMProvider,
        config: AgenticLaneConfig,
    ) -> None:
        from agenticlane.orchestration.orchestrator import (
            _consult_specialists,
            _create_specialists,
        )

        specialists = _create_specialists(mock_llm, config)
        results = await _consult_specialists(
            specialists=specialists,
            stage_name="CTS",
            metrics=None,
            evidence=None,
            scores=[0.5, 0.51],
            plateau_info=None,
        )
        assert results == []

    async def test_consult_handles_llm_failure_gracefully(
        self,
        mock_llm: MockLLMProvider,
        config: AgenticLaneConfig,
        timing_metrics: MetricsPayload,
        timing_evidence: EvidencePack,
    ) -> None:
        from agenticlane.orchestration.orchestrator import (
            _consult_specialists,
            _create_specialists,
        )

        mock_llm.set_failure(count=100)

        specialists = _create_specialists(mock_llm, config)
        results = await _consult_specialists(
            specialists=specialists,
            stage_name="CTS",
            metrics=timing_metrics,
            evidence=timing_evidence,
            scores=[0.5, 0.51, 0.505],
            plateau_info=None,
        )
        # Should return empty list when all specialists fail
        assert results == []


# ------------------------------------------------------------------ #
# KnobRecommendation schema tests
# ------------------------------------------------------------------ #


class TestKnobRecommendation:
    """Tests for the KnobRecommendation model."""

    def test_minimal(self) -> None:
        rec = KnobRecommendation(
            knob_name="PL_TARGET_DENSITY",
            recommended_value=0.55,
        )
        assert rec.knob_name == "PL_TARGET_DENSITY"
        assert rec.recommended_value == 0.55
        assert rec.rationale == ""

    def test_full(self) -> None:
        rec = KnobRecommendation(
            knob_name="FP_CORE_UTIL",
            current_value=60,
            recommended_value=45,
            rationale="Lower utilization to reduce congestion",
        )
        assert rec.current_value == 60
        assert rec.recommended_value == 45
        assert "congestion" in rec.rationale


# ------------------------------------------------------------------ #
# __init__ exports test
# ------------------------------------------------------------------ #


class TestSpecialistExports:
    """Tests for specialist module exports."""

    def test_exports_from_init(self) -> None:
        from agenticlane.agents import specialists

        assert hasattr(specialists, "BaseSpecialist")
        assert hasattr(specialists, "TimingSpecialist")
        assert hasattr(specialists, "RoutabilitySpecialist")
        assert hasattr(specialists, "DRCSpecialist")

    def test_schema_exports(self) -> None:
        from agenticlane.schemas import KnobRecommendation, SpecialistAdvice

        assert SpecialistAdvice is not None
        assert KnobRecommendation is not None
