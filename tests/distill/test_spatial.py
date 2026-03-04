"""Tests for P4.2 Spatial Hotspot Extraction Enhancement.

Tests the enhanced SpatialExtractor with coordinate bounds, nearby
macro detection, and severity normalization.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from agenticlane.distill.extractors.spatial import SpatialExtractor
from agenticlane.schemas.evidence import SpatialHotspot

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_attempt_dir(tmp_path: Path) -> Path:
    """Create a minimal attempt directory with artifacts/ subdir."""
    attempt = tmp_path / "attempt_001"
    artifacts = attempt / "artifacts"
    artifacts.mkdir(parents=True)
    return attempt


def _write_congestion(attempt: Path, overflow: float) -> None:
    """Write a synthetic congestion report with given overflow %."""
    (attempt / "artifacts" / "congestion.rpt").write_text(
        f"Overflow: {overflow:.4f}%\n"
    )


def _write_die_area(
    attempt: Path,
    x_min: float = 0.0,
    y_min: float = 0.0,
    x_max: float = 1000.0,
    y_max: float = 1000.0,
) -> None:
    """Write a die_area.json file."""
    (attempt / "artifacts" / "die_area.json").write_text(
        json.dumps(
            {"x_min": x_min, "y_min": y_min, "x_max": x_max, "y_max": y_max}
        )
    )


def _write_macros(attempt: Path, macros: list[dict]) -> None:
    """Write a macros.json file."""
    (attempt / "artifacts" / "macros.json").write_text(json.dumps(macros))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSpatialHotspotCoordinates:
    """Test coordinate bounds from die area."""

    def test_hotspot_has_coordinates(self, tmp_path: Path) -> None:
        """When die_area.json exists, hotspots include x/y coordinate bounds."""
        attempt = _make_attempt_dir(tmp_path)
        _write_congestion(attempt, overflow=5.0)
        _write_die_area(attempt, x_min=0.0, y_min=0.0, x_max=1000.0, y_max=1000.0)

        ext = SpatialExtractor(grid_bins_x=2, grid_bins_y=2)
        result = ext.extract(attempt, "route_global")

        hotspots = result["spatial_hotspots"]
        assert len(hotspots) > 0
        for h in hotspots:
            assert h["x_min_um"] is not None
            assert h["y_min_um"] is not None
            assert h["x_max_um"] is not None
            assert h["y_max_um"] is not None
            # Bounds are within die area
            assert h["x_min_um"] >= 0.0
            assert h["y_min_um"] >= 0.0
            assert h["x_max_um"] <= 1000.0
            assert h["y_max_um"] <= 1000.0
            # Bounds are ordered
            assert h["x_max_um"] > h["x_min_um"]
            assert h["y_max_um"] > h["y_min_um"]

    def test_coordinate_bounds_correct_2x2(self, tmp_path: Path) -> None:
        """2x2 grid on a 1000x1000 die produces 500um bins."""
        attempt = _make_attempt_dir(tmp_path)
        _write_congestion(attempt, overflow=5.0)
        _write_die_area(attempt, x_min=0.0, y_min=0.0, x_max=1000.0, y_max=1000.0)

        ext = SpatialExtractor(grid_bins_x=2, grid_bins_y=2)
        result = ext.extract(attempt, "route_global")

        hotspots = result["spatial_hotspots"]
        # Collect all bin coordinates
        bins_by_coord = {
            (h["grid_bin"]["x"], h["grid_bin"]["y"]): h for h in hotspots
        }

        # Check SW bin (0,0)
        if (0, 0) in bins_by_coord:
            sw = bins_by_coord[(0, 0)]
            assert sw["x_min_um"] == pytest.approx(0.0)
            assert sw["y_min_um"] == pytest.approx(0.0)
            assert sw["x_max_um"] == pytest.approx(500.0)
            assert sw["y_max_um"] == pytest.approx(500.0)

        # Check NE bin (1,1)
        if (1, 1) in bins_by_coord:
            ne = bins_by_coord[(1, 1)]
            assert ne["x_min_um"] == pytest.approx(500.0)
            assert ne["y_min_um"] == pytest.approx(500.0)
            assert ne["x_max_um"] == pytest.approx(1000.0)
            assert ne["y_max_um"] == pytest.approx(1000.0)

    def test_no_die_area_coordinates_none(self, tmp_path: Path) -> None:
        """Without die_area.json, coordinate fields are None."""
        attempt = _make_attempt_dir(tmp_path)
        _write_congestion(attempt, overflow=5.0)
        # No die_area.json written

        ext = SpatialExtractor(grid_bins_x=2, grid_bins_y=2)
        result = ext.extract(attempt, "route_global")

        hotspots = result["spatial_hotspots"]
        assert len(hotspots) > 0
        for h in hotspots:
            assert h["x_min_um"] is None
            assert h["y_min_um"] is None
            assert h["x_max_um"] is None
            assert h["y_max_um"] is None


class TestSpatialSeverity:
    """Test severity normalization."""

    def test_hotspot_severity_normalized(self, tmp_path: Path) -> None:
        """All severity values are in [0.0, 1.0]."""
        attempt = _make_attempt_dir(tmp_path)
        _write_congestion(attempt, overflow=50.0)

        ext = SpatialExtractor(grid_bins_x=3, grid_bins_y=3)
        result = ext.extract(attempt, "route_global")

        hotspots = result["spatial_hotspots"]
        assert len(hotspots) > 0
        for h in hotspots:
            assert 0.0 <= h["severity"] <= 1.0

    def test_high_overflow_clamped(self, tmp_path: Path) -> None:
        """200% overflow results in severity clamped to 1.0 max."""
        attempt = _make_attempt_dir(tmp_path)
        _write_congestion(attempt, overflow=200.0)

        ext = SpatialExtractor(grid_bins_x=2, grid_bins_y=2)
        result = ext.extract(attempt, "route_global")

        hotspots = result["spatial_hotspots"]
        assert len(hotspots) > 0
        for h in hotspots:
            assert h["severity"] <= 1.0

    def test_severity_schema_validation(self) -> None:
        """SpatialHotspot schema rejects severity > 1.0."""
        with pytest.raises(ValidationError):
            SpatialHotspot(
                type="congestion",
                grid_bin={"x": 0, "y": 0},
                severity=1.5,
            )

    def test_severity_schema_accepts_valid(self) -> None:
        """SpatialHotspot schema accepts severity in [0.0, 1.0]."""
        h = SpatialHotspot(
            type="congestion",
            grid_bin={"x": 0, "y": 0},
            severity=0.75,
        )
        assert h.severity == 0.75

    def test_hotspots_sorted_by_severity(self, tmp_path: Path) -> None:
        """Returned list is severity-descending."""
        attempt = _make_attempt_dir(tmp_path)
        _write_congestion(attempt, overflow=10.0)

        ext = SpatialExtractor(grid_bins_x=3, grid_bins_y=3)
        result = ext.extract(attempt, "route_global")

        hotspots = result["spatial_hotspots"]
        severities = [h["severity"] for h in hotspots]
        assert severities == sorted(severities, reverse=True)


class TestSpatialNearbyMacros:
    """Test nearby macro detection."""

    def test_hotspot_lists_nearby_macros(self, tmp_path: Path) -> None:
        """Macros near hotspot bins are listed."""
        attempt = _make_attempt_dir(tmp_path)
        _write_congestion(attempt, overflow=5.0)
        _write_die_area(attempt, x_min=0.0, y_min=0.0, x_max=1000.0, y_max=1000.0)
        # Place macro at center of SW bin (0,0) which spans [0, 500] x [0, 500]
        _write_macros(attempt, [
            {"name": "U_SRAM_0", "x_um": 250.0, "y_um": 250.0},
        ])

        ext = SpatialExtractor(grid_bins_x=2, grid_bins_y=2, macro_nearby_radius_um=50.0)
        result = ext.extract(attempt, "route_global")

        hotspots = result["spatial_hotspots"]
        bins_by_coord = {
            (h["grid_bin"]["x"], h["grid_bin"]["y"]): h for h in hotspots
        }

        # Macro is inside SW bin, so it should be in nearby_macros
        if (0, 0) in bins_by_coord:
            assert "U_SRAM_0" in bins_by_coord[(0, 0)]["nearby_macros"]

    def test_macro_outside_radius_not_listed(self, tmp_path: Path) -> None:
        """Macro far from bin is not included in nearby_macros."""
        attempt = _make_attempt_dir(tmp_path)
        _write_congestion(attempt, overflow=5.0)
        _write_die_area(attempt, x_min=0.0, y_min=0.0, x_max=1000.0, y_max=1000.0)
        # Place macro far away at (900, 900), only near NE bin
        _write_macros(attempt, [
            {"name": "U_FAR_MACRO", "x_um": 900.0, "y_um": 900.0},
        ])

        ext = SpatialExtractor(grid_bins_x=2, grid_bins_y=2, macro_nearby_radius_um=50.0)
        result = ext.extract(attempt, "route_global")

        hotspots = result["spatial_hotspots"]
        bins_by_coord = {
            (h["grid_bin"]["x"], h["grid_bin"]["y"]): h for h in hotspots
        }

        # Macro at (900, 900) is inside NE bin [500, 1000]x[500, 1000]
        if (1, 1) in bins_by_coord:
            assert "U_FAR_MACRO" in bins_by_coord[(1, 1)]["nearby_macros"]

        # Macro should NOT be near SW bin
        if (0, 0) in bins_by_coord:
            assert "U_FAR_MACRO" not in bins_by_coord[(0, 0)]["nearby_macros"]

    def test_no_macros_file_empty_nearby(self, tmp_path: Path) -> None:
        """Without macros.json, nearby_macros is empty list."""
        attempt = _make_attempt_dir(tmp_path)
        _write_congestion(attempt, overflow=5.0)
        _write_die_area(attempt, x_min=0.0, y_min=0.0, x_max=1000.0, y_max=1000.0)
        # No macros.json

        ext = SpatialExtractor(grid_bins_x=2, grid_bins_y=2)
        result = ext.extract(attempt, "route_global")

        hotspots = result["spatial_hotspots"]
        assert len(hotspots) > 0
        for h in hotspots:
            assert h["nearby_macros"] == []

    def test_multiple_macros_near_same_bin(self, tmp_path: Path) -> None:
        """Multiple macros near the same bin are all listed."""
        attempt = _make_attempt_dir(tmp_path)
        _write_congestion(attempt, overflow=5.0)
        _write_die_area(attempt, x_min=0.0, y_min=0.0, x_max=1000.0, y_max=1000.0)
        _write_macros(attempt, [
            {"name": "U_SRAM_0", "x_um": 250.0, "y_um": 250.0},
            {"name": "U_SRAM_1", "x_um": 300.0, "y_um": 300.0},
        ])

        ext = SpatialExtractor(grid_bins_x=2, grid_bins_y=2, macro_nearby_radius_um=50.0)
        result = ext.extract(attempt, "route_global")

        hotspots = result["spatial_hotspots"]
        bins_by_coord = {
            (h["grid_bin"]["x"], h["grid_bin"]["y"]): h for h in hotspots
        }

        if (0, 0) in bins_by_coord:
            nearby = bins_by_coord[(0, 0)]["nearby_macros"]
            assert "U_SRAM_0" in nearby
            assert "U_SRAM_1" in nearby
            # Sorted alphabetically
            assert nearby == sorted(nearby)

    def test_macro_within_radius_of_bin_edge(self, tmp_path: Path) -> None:
        """Macro just outside bin but within radius is still nearby."""
        attempt = _make_attempt_dir(tmp_path)
        _write_congestion(attempt, overflow=5.0)
        _write_die_area(attempt, x_min=0.0, y_min=0.0, x_max=1000.0, y_max=1000.0)
        # Place macro just outside SW bin at (510, 250) -- 10um from x_max of SW bin
        _write_macros(attempt, [
            {"name": "U_EDGE", "x_um": 510.0, "y_um": 250.0},
        ])

        ext = SpatialExtractor(grid_bins_x=2, grid_bins_y=2, macro_nearby_radius_um=50.0)
        result = ext.extract(attempt, "route_global")

        hotspots = result["spatial_hotspots"]
        bins_by_coord = {
            (h["grid_bin"]["x"], h["grid_bin"]["y"]): h for h in hotspots
        }

        # 10um from SW bin edge, within 50um radius
        if (0, 0) in bins_by_coord:
            assert "U_EDGE" in bins_by_coord[(0, 0)]["nearby_macros"]


class TestSpatialEdgeCases:
    """Test edge cases and golden patterns."""

    def test_no_congestion_empty_list(self, tmp_path: Path) -> None:
        """No overflow produces empty hotspot list."""
        attempt = _make_attempt_dir(tmp_path)
        _write_congestion(attempt, overflow=0.0)
        _write_die_area(attempt, x_min=0.0, y_min=0.0, x_max=1000.0, y_max=1000.0)

        ext = SpatialExtractor(grid_bins_x=2, grid_bins_y=2)
        result = ext.extract(attempt, "route_global")

        assert result["spatial_hotspots"] == []

    def test_golden_congestion_map(self, tmp_path: Path) -> None:
        """Known 5% overflow on 2x2 grid produces exact hotspot list.

        For a 2x2 grid, all four bins have identical centre_factor=0.0,
        so severity = 5.0 * (0.5 + 0.0) / 100.0 = 0.025 for all bins.
        """
        attempt = _make_attempt_dir(tmp_path)
        _write_congestion(attempt, overflow=5.0)
        _write_die_area(attempt, x_min=0.0, y_min=0.0, x_max=1000.0, y_max=1000.0)

        ext = SpatialExtractor(grid_bins_x=2, grid_bins_y=2, max_hotspots=12)
        result = ext.extract(attempt, "route_global")

        hotspots = result["spatial_hotspots"]
        assert len(hotspots) == 4

        # All have severity 0.025
        for h in hotspots:
            assert h["severity"] == pytest.approx(0.025)
            assert h["type"] == "congestion"

        # All four quadrant labels present
        labels = {h["region_label"] for h in hotspots}
        assert labels == {"SW", "SE", "NW", "NE"}

        # All have coordinate bounds (die area was provided)
        for h in hotspots:
            assert h["x_min_um"] is not None
            assert h["y_min_um"] is not None

    def test_missing_congestion_report(self, tmp_path: Path) -> None:
        """Missing congestion.rpt returns empty hotspot list."""
        attempt = _make_attempt_dir(tmp_path)
        # No congestion.rpt written

        ext = SpatialExtractor()
        result = ext.extract(attempt, "route_global")

        assert result["spatial_hotspots"] == []

    def test_schema_roundtrip_with_coordinates(self) -> None:
        """SpatialHotspot with coordinates roundtrips through JSON."""
        h = SpatialHotspot(
            type="congestion",
            grid_bin={"x": 0, "y": 0},
            region_label="SW",
            severity=0.5,
            nearby_macros=["U_SRAM_0"],
            x_min_um=0.0,
            y_min_um=0.0,
            x_max_um=500.0,
            y_max_um=500.0,
        )
        json_str = h.model_dump_json()
        restored = SpatialHotspot.model_validate_json(json_str)
        assert restored == h
        assert restored.x_min_um == 0.0
        assert restored.x_max_um == 500.0

    def test_schema_without_coordinates(self) -> None:
        """SpatialHotspot without coordinates has None defaults."""
        h = SpatialHotspot(
            type="congestion",
            grid_bin={"x": 0, "y": 0},
            severity=0.5,
        )
        assert h.x_min_um is None
        assert h.y_min_um is None
        assert h.x_max_um is None
        assert h.y_max_um is None
        assert h.nearby_macros == []
