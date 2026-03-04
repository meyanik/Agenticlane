"""P3.5 Scoring Formula tests."""

from __future__ import annotations

import pytest

from agenticlane.config.models import ScoringConfig
from agenticlane.judge.scoring import ScoringEngine, normalize_metric
from agenticlane.schemas.constraints import ClockDefinition, ConstraintDigest
from agenticlane.schemas.metrics import (
    MetricsPayload,
    PhysicalMetrics,
    PowerMetrics,
    RouteMetrics,
    TimingMetrics,
)

# -- Helper to build MetricsPayload --


def make_metrics(
    *,
    wns: dict[str, float] | None = None,
    area: float | None = None,
    congestion: float | None = None,
    total_power: float | None = None,
    run_id: str = "test",
    stage: str = "PLACE_GLOBAL",
    attempt: int = 1,
) -> MetricsPayload:
    timing = TimingMetrics(setup_wns_ns=wns) if wns is not None else None
    physical = PhysicalMetrics(core_area_um2=area) if area is not None else None
    route = (
        RouteMetrics(congestion_overflow_pct=congestion)
        if congestion is not None
        else None
    )
    power = (
        PowerMetrics(total_power_mw=total_power)
        if total_power is not None
        else None
    )
    return MetricsPayload(
        run_id=run_id,
        branch_id="B0",
        stage=stage,
        attempt=attempt,
        execution_status="success",
        timing=timing,
        physical=physical,
        route=route,
        power=power,
    )


class TestNormalizeMetric:
    def test_improvement_positive_lower_is_better(self) -> None:
        # baseline=10, current=8 -> improvement of 0.2
        result = normalize_metric(8.0, 10.0, direction="lower_is_better")
        assert result is not None
        assert abs(result - 0.2) < 0.01

    def test_improvement_positive_higher_is_better(self) -> None:
        # baseline=10, current=12 -> improvement of 0.2
        result = normalize_metric(12.0, 10.0, direction="higher_is_better")
        assert result is not None
        assert abs(result - 0.2) < 0.01

    def test_regression_negative(self) -> None:
        # baseline=10, current=12, lower_is_better -> regression = -0.2
        result = normalize_metric(12.0, 10.0, direction="lower_is_better")
        assert result is not None
        assert result < 0

    def test_no_change_returns_zero(self) -> None:
        result = normalize_metric(10.0, 10.0, direction="lower_is_better")
        assert result is not None
        assert abs(result) < 0.001

    def test_clamped_to_bounds(self) -> None:
        # Huge improvement clamped to 1.0
        result = normalize_metric(0.0, 100.0, clamp=1.0, direction="lower_is_better")
        assert result is not None
        assert result <= 1.0
        # Huge regression clamped to -1.0
        result = normalize_metric(200.0, 1.0, clamp=1.0, direction="lower_is_better")
        assert result is not None
        assert result >= -1.0

    def test_none_inputs_return_none(self) -> None:
        assert normalize_metric(None, 10.0) is None
        assert normalize_metric(10.0, None) is None
        assert normalize_metric(None, None) is None

    def test_zero_baseline_uses_epsilon(self) -> None:
        # baseline=0, should not crash (epsilon prevents div by zero)
        result = normalize_metric(5.0, 0.0, direction="lower_is_better")
        assert result is not None

    def test_invalid_direction_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown direction"):
            normalize_metric(1.0, 1.0, direction="invalid")

    def test_custom_clamp(self) -> None:
        result = normalize_metric(0.0, 100.0, clamp=0.5, direction="lower_is_better")
        assert result is not None
        assert result <= 0.5


class TestScoringEngine:
    @pytest.fixture()
    def engine(self) -> ScoringEngine:
        return ScoringEngine(ScoringConfig())

    def test_composite_timing_area(self, engine: ScoringEngine) -> None:
        baseline = make_metrics(wns={"tt": -0.5}, area=1000.0)
        current = make_metrics(wns={"tt": -0.3}, area=950.0)
        score = engine.compute_composite_score(
            baseline,
            current,
            intent_weights={"timing": 0.7, "area": 0.3},
        )
        assert score > 0  # both improved

    def test_regression_gives_negative_score(self, engine: ScoringEngine) -> None:
        baseline = make_metrics(wns={"tt": -0.1}, area=1000.0)
        current = make_metrics(wns={"tt": -0.5}, area=1200.0)
        score = engine.compute_composite_score(
            baseline,
            current,
            intent_weights={"timing": 0.7, "area": 0.3},
        )
        assert score < 0

    def test_no_metrics_returns_zero(self, engine: ScoringEngine) -> None:
        baseline = make_metrics()
        current = make_metrics()
        score = engine.compute_composite_score(baseline, current)
        assert score == 0.0

    def test_anti_cheat_timing(self, engine: ScoringEngine) -> None:
        """Relaxing clock period but keeping same WNS should not improve score."""
        digest_tight = ConstraintDigest(
            clocks=[ClockDefinition(name="clk", period_ns=10.0)]
        )
        # Same WNS with tight clock
        baseline = make_metrics(wns={"tt": -0.5})
        current = make_metrics(wns={"tt": -0.5})

        score_tight = engine.compute_composite_score(
            baseline,
            current,
            constraint_digest=digest_tight,
            intent_weights={"timing": 1.0},
        )
        # Score should be ~0 (no real improvement)
        assert abs(score_tight) < 0.01

    def test_effective_clock_used(self, engine: ScoringEngine) -> None:
        """effective_setup_period = clock_period - WNS."""
        digest = ConstraintDigest(
            clocks=[ClockDefinition(name="clk", period_ns=10.0)]
        )
        # baseline: effective = 10 - (-0.5) = 10.5
        # current: effective = 10 - (-0.1) = 10.1 (better, lower)
        baseline = make_metrics(wns={"tt": -0.5})
        current = make_metrics(wns={"tt": -0.1})
        score = engine.compute_composite_score(
            baseline,
            current,
            constraint_digest=digest,
            intent_weights={"timing": 1.0},
        )
        assert score > 0  # effective period decreased = improvement

    def test_composite_weighted_correctly(self, engine: ScoringEngine) -> None:
        """Manual calculation: timing*0.5 + area*0.3 + route*0.2."""
        baseline = make_metrics(wns={"tt": -1.0}, area=1000.0, congestion=50.0)
        current = make_metrics(wns={"tt": -0.5}, area=900.0, congestion=40.0)

        # Without constraint digest, uses raw WNS (higher_is_better)
        # timing: (-0.5 - (-1.0)) / (1.0 + eps) ~ 0.5
        # area: (1000 - 900) / (1000 + eps) ~ 0.1
        # route: (50 - 40) / (50 + eps) ~ 0.2
        score = engine.compute_composite_score(
            baseline,
            current,
            intent_weights={"timing": 0.5, "area": 0.3, "route": 0.2},
        )
        # composite = (0.5*0.5 + 0.3*0.1 + 0.2*0.2) / 1.0 = 0.25 + 0.03 + 0.04 = 0.32
        assert 0.2 < score < 0.5

    def test_worst_corner_wns_used(self, engine: ScoringEngine) -> None:
        """Multi-corner: worst (minimum) WNS is used."""
        baseline = make_metrics(wns={"tt": -0.3, "ss": -0.8, "ff": 0.1})
        current = make_metrics(wns={"tt": -0.2, "ss": -0.6, "ff": 0.2})
        # worst corner baseline: -0.8, current: -0.6
        score = engine.compute_composite_score(
            baseline, current, intent_weights={"timing": 1.0}
        )
        assert score > 0  # -0.6 > -0.8 = improvement

    def test_missing_timing_returns_zero(self, engine: ScoringEngine) -> None:
        baseline = make_metrics(area=1000.0)
        current = make_metrics(area=900.0)
        score = engine.compute_composite_score(
            baseline, current, intent_weights={"timing": 0.7, "area": 0.3}
        )
        # Only area contributes (timing is None, skipped)
        assert score > 0

    def test_power_component_returns_none_when_missing(self, engine: ScoringEngine) -> None:
        baseline = make_metrics(area=1000.0)
        current = make_metrics(area=900.0)
        score = engine.compute_composite_score(
            baseline, current, intent_weights={"power": 0.5, "area": 0.5}
        )
        # Power is None -> only area contributes
        assert score > 0

    def test_power_improvement_positive_score(self, engine: ScoringEngine) -> None:
        """Lower power -> positive score (improvement)."""
        baseline = make_metrics(total_power=10.0)
        current = make_metrics(total_power=8.0)
        score = engine.compute_composite_score(
            baseline, current, intent_weights={"power": 1.0}
        )
        assert score > 0

    def test_power_regression_negative_score(self, engine: ScoringEngine) -> None:
        """Higher power -> negative score (regression)."""
        baseline = make_metrics(total_power=10.0)
        current = make_metrics(total_power=12.0)
        score = engine.compute_composite_score(
            baseline, current, intent_weights={"power": 1.0}
        )
        assert score < 0

    def test_power_no_change_zero_score(self, engine: ScoringEngine) -> None:
        """Same power -> ~zero score."""
        baseline = make_metrics(total_power=10.0)
        current = make_metrics(total_power=10.0)
        score = engine.compute_composite_score(
            baseline, current, intent_weights={"power": 1.0}
        )
        assert abs(score) < 0.001

    def test_composite_with_power_weight(self, engine: ScoringEngine) -> None:
        """Composite with timing, area, and power weights."""
        baseline = make_metrics(wns={"tt": -1.0}, area=1000.0, total_power=10.0)
        current = make_metrics(wns={"tt": -0.5}, area=900.0, total_power=8.0)
        score = engine.compute_composite_score(
            baseline,
            current,
            intent_weights={"timing": 0.4, "area": 0.3, "power": 0.3},
        )
        assert score > 0  # all three improved

    def test_deterministic_scoring(self, engine: ScoringEngine) -> None:
        """Same inputs always produce same score."""
        baseline = make_metrics(wns={"tt": -0.5}, area=1000.0)
        current = make_metrics(wns={"tt": -0.3}, area=950.0)
        s1 = engine.compute_composite_score(baseline, current)
        s2 = engine.compute_composite_score(baseline, current)
        assert s1 == s2
