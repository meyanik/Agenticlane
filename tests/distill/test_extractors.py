"""Tests for individual distillation extractors.

Tests each extractor independently against synthetic and golden report
files, verifying correct metric extraction and robustness to missing
or malformed input.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from agenticlane.distill.extractors.area import AreaExtractor
from agenticlane.distill.extractors.constraints import ConstraintExtractor
from agenticlane.distill.extractors.crash import CrashExtractor
from agenticlane.distill.extractors.drc import DRCExtractor
from agenticlane.distill.extractors.lvs import LVSExtractor
from agenticlane.distill.extractors.power import PowerExtractor
from agenticlane.distill.extractors.route import RouteExtractor
from agenticlane.distill.extractors.runtime import RuntimeExtractor
from agenticlane.distill.extractors.spatial import SpatialExtractor
from agenticlane.distill.extractors.timing import TimingExtractor
from agenticlane.distill.registry import (
    get_all_extractors,
    get_extractor,
    list_extractor_names,
    register,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

GOLDEN_DIR = Path(__file__).parent.parent / "golden" / "reports"


def _make_attempt_dir(tmp_path: Path, *, stage: str = "synth") -> Path:
    """Create a minimal attempt directory structure."""
    attempt_dir = tmp_path / "attempt_001"
    artifacts = attempt_dir / "artifacts"
    artifacts.mkdir(parents=True)
    return attempt_dir


def _write_timing_report(artifacts: Path, wns: float = -0.15) -> None:
    """Write a synthetic timing report."""
    (artifacts / "timing.rpt").write_text(
        f"wns {wns:.4f}\n"
        f"tns {wns * 10:.4f}\n"
        f"Clock clk Period: 10.000\n"
        f"  Setup WNS: {wns:.4f} ns\n"
        f"  Setup TNS: {wns * 10:.4f} ns\n"
    )


def _write_area_report(
    artifacts: Path, area: float = 500000.0, util: float = 45.0
) -> None:
    """Write a synthetic area report."""
    (artifacts / "area.rpt").write_text(
        f"Design area {area:.2f} u^2\n"
        f"Core utilization: {util:.2f}%\n"
        f"  Core area: {area:.2f} um^2\n"
        f"  Utilization: {util:.2f}%\n"
    )


def _write_congestion_report(artifacts: Path, overflow: float = 2.0) -> None:
    """Write a synthetic congestion report."""
    (artifacts / "congestion.rpt").write_text(f"Overflow: {overflow:.4f}%\n")


def _write_state_out(
    attempt_dir: Path,
    *,
    status: str = "success",
    metrics: dict | None = None,
) -> None:
    """Write a synthetic state_out.json."""
    data = {
        "stage": "synth",
        "status": status,
        "metrics_snapshot": metrics or {},
    }
    (attempt_dir / "state_out.json").write_text(json.dumps(data))


# ---------------------------------------------------------------------------
# TimingExtractor
# ---------------------------------------------------------------------------


class TestTimingExtractor:
    def test_extracts_wns_and_tns(self, tmp_path: Path) -> None:
        attempt = _make_attempt_dir(tmp_path)
        _write_timing_report(attempt / "artifacts", wns=-0.20)

        ext = TimingExtractor()
        result = ext.extract(attempt, "synth")

        assert result["setup_wns_ns"]["default"] == pytest.approx(-0.20)
        assert result["tns_ns"] == pytest.approx(-2.0)
        assert result["clock_period_ns"] == pytest.approx(10.0)

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        attempt = _make_attempt_dir(tmp_path)
        ext = TimingExtractor()
        result = ext.extract(attempt, "synth")

        assert result["setup_wns_ns"] == {}
        assert result["tns_ns"] is None
        assert result["clock_period_ns"] is None

    def test_golden_timing_report(self) -> None:
        """Known golden report produces exact expected metrics."""
        # Set up attempt dir structure pointing to golden data
        ext = TimingExtractor()
        # Create a temp structure with golden report
        golden = GOLDEN_DIR / "timing.rpt"
        assert golden.is_file(), f"Golden file missing: {golden}"

        # We need attempt_dir/artifacts/timing.rpt
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            attempt = Path(td)
            arts = attempt / "artifacts"
            arts.mkdir()
            shutil.copy(golden, arts / "timing.rpt")

            result = ext.extract(attempt, "synth")

        assert result["setup_wns_ns"]["default"] == pytest.approx(-0.15)
        assert result["tns_ns"] == pytest.approx(-1.5)
        assert result["clock_period_ns"] == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# AreaExtractor
# ---------------------------------------------------------------------------


class TestAreaExtractor:
    def test_extracts_area_and_utilization(self, tmp_path: Path) -> None:
        attempt = _make_attempt_dir(tmp_path)
        _write_area_report(attempt / "artifacts", area=600000.0, util=50.0)

        ext = AreaExtractor()
        result = ext.extract(attempt, "synth")

        assert result["core_area_um2"] == pytest.approx(600000.0)
        assert result["utilization_pct"] == pytest.approx(50.0)

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        attempt = _make_attempt_dir(tmp_path)
        ext = AreaExtractor()
        result = ext.extract(attempt, "synth")

        assert result["core_area_um2"] is None
        assert result["utilization_pct"] is None

    def test_golden_area_report(self) -> None:
        """Known golden report produces exact expected metrics."""
        ext = AreaExtractor()
        golden = GOLDEN_DIR / "area.rpt"
        assert golden.is_file()

        import tempfile

        with tempfile.TemporaryDirectory() as td:
            attempt = Path(td)
            arts = attempt / "artifacts"
            arts.mkdir()
            shutil.copy(golden, arts / "area.rpt")

            result = ext.extract(attempt, "synth")

        assert result["core_area_um2"] == pytest.approx(500000.0)
        assert result["utilization_pct"] == pytest.approx(45.0)


# ---------------------------------------------------------------------------
# RouteExtractor
# ---------------------------------------------------------------------------


class TestRouteExtractor:
    def test_extracts_congestion(self, tmp_path: Path) -> None:
        attempt = _make_attempt_dir(tmp_path)
        _write_congestion_report(attempt / "artifacts", overflow=3.5)

        ext = RouteExtractor()
        result = ext.extract(attempt, "route_global")

        assert result["congestion_overflow_pct"] == pytest.approx(3.5)

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        attempt = _make_attempt_dir(tmp_path)
        ext = RouteExtractor()
        result = ext.extract(attempt, "route_global")

        assert result["congestion_overflow_pct"] is None


# ---------------------------------------------------------------------------
# DRCExtractor
# ---------------------------------------------------------------------------


class TestDRCExtractor:
    def test_extracts_from_drc_report(self, tmp_path: Path) -> None:
        attempt = _make_attempt_dir(tmp_path)
        (attempt / "artifacts" / "drc.rpt").write_text(
            "DRC Report\nTotal violations: 5\n"
            "Type: Metal1.MinSpacing\nType: Via1.Enclosure\n"
        )

        ext = DRCExtractor()
        result = ext.extract(attempt, "signoff")

        assert result["drc_count"] == 5
        assert "Metal1.MinSpacing" in result["drc_types"]
        assert "Via1.Enclosure" in result["drc_types"]

    def test_extracts_from_state_out(self, tmp_path: Path) -> None:
        attempt = _make_attempt_dir(tmp_path)
        _write_state_out(attempt, metrics={"drc_count": 3})

        ext = DRCExtractor()
        result = ext.extract(attempt, "signoff")

        assert result["drc_count"] == 3

    def test_missing_files_returns_none(self, tmp_path: Path) -> None:
        attempt = _make_attempt_dir(tmp_path)
        ext = DRCExtractor()
        result = ext.extract(attempt, "signoff")

        assert result["drc_count"] is None

    def test_golden_drc_report(self) -> None:
        """Golden DRC report produces exact expected counts."""
        ext = DRCExtractor()
        golden = GOLDEN_DIR / "drc.rpt"
        assert golden.is_file()

        import tempfile

        with tempfile.TemporaryDirectory() as td:
            attempt = Path(td)
            arts = attempt / "artifacts"
            arts.mkdir()
            shutil.copy(golden, arts / "drc.rpt")

            result = ext.extract(attempt, "signoff")

        assert result["drc_count"] == 3
        assert len(result["drc_types"]) == 3
        assert "Metal1.MinSpacing" in result["drc_types"]
        assert "Via1.Enclosure" in result["drc_types"]
        assert "Metal2.MinWidth" in result["drc_types"]


# ---------------------------------------------------------------------------
# LVSExtractor
# ---------------------------------------------------------------------------


class TestLVSExtractor:
    def test_pass_from_report(self, tmp_path: Path) -> None:
        attempt = _make_attempt_dir(tmp_path)
        (attempt / "artifacts" / "lvs.rpt").write_text("LVS clean\n")

        ext = LVSExtractor()
        result = ext.extract(attempt, "signoff")

        assert result["lvs_pass"] is True

    def test_fail_from_report(self, tmp_path: Path) -> None:
        attempt = _make_attempt_dir(tmp_path)
        (attempt / "artifacts" / "lvs.rpt").write_text("LVS failed: 3 mismatches\n")

        ext = LVSExtractor()
        result = ext.extract(attempt, "signoff")

        assert result["lvs_pass"] is False

    def test_derives_from_state_success(self, tmp_path: Path) -> None:
        attempt = _make_attempt_dir(tmp_path)
        _write_state_out(attempt, status="success")

        ext = LVSExtractor()
        result = ext.extract(attempt, "signoff")

        assert result["lvs_pass"] is True

    def test_derives_from_state_failure(self, tmp_path: Path) -> None:
        attempt = _make_attempt_dir(tmp_path)
        _write_state_out(attempt, status="failure")

        ext = LVSExtractor()
        result = ext.extract(attempt, "signoff")

        assert result["lvs_pass"] is False

    def test_missing_everything_returns_none(self, tmp_path: Path) -> None:
        attempt = _make_attempt_dir(tmp_path)
        ext = LVSExtractor()
        result = ext.extract(attempt, "signoff")

        assert result["lvs_pass"] is None


# ---------------------------------------------------------------------------
# PowerExtractor
# ---------------------------------------------------------------------------


class TestPowerExtractor:
    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        """Power extractor returns None for all metrics when no report exists."""
        attempt = _make_attempt_dir(tmp_path)
        ext = PowerExtractor()
        result = ext.extract(attempt, "signoff")

        assert result["total_power_mw"] is None
        assert result["internal_power_mw"] is None
        assert result["switching_power_mw"] is None
        assert result["leakage_power_mw"] is None
        assert result["leakage_pct"] is None

    def test_parses_simple_power_report(self, tmp_path: Path) -> None:
        attempt = _make_attempt_dir(tmp_path)
        (attempt / "artifacts" / "power.rpt").write_text(
            "Power Report\n"
            "Total Power: 12.5 mW\n"
            "Leakage: 15.3%\n"
        )

        ext = PowerExtractor()
        result = ext.extract(attempt, "signoff")

        assert result["total_power_mw"] == pytest.approx(12.5)
        assert result["leakage_pct"] == pytest.approx(15.3)

    def test_parses_openroad_4col_format(self, tmp_path: Path) -> None:
        """OpenROAD 4-column tabular format: internal, switching, leakage, total."""
        attempt = _make_attempt_dir(tmp_path)
        (attempt / "artifacts" / "power.rpt").write_text(
            "Group    Internal  Switching  Leakage    Total\n"
            "Total    5.00e-03  3.00e-03   2.00e-03   1.00e-02\n"
        )

        ext = PowerExtractor()
        result = ext.extract(attempt, "signoff")

        assert result["total_power_mw"] == pytest.approx(10.0)
        assert result["internal_power_mw"] == pytest.approx(5.0)
        assert result["switching_power_mw"] == pytest.approx(3.0)
        assert result["leakage_power_mw"] == pytest.approx(2.0)
        assert result["leakage_pct"] == pytest.approx(20.0)

    def test_parses_openroad_3col_format(self, tmp_path: Path) -> None:
        """OpenROAD 3-column tabular format: internal, switching, total."""
        attempt = _make_attempt_dir(tmp_path)
        (attempt / "artifacts" / "power.rpt").write_text(
            "Group    Internal  Switching  Total\n"
            "Total    4.00e-03  5.00e-03   1.00e-02\n"
        )

        ext = PowerExtractor()
        result = ext.extract(attempt, "signoff")

        assert result["total_power_mw"] == pytest.approx(10.0)
        assert result["internal_power_mw"] == pytest.approx(4.0)
        assert result["switching_power_mw"] == pytest.approx(5.0)
        # Leakage derived as residual: 10 - 4 - 5 = 1 mW
        assert result["leakage_power_mw"] == pytest.approx(1.0)
        assert result["leakage_pct"] == pytest.approx(10.0)

    def test_parses_component_lines(self, tmp_path: Path) -> None:
        """Mock format with per-component lines."""
        attempt = _make_attempt_dir(tmp_path)
        (attempt / "artifacts" / "power.rpt").write_text(
            "Power Report\n"
            "Internal Power: 6.0 mW\n"
            "Switching Power: 3.0 mW\n"
            "Leakage Power: 1.0 mW\n"
            "Total Power: 10.0 mW\n"
        )

        ext = PowerExtractor()
        result = ext.extract(attempt, "signoff")

        assert result["total_power_mw"] == pytest.approx(10.0)
        assert result["internal_power_mw"] == pytest.approx(6.0)
        assert result["switching_power_mw"] == pytest.approx(3.0)
        assert result["leakage_power_mw"] == pytest.approx(1.0)
        assert result["leakage_pct"] == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# RuntimeExtractor
# ---------------------------------------------------------------------------


class TestRuntimeExtractor:
    def test_extracts_runtime(self, tmp_path: Path) -> None:
        attempt = _make_attempt_dir(tmp_path)
        _write_state_out(attempt, metrics={"runtime_seconds": 42.5})

        ext = RuntimeExtractor()
        result = ext.extract(attempt, "synth")

        assert result["stage_seconds"] == pytest.approx(42.5)

    def test_missing_state_returns_none(self, tmp_path: Path) -> None:
        attempt = _make_attempt_dir(tmp_path)
        ext = RuntimeExtractor()
        result = ext.extract(attempt, "synth")

        assert result["stage_seconds"] is None

    def test_missing_runtime_key_returns_none(self, tmp_path: Path) -> None:
        attempt = _make_attempt_dir(tmp_path)
        _write_state_out(attempt, metrics={"some_other_metric": 1.0})

        ext = RuntimeExtractor()
        result = ext.extract(attempt, "synth")

        assert result["stage_seconds"] is None


# ---------------------------------------------------------------------------
# CrashExtractor -- MUST NEVER CRASH
# ---------------------------------------------------------------------------


class TestCrashExtractor:
    def test_extracts_tool_crash(self, tmp_path: Path) -> None:
        attempt = _make_attempt_dir(tmp_path)
        (attempt / "crash.log").write_text(
            "OpenROAD crashed with SIGSEGV at detailed_route.cpp:1234\n"
            "Backtrace:\n"
            "  #0 0x7f8a in odb::dbNet::getSigType()\n"
            "Aborted (core dumped)\n"
        )

        ext = CrashExtractor()
        result = ext.extract(attempt, "route_detail")

        ci = result["crash_info"]
        assert ci is not None
        assert ci["crash_type"] == "tool_crash"
        assert ci["stderr_tail"] is not None
        assert ci["error_signature"] is not None

    def test_extracts_timeout(self, tmp_path: Path) -> None:
        attempt = _make_attempt_dir(tmp_path)
        (attempt / "crash.log").write_text(
            "Stage execution exceeded timeout. Process killed after 3600.0s."
        )

        ext = CrashExtractor()
        result = ext.extract(attempt, "synth")

        ci = result["crash_info"]
        assert ci is not None
        assert ci["crash_type"] == "timeout"

    def test_extracts_oom(self, tmp_path: Path) -> None:
        attempt = _make_attempt_dir(tmp_path)
        (attempt / "crash.log").write_text(
            "Process killed by OOM killer.\n"
            "Memory usage peaked at 32.1 GB (limit: 16 GB).\n"
            "dmesg: Out of memory: Killed process 12345 (openroad)\n"
        )

        ext = CrashExtractor()
        result = ext.extract(attempt, "route_detail")

        ci = result["crash_info"]
        assert ci is not None
        assert ci["crash_type"] == "oom_killed"

    def test_no_crash_log_returns_none(self, tmp_path: Path) -> None:
        attempt = _make_attempt_dir(tmp_path)
        ext = CrashExtractor()
        result = ext.extract(attempt, "synth")

        assert result["crash_info"] is None

    def test_never_crashes_on_garbage(self, tmp_path: Path) -> None:
        """Given garbage input, CrashExtractor NEVER raises."""
        attempt = _make_attempt_dir(tmp_path)

        # Write binary garbage as crash.log
        (attempt / "crash.log").write_bytes(b"\x00\xff\xfe\xfd" * 100)

        ext = CrashExtractor()
        # This must not raise
        result = ext.extract(attempt, "synth")
        assert "crash_info" in result

    def test_never_crashes_on_empty_file(self, tmp_path: Path) -> None:
        attempt = _make_attempt_dir(tmp_path)
        (attempt / "crash.log").write_text("")

        ext = CrashExtractor()
        result = ext.extract(attempt, "synth")
        # Empty crash log should return crash_info with type "unknown"
        ci = result["crash_info"]
        assert ci is not None
        assert ci["crash_type"] == "unknown"

    def test_never_crashes_on_nonexistent_dir(self) -> None:
        """Extractor handles nonexistent attempt_dir gracefully."""
        ext = CrashExtractor()
        result = ext.extract(Path("/nonexistent/path/attempt_999"), "synth")
        assert result["crash_info"] is None


# ---------------------------------------------------------------------------
# SpatialExtractor
# ---------------------------------------------------------------------------


class TestSpatialExtractor:
    def test_generates_hotspots(self, tmp_path: Path) -> None:
        attempt = _make_attempt_dir(tmp_path)
        _write_congestion_report(attempt / "artifacts", overflow=5.0)

        ext = SpatialExtractor(grid_bins_x=2, grid_bins_y=2, max_hotspots=12)
        result = ext.extract(attempt, "route_global")

        hotspots = result["spatial_hotspots"]
        assert len(hotspots) > 0
        for h in hotspots:
            assert h["type"] == "congestion"
            assert "x" in h["grid_bin"]
            assert "y" in h["grid_bin"]
            assert h["severity"] >= 0.0

    def test_sorted_by_severity(self, tmp_path: Path) -> None:
        attempt = _make_attempt_dir(tmp_path)
        _write_congestion_report(attempt / "artifacts", overflow=10.0)

        ext = SpatialExtractor(grid_bins_x=3, grid_bins_y=3)
        result = ext.extract(attempt, "route_global")

        hotspots = result["spatial_hotspots"]
        severities = [h["severity"] for h in hotspots]
        assert severities == sorted(severities, reverse=True)

    def test_zero_overflow_no_hotspots(self, tmp_path: Path) -> None:
        attempt = _make_attempt_dir(tmp_path)
        _write_congestion_report(attempt / "artifacts", overflow=0.0)

        ext = SpatialExtractor()
        result = ext.extract(attempt, "route_global")

        assert result["spatial_hotspots"] == []

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        attempt = _make_attempt_dir(tmp_path)
        ext = SpatialExtractor()
        result = ext.extract(attempt, "route_global")

        assert result["spatial_hotspots"] == []

    def test_region_labels(self, tmp_path: Path) -> None:
        """2x2 grid should produce NW/NE/SW/SE labels."""
        attempt = _make_attempt_dir(tmp_path)
        _write_congestion_report(attempt / "artifacts", overflow=5.0)

        ext = SpatialExtractor(grid_bins_x=2, grid_bins_y=2)
        result = ext.extract(attempt, "route_global")

        labels = {h["region_label"] for h in result["spatial_hotspots"]}
        # Should have some of the quadrant labels
        assert labels.issubset({"NW", "NE", "SW", "SE"})


# ---------------------------------------------------------------------------
# ConstraintExtractor
# ---------------------------------------------------------------------------


class TestConstraintExtractor:
    def test_parses_sdc(self, tmp_path: Path) -> None:
        attempt = _make_attempt_dir(tmp_path)
        (attempt / "artifacts" / "synth.sdc").write_text(
            "create_clock -name core_clk -period 10.0 [get_ports clk]\n"
            "set_false_path -from [get_ports reset]\n"
            "set_max_delay 5.0 -from [get_ports din] -to [get_ports dout]\n"
        )

        ext = ConstraintExtractor()
        result = ext.extract(attempt, "synth")

        cd = result["constraint_digest"]
        assert len(cd["clocks"]) == 1
        assert cd["clocks"][0]["name"] == "core_clk"
        assert cd["clocks"][0]["period_ns"] == pytest.approx(10.0)
        assert cd["exceptions"]["false_path_count"] == 1
        assert cd["delays"]["set_max_delay_count"] == 1

    def test_golden_sdc(self) -> None:
        """Golden SDC produces exact expected constraint digest."""
        ext = ConstraintExtractor()
        golden = GOLDEN_DIR / "constraints.sdc"
        assert golden.is_file()

        import tempfile

        with tempfile.TemporaryDirectory() as td:
            attempt = Path(td)
            arts = attempt / "artifacts"
            arts.mkdir()
            shutil.copy(golden, arts / "constraints.sdc")

            result = ext.extract(attempt, "synth")

        cd = result["constraint_digest"]
        assert len(cd["clocks"]) == 1
        assert cd["clocks"][0]["name"] == "core_clk"
        assert cd["clocks"][0]["period_ns"] == pytest.approx(10.0)
        assert cd["exceptions"]["false_path_count"] == 2
        assert cd["exceptions"]["multicycle_path_count"] == 1
        assert cd["delays"]["set_max_delay_count"] == 1
        assert cd["uncertainty"]["set_clock_uncertainty_count"] == 1

    def test_no_sdc_files(self, tmp_path: Path) -> None:
        attempt = _make_attempt_dir(tmp_path)
        ext = ConstraintExtractor()
        result = ext.extract(attempt, "synth")

        cd = result["constraint_digest"]
        assert cd["clocks"] == []
        assert "No SDC files found" in cd["notes"]

    def test_no_artifacts_dir(self, tmp_path: Path) -> None:
        attempt = tmp_path / "attempt_001"
        attempt.mkdir()
        # No artifacts/ sub-directory

        ext = ConstraintExtractor()
        result = ext.extract(attempt, "synth")

        cd = result["constraint_digest"]
        assert "No artifacts directory found" in cd["notes"]


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------


class TestRegistry:
    def setup_method(self) -> None:
        """Ensure we re-import extractors to populate registry."""
        # Import the extractors package to register all built-in extractors
        import agenticlane.distill.extractors  # noqa: F401

    def test_register_and_list(self) -> None:
        names = list_extractor_names()
        assert "timing" in names
        assert "area" in names
        assert "route" in names
        assert "drc" in names
        assert "lvs" in names
        assert "power" in names
        assert "runtime" in names
        assert "crash" in names
        assert "spatial" in names
        assert "constraints" in names

    def test_get_extractor(self) -> None:
        ext = get_extractor("timing")
        assert ext.name == "timing"

    def test_get_missing_extractor(self) -> None:
        with pytest.raises(KeyError, match="no_such_extractor"):
            get_extractor("no_such_extractor")

    def test_get_all_extractors(self) -> None:
        all_ext = get_all_extractors()
        assert isinstance(all_ext, dict)
        assert len(all_ext) >= 10

    def test_register_custom(self) -> None:
        class CustomExtractor:
            name = "custom_test"

            def extract(self, attempt_dir: Path, stage_name: str) -> dict:
                return {"custom": True}

        register(CustomExtractor())
        ext = get_extractor("custom_test")
        assert ext.name == "custom_test"

        result = ext.extract(Path("/fake"), "test")
        assert result["custom"] is True


# ---------------------------------------------------------------------------
# Missing file graceful handling (cross-extractor)
# ---------------------------------------------------------------------------


class TestMissingFileGraceful:
    """Every extractor must handle missing files without raising."""

    EXTRACTORS = [
        TimingExtractor(),
        AreaExtractor(),
        RouteExtractor(),
        DRCExtractor(),
        LVSExtractor(),
        PowerExtractor(),
        RuntimeExtractor(),
        CrashExtractor(),
        SpatialExtractor(),
        ConstraintExtractor(),
    ]

    @pytest.mark.parametrize(
        "extractor",
        EXTRACTORS,
        ids=[e.name for e in EXTRACTORS],
    )
    def test_missing_attempt_dir(self, extractor: object) -> None:
        """Extractor returns dict (not raises) for nonexistent dir."""
        result = extractor.extract(  # type: ignore[union-attr]
            Path("/nonexistent/attempt_dir"), "synth"
        )
        assert isinstance(result, dict)

    @pytest.mark.parametrize(
        "extractor",
        EXTRACTORS,
        ids=[e.name for e in EXTRACTORS],
    )
    def test_empty_attempt_dir(self, tmp_path: Path, extractor: object) -> None:
        """Extractor returns dict for empty attempt dir (no artifacts)."""
        attempt = tmp_path / "empty_attempt"
        attempt.mkdir()
        result = extractor.extract(  # type: ignore[union-attr]
            attempt, "synth"
        )
        assert isinstance(result, dict)
