"""Tests for agent-driven physical parameters and flow mode features.

Covers:
- flow_mode config validation
- DIE_AREA knob registration and validation
- SynthesisMetrics schema
- SynthExtractor parsing
- refine_after_synth() calculation
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from agenticlane.config.knobs import (
    KNOB_REGISTRY,
    get_knob,
    get_knobs_for_stage,
    validate_knob_value,
)
from agenticlane.config.models import AgenticLaneConfig, DesignConfig
from agenticlane.distill.extractors.synth import SynthExtractor
from agenticlane.orchestration.manifest import ManifestBuilder, RunManifest
from agenticlane.orchestration.zero_shot import ZeroShotInitializer
from agenticlane.schemas.metrics import MetricsPayload, SynthesisMetrics

# ===================================================================
# Feature 1: flow_mode config
# ===================================================================


class TestFlowModeConfig:
    """Test flow_mode field on DesignConfig."""

    def test_default_is_auto(self) -> None:
        cfg = DesignConfig()
        assert cfg.flow_mode == "auto"

    def test_flat(self) -> None:
        cfg = DesignConfig(flow_mode="flat")
        assert cfg.flow_mode == "flat"

    def test_hierarchical(self) -> None:
        from agenticlane.config.models import ModuleConfig

        cfg = DesignConfig(
            flow_mode="hierarchical",
            modules={"mod1": ModuleConfig(librelane_config_path="./mod1/config.yaml")},
        )
        assert cfg.flow_mode == "hierarchical"

    def test_invalid_flow_mode(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            DesignConfig(flow_mode="invalid")  # type: ignore[arg-type]

    def test_flow_mode_in_full_config(self) -> None:
        cfg = AgenticLaneConfig(design={"flow_mode": "flat"})  # type: ignore[arg-type]
        assert cfg.design.flow_mode == "flat"

    def test_flow_mode_serialization(self) -> None:
        from agenticlane.config.models import ModuleConfig

        cfg = DesignConfig(
            flow_mode="hierarchical",
            modules={"mod1": ModuleConfig(librelane_config_path="./mod1/config.yaml")},
        )
        dumped = cfg.model_dump()
        assert dumped["flow_mode"] == "hierarchical"


# ===================================================================
# Feature 1: flow_mode in manifest
# ===================================================================


class TestManifestFlowMode:
    """Test flow_mode recording in manifest."""

    def test_default_flow_mode(self) -> None:
        m = RunManifest(run_id="test")
        assert m.flow_mode == "flat"

    def test_set_flow_mode(self) -> None:
        builder = ManifestBuilder(run_id="test")
        builder.set_flow_mode("hierarchical")
        assert builder.manifest.flow_mode == "hierarchical"

    def test_flow_mode_in_finalized(self) -> None:
        builder = ManifestBuilder(run_id="test")
        builder.set_flow_mode("flat")
        manifest = builder.finalize()
        assert manifest.flow_mode == "flat"


# ===================================================================
# Feature 2: DIE_AREA knob
# ===================================================================


class TestDieAreaKnob:
    """Test DIE_AREA knob registration and validation."""

    def test_die_area_registered(self) -> None:
        assert "DIE_AREA" in KNOB_REGISTRY
        spec = get_knob("DIE_AREA")
        assert spec.dtype is list
        assert spec.safety_tier == "safe"
        assert "FLOORPLAN" in spec.stage_applicability

    def test_die_area_in_floorplan_knobs(self) -> None:
        knobs = get_knobs_for_stage("FLOORPLAN")
        names = [k.name for k in knobs]
        assert "DIE_AREA" in names

    def test_validate_valid_die_area(self) -> None:
        validate_knob_value("DIE_AREA", [0, 0, 600, 600])

    def test_validate_valid_die_area_floats(self) -> None:
        validate_knob_value("DIE_AREA", [0.0, 0.0, 600.5, 600.5])

    def test_validate_die_area_wrong_type(self) -> None:
        with pytest.raises(TypeError, match="expects list"):
            validate_knob_value("DIE_AREA", "0 0 600 600")

    def test_validate_die_area_wrong_length(self) -> None:
        with pytest.raises(ValueError, match="4 numbers"):
            validate_knob_value("DIE_AREA", [0, 0, 600])

    def test_validate_die_area_wrong_element_type(self) -> None:
        with pytest.raises(TypeError, match="element .* must be a number"):
            validate_knob_value("DIE_AREA", [0, 0, "600", 600])

    def test_validate_die_area_five_elements(self) -> None:
        with pytest.raises(ValueError, match="4 numbers"):
            validate_knob_value("DIE_AREA", [0, 0, 600, 600, 0])


# ===================================================================
# Feature 2: SynthesisMetrics
# ===================================================================


class TestSynthesisMetrics:
    """Test SynthesisMetrics schema."""

    def test_all_none_defaults(self) -> None:
        m = SynthesisMetrics()
        assert m.cell_count is None
        assert m.net_count is None
        assert m.area_estimate_um2 is None

    def test_with_values(self) -> None:
        m = SynthesisMetrics(cell_count=43000, net_count=12000, area_estimate_um2=55000.5)
        assert m.cell_count == 43000
        assert m.net_count == 12000
        assert m.area_estimate_um2 == 55000.5

    def test_metrics_payload_synthesis_field(self) -> None:
        mp = MetricsPayload(
            run_id="r1",
            branch_id="B0",
            stage="SYNTH",
            attempt=1,
            execution_status="success",
            synthesis=SynthesisMetrics(cell_count=100),
        )
        assert mp.synthesis is not None
        assert mp.synthesis.cell_count == 100

    def test_metrics_payload_synthesis_default_none(self) -> None:
        mp = MetricsPayload(
            run_id="r1",
            branch_id="B0",
            stage="SYNTH",
            attempt=1,
            execution_status="success",
        )
        assert mp.synthesis is None


# ===================================================================
# Feature 2: SynthExtractor
# ===================================================================


SAMPLE_YOSYS_LOG = """\
=== counter ===

   Number of wires:                456
   Number of wire bits:            789
   Number of public wires:         123
   Number of public wire bits:     234
   Number of cells:              43215
   Number of memories:               0

   Chip area for module '\\counter': 559430.123400

"""

SAMPLE_YOSYS_LOG_TOPLEVEL = """\
   Number of cells:              1234
   Number of wires:               567

   Chip area for top-level module '\\top': 12345.678900
"""


class TestSynthExtractor:
    """Test SynthExtractor parsing."""

    def test_extract_from_yosys_log(self, tmp_path: Path) -> None:
        attempt_dir = tmp_path / "attempt_1"
        log_dir = attempt_dir / "01-yosys-synthesis"
        log_dir.mkdir(parents=True)
        (log_dir / "yosys-synthesis.log").write_text(SAMPLE_YOSYS_LOG)

        ext = SynthExtractor()
        result = ext.extract(attempt_dir, "SYNTH")

        assert result["cell_count"] == 43215
        assert result["net_count"] == 456
        assert result["area_estimate_um2"] == pytest.approx(559430.1234)

    def test_extract_toplevel_module(self, tmp_path: Path) -> None:
        attempt_dir = tmp_path / "attempt_1"
        (attempt_dir / "artifacts").mkdir(parents=True)
        (attempt_dir / "artifacts" / "synth.log").write_text(SAMPLE_YOSYS_LOG_TOPLEVEL)

        ext = SynthExtractor()
        result = ext.extract(attempt_dir, "SYNTH")

        assert result["cell_count"] == 1234
        assert result["net_count"] == 567
        assert result["area_estimate_um2"] == pytest.approx(12345.6789)

    def test_extract_no_log(self, tmp_path: Path) -> None:
        attempt_dir = tmp_path / "empty"
        attempt_dir.mkdir()

        ext = SynthExtractor()
        result = ext.extract(attempt_dir, "SYNTH")

        assert result["cell_count"] is None
        assert result["net_count"] is None
        assert result["area_estimate_um2"] is None

    def test_extract_partial_log(self, tmp_path: Path) -> None:
        attempt_dir = tmp_path / "attempt_1"
        attempt_dir.mkdir()
        (attempt_dir / "flow.log").write_text(
            "Some log\n   Number of cells:              500\nDone\n"
        )

        ext = SynthExtractor()
        result = ext.extract(attempt_dir, "SYNTH")

        assert result["cell_count"] == 500
        assert result["net_count"] is None
        assert result["area_estimate_um2"] is None

    def test_extractor_name(self) -> None:
        ext = SynthExtractor()
        assert ext.name == "synth"


# ===================================================================
# Feature 2: refine_after_synth
# ===================================================================


class TestRefineAfterSynth:
    """Test ZeroShotInitializer.refine_after_synth()."""

    def test_basic_auto_sizing(self) -> None:
        metrics = SynthesisMetrics(cell_count=1000)
        patch = ZeroShotInitializer.refine_after_synth(
            synth_metrics=metrics,
            intent={"optimize_for": "balanced"},
            pdk="sky130A",
        )
        assert patch.patch_id == "post_synth_refinement"
        assert patch.stage == "FLOORPLAN"
        assert "config_vars" in patch.types

        cv = patch.config_vars
        assert cv["FP_SIZING"] == "absolute"
        assert cv["FP_CORE_UTIL"] == 45
        assert isinstance(cv["DIE_AREA"], list)
        assert len(cv["DIE_AREA"]) == 4

        # Verify the calculation: 1000 cells * 13 um2 / 0.45 util = ~28889 um2
        # sqrt(28889) * 1.2 = ~203.8 -> int = 203
        expected_area = 1000 * 13.0 / 0.45
        expected_side = int(math.sqrt(expected_area) * 1.20)
        assert cv["DIE_AREA"][2] == expected_side
        assert cv["DIE_AREA"][3] == expected_side

    def test_timing_optimization_lower_util(self) -> None:
        metrics = SynthesisMetrics(cell_count=5000)
        patch = ZeroShotInitializer.refine_after_synth(
            synth_metrics=metrics,
            intent={"optimize_for": "timing"},
            pdk="sky130A",
        )
        assert patch.config_vars["FP_CORE_UTIL"] == 35

    def test_area_optimization_higher_util(self) -> None:
        metrics = SynthesisMetrics(cell_count=5000)
        patch = ZeroShotInitializer.refine_after_synth(
            synth_metrics=metrics,
            intent={"optimize_for": "area"},
            pdk="sky130A",
        )
        assert patch.config_vars["FP_CORE_UTIL"] == 60

    def test_zero_cells_no_config_vars(self) -> None:
        metrics = SynthesisMetrics(cell_count=0)
        patch = ZeroShotInitializer.refine_after_synth(
            synth_metrics=metrics,
            intent={"optimize_for": "balanced"},
        )
        # cell_count=0 is falsy, so no config_vars
        assert patch.config_vars == {}
        assert patch.types == []

    def test_none_cells_no_config_vars(self) -> None:
        metrics = SynthesisMetrics(cell_count=None)
        patch = ZeroShotInitializer.refine_after_synth(
            synth_metrics=metrics,
            intent={"optimize_for": "balanced"},
        )
        assert patch.config_vars == {}

    def test_minimum_die_size(self) -> None:
        # Very small design: 1 cell -> should be at minimum 100um
        metrics = SynthesisMetrics(cell_count=1)
        patch = ZeroShotInitializer.refine_after_synth(
            synth_metrics=metrics,
            intent={"optimize_for": "balanced"},
            pdk="sky130A",
        )
        assert patch.config_vars["DIE_AREA"][2] >= 100
        assert patch.config_vars["DIE_AREA"][3] >= 100

    def test_pl_target_density_capped(self) -> None:
        metrics = SynthesisMetrics(cell_count=5000)
        patch = ZeroShotInitializer.refine_after_synth(
            synth_metrics=metrics,
            intent={"optimize_for": "area"},  # util=60
            pdk="sky130A",
        )
        # PL_TARGET_DENSITY_PCT = min(60 + 10, 80) = 70
        assert patch.config_vars["PL_TARGET_DENSITY_PCT"] == 70

    def test_different_pdk(self) -> None:
        metrics = SynthesisMetrics(cell_count=1000)
        patch = ZeroShotInitializer.refine_after_synth(
            synth_metrics=metrics,
            intent={"optimize_for": "balanced"},
            pdk="gf180mcuD",
        )
        # gf180 has larger cells (20 um2 vs 13 um2), so die should be bigger
        cv = patch.config_vars
        expected_area = 1000 * 20.0 / 0.45
        expected_side = int(math.sqrt(expected_area) * 1.20)
        assert cv["DIE_AREA"][2] == expected_side

    def test_rationale_includes_cell_count(self) -> None:
        metrics = SynthesisMetrics(cell_count=43000)
        patch = ZeroShotInitializer.refine_after_synth(
            synth_metrics=metrics,
            intent={"optimize_for": "balanced"},
        )
        assert "43000" in patch.rationale
