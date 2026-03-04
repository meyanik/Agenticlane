"""Tests for the stage graph and knob registry.

Covers:
- Stage graph completeness and ordering
- Rollback edge correctness
- Knob registry key knobs and validation
- Type checking and range enforcement
- Stage-to-knob mappings
"""

from __future__ import annotations

import pytest

from agenticlane.config.knobs import (
    KNOB_REGISTRY,
    get_knob,
    get_knobs_for_stage,
    validate_knob_value,
)
from agenticlane.orchestration.graph import (
    ROLLBACK_EDGES,
    STAGE_GRAPH,
    STAGE_ORDER,
    StageSpec,
    get_rollback_targets,
    get_stage,
    get_stage_index,
)

# ═══════════════════════════════════════════════════════════════════════════
# Stage Graph Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestStageGraph:
    """Tests for STAGE_GRAPH, STAGE_ORDER, and helpers."""

    def test_stage_graph_has_10_stages(self) -> None:
        """The stage graph must contain exactly 10 stages."""
        assert len(STAGE_GRAPH) == 10

    def test_stage_order_is_correct(self) -> None:
        """STAGE_ORDER follows the canonical ASIC PnR flow."""
        expected = [
            "SYNTH",
            "FLOORPLAN",
            "PDN",
            "PLACE_GLOBAL",
            "PLACE_DETAILED",
            "CTS",
            "ROUTE_GLOBAL",
            "ROUTE_DETAILED",
            "FINISH",
            "SIGNOFF",
        ]
        assert expected == STAGE_ORDER

    def test_stage_order_matches_graph_keys(self) -> None:
        """Every entry in STAGE_ORDER must have a matching STAGE_GRAPH key."""
        assert set(STAGE_ORDER) == set(STAGE_GRAPH.keys())

    def test_every_stage_has_steps(self) -> None:
        """Every stage must have at least one LibreLane step."""
        for name, spec in STAGE_GRAPH.items():
            assert len(spec.librelane_steps) > 0, (
                f"Stage '{name}' has no LibreLane steps"
            )

    def test_every_stage_has_first_and_last_step(self) -> None:
        """first_step and last_step must be non-empty and present in the
        step list."""
        for name, spec in STAGE_GRAPH.items():
            assert spec.first_step, f"Stage '{name}' has empty first_step"
            assert spec.last_step, f"Stage '{name}' has empty last_step"
            assert spec.first_step == spec.librelane_steps[0], (
                f"Stage '{name}': first_step does not match first element"
            )
            assert spec.last_step == spec.librelane_steps[-1], (
                f"Stage '{name}': last_step does not match last element"
            )

    def test_every_stage_has_required_outputs(self) -> None:
        """Every stage must declare at least one required output."""
        for name, spec in STAGE_GRAPH.items():
            assert len(spec.required_outputs) > 0, (
                f"Stage '{name}' has no required outputs"
            )

    def test_rollback_path_from_route_detailed_to_floorplan(self) -> None:
        """ROUTE_DETAILED must be able to roll back to FLOORPLAN."""
        targets = get_rollback_targets("ROUTE_DETAILED")
        assert "FLOORPLAN" in targets
        assert "ROUTE_GLOBAL" in targets
        assert "PLACE_DETAILED" in targets

    def test_signoff_rollback_targets(self) -> None:
        """SIGNOFF must be able to roll back to ROUTE_DETAILED and FLOORPLAN."""
        targets = get_rollback_targets("SIGNOFF")
        assert "ROUTE_DETAILED" in targets
        assert "FLOORPLAN" in targets

    def test_cts_rollback_to_place_detailed(self) -> None:
        """CTS must be able to roll back to PLACE_DETAILED."""
        targets = get_rollback_targets("CTS")
        assert "PLACE_DETAILED" in targets

    def test_synth_has_no_rollback(self) -> None:
        """SYNTH (first stage) should have no rollback targets."""
        targets = get_rollback_targets("SYNTH")
        assert targets == []

    def test_rollback_edges_dict_matches_graph(self) -> None:
        """ROLLBACK_EDGES pre-computed dict must match the graph."""
        for name in STAGE_ORDER:
            assert ROLLBACK_EDGES[name] == STAGE_GRAPH[name].rollback_targets

    def test_get_stage_returns_correct_spec(self) -> None:
        """get_stage returns the correct StageSpec instance."""
        spec = get_stage("SYNTH")
        assert isinstance(spec, StageSpec)
        assert spec.name == "SYNTH"
        assert "Yosys.Synthesis" in spec.librelane_steps

    def test_get_stage_unknown_raises_key_error(self) -> None:
        """get_stage raises KeyError for unknown stage names."""
        with pytest.raises(KeyError, match="Unknown stage"):
            get_stage("NONEXISTENT")

    def test_get_stage_index_synth_is_zero(self) -> None:
        """SYNTH is the first stage (index 0)."""
        assert get_stage_index("SYNTH") == 0

    def test_get_stage_index_signoff_is_nine(self) -> None:
        """SIGNOFF is the last stage (index 9)."""
        assert get_stage_index("SIGNOFF") == 9

    def test_get_stage_index_unknown_raises_value_error(self) -> None:
        """get_stage_index raises ValueError for unknown stages."""
        with pytest.raises(ValueError, match="Unknown stage"):
            get_stage_index("INVALID_STAGE")

    def test_every_stage_has_relevant_metrics(self) -> None:
        """Every stage should have at least one relevant metric."""
        for name, spec in STAGE_GRAPH.items():
            assert len(spec.relevant_metrics) > 0, (
                f"Stage '{name}' has no relevant metrics"
            )

    def test_every_stage_has_typical_failures(self) -> None:
        """Every stage should have at least one typical failure mode."""
        for name, spec in STAGE_GRAPH.items():
            assert len(spec.typical_failures) > 0, (
                f"Stage '{name}' has no typical failures"
            )


# ═══════════════════════════════════════════════════════════════════════════
# Knob Registry Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestKnobRegistry:
    """Tests for KNOB_REGISTRY and helpers."""

    def test_knob_registry_has_key_knobs(self) -> None:
        """Registry must contain the core knobs."""
        key_knobs = [
            "FP_CORE_UTIL",
            "CLOCK_PERIOD",
            "SYNTH_STRATEGY",
            "PL_TARGET_DENSITY_PCT",
            "GRT_ADJUSTMENT",
            "DRT_OPT_ITERS",
            "CTS_CLK_MAX_WIRE_LENGTH",
        ]
        for knob_name in key_knobs:
            assert knob_name in KNOB_REGISTRY, (
                f"Key knob '{knob_name}' missing from registry"
            )

    def test_knob_range_validation_rejects_out_of_range(self) -> None:
        """Out-of-range values must raise ValueError."""
        # FP_CORE_UTIL range: 20-80
        with pytest.raises(ValueError, match="below minimum"):
            validate_knob_value("FP_CORE_UTIL", 10)
        with pytest.raises(ValueError, match="above maximum"):
            validate_knob_value("FP_CORE_UTIL", 90)

    def test_knob_range_validation_accepts_in_range(self) -> None:
        """Values within the valid range must not raise."""
        validate_knob_value("FP_CORE_UTIL", 50)
        validate_knob_value("FP_CORE_UTIL", 20)  # boundary
        validate_knob_value("FP_CORE_UTIL", 80)  # boundary

    def test_knob_type_validation(self) -> None:
        """Wrong types must raise TypeError."""
        # FP_CORE_UTIL expects int
        with pytest.raises(TypeError, match="expects int"):
            validate_knob_value("FP_CORE_UTIL", "fifty")
        # SYNTH_BUFFERING expects bool
        with pytest.raises(TypeError, match="expects bool"):
            validate_knob_value("SYNTH_BUFFERING", 1)
        # GRT_ADJUSTMENT expects float -- string should fail
        with pytest.raises(TypeError):
            validate_knob_value("GRT_ADJUSTMENT", "high")

    def test_knob_type_validation_float_accepts_int(self) -> None:
        """Float knobs should accept integer values (Python numeric coercion)."""
        # GRT_ADJUSTMENT is float, accepts int
        validate_knob_value("GRT_ADJUSTMENT", 0)
        validate_knob_value("FP_ASPECT_RATIO", 1)

    def test_knob_string_enum_validation(self) -> None:
        """String enum knobs reject invalid string values."""
        with pytest.raises(ValueError, match="not one of the allowed values"):
            validate_knob_value("SYNTH_STRATEGY", "SPEED")
        # Valid values should pass
        validate_knob_value("SYNTH_STRATEGY", "AREA")
        validate_knob_value("SYNTH_STRATEGY", "DELAY")

    def test_get_knobs_for_stage_returns_correct_knobs(self) -> None:
        """get_knobs_for_stage returns all knobs applicable to a stage."""
        synth_knobs = get_knobs_for_stage("SYNTH")
        synth_names = {k.name for k in synth_knobs}
        assert "SYNTH_STRATEGY" in synth_names
        assert "SYNTH_MAX_FANOUT" in synth_names
        assert "SYNTH_BUFFERING" in synth_names
        assert "SYNTH_SIZING" in synth_names
        # SYNTH knobs should NOT include floorplan knobs
        assert "FP_CORE_UTIL" not in synth_names

    def test_get_knobs_for_stage_floorplan(self) -> None:
        """Floorplan stage returns floorplan knobs and CLOCK_PERIOD."""
        fp_knobs = get_knobs_for_stage("FLOORPLAN")
        fp_names = {k.name for k in fp_knobs}
        assert "FP_CORE_UTIL" in fp_names
        assert "FP_ASPECT_RATIO" in fp_names
        assert "FP_SIZING" in fp_names
        assert "CLOCK_PERIOD" in fp_names  # constraint applies to all PnR

    def test_get_knobs_for_stage_routing(self) -> None:
        """Routing stages return the correct routing knobs."""
        grt_knobs = get_knobs_for_stage("ROUTE_GLOBAL")
        grt_names = {k.name for k in grt_knobs}
        assert "GRT_ADJUSTMENT" in grt_names
        assert "GRT_OVERFLOW_ITERS" in grt_names
        assert "CLOCK_PERIOD" in grt_names

        drt_knobs = get_knobs_for_stage("ROUTE_DETAILED")
        drt_names = {k.name for k in drt_knobs}
        assert "DRT_OPT_ITERS" in drt_names
        assert "CLOCK_PERIOD" in drt_names

    def test_clock_period_is_constraint_knob(self) -> None:
        """CLOCK_PERIOD must be marked as constraint, locked, and cheat_risk."""
        cp = get_knob("CLOCK_PERIOD")
        assert cp.is_constraint is True
        assert cp.locked_by_default is True
        assert cp.cheat_risk is True
        assert cp.safety_tier == "expert"

    def test_clock_period_applies_to_all_pnr_stages(self) -> None:
        """CLOCK_PERIOD should be applicable to all PnR stages."""
        cp = get_knob("CLOCK_PERIOD")
        expected_stages = [
            "FLOORPLAN", "PDN", "PLACE_GLOBAL", "PLACE_DETAILED",
            "CTS", "ROUTE_GLOBAL", "ROUTE_DETAILED", "FINISH", "SIGNOFF",
        ]
        for stage in expected_stages:
            assert stage in cp.stage_applicability, (
                f"CLOCK_PERIOD missing stage_applicability for '{stage}'"
            )
        # Should NOT include SYNTH
        assert "SYNTH" not in cp.stage_applicability

    def test_fp_core_util_pdk_override(self) -> None:
        """FP_CORE_UTIL should have a sky130A PDK override."""
        knob = get_knob("FP_CORE_UTIL")
        assert "sky130A" in knob.pdk_overrides
        assert knob.pdk_overrides["sky130A"]["default"] == 45

    def test_get_knob_unknown_raises_key_error(self) -> None:
        """get_knob raises KeyError for unknown knob names."""
        with pytest.raises(KeyError, match="Unknown knob"):
            get_knob("NONEXISTENT_KNOB")

    def test_all_knobs_have_stage_applicability(self) -> None:
        """Every knob must declare at least one applicable stage."""
        for name, spec in KNOB_REGISTRY.items():
            assert len(spec.stage_applicability) > 0, (
                f"Knob '{name}' has no stage_applicability"
            )

    def test_all_knob_stages_are_valid(self) -> None:
        """Every stage referenced in knob stage_applicability must exist."""
        for name, spec in KNOB_REGISTRY.items():
            for stage in spec.stage_applicability:
                assert stage in STAGE_GRAPH, (
                    f"Knob '{name}' references unknown stage '{stage}'"
                )
