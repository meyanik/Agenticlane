"""P4.3 Grid Snap and Macro Placement Resolution tests.

Tests the deterministic hint->coords resolver, placement grid snapping
(site size + DBU roundtrip), collision detection, and the full
resolve_macro_placements pipeline.
"""
from __future__ import annotations

import random

import pytest

from agenticlane.execution.grid_snap import (
    CoreBBox,
    PlacementSite,
    ResolvedMacro,
    detect_collisions,
    resolve_collisions_with_offset,
    resolve_hint_to_coords,
    resolve_macro_placements,
    snap_to_grid,
    validate_orientation,
    validate_within_bounds,
)
from agenticlane.schemas.patch import MacroPlacement

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def core_bbox() -> CoreBBox:
    """Standard 1000x1000 um core bbox starting at (0,0)."""
    return CoreBBox(x_min=0.0, y_min=0.0, x_max=1000.0, y_max=1000.0)


@pytest.fixture
def site() -> PlacementSite:
    """Standard placement site 0.46 x 2.72 um (typical sky130)."""
    return PlacementSite(width_um=0.46, height_um=2.72)


# ---------------------------------------------------------------------------
# Grid Snap Tests
# ---------------------------------------------------------------------------


class TestSnapNearest:
    """test_snap_nearest -- x=13.7, site.width=0.46 snaps to nearest multiple."""

    def test_snap_nearest(self, site: PlacementSite) -> None:
        x, y = snap_to_grid(13.7, 5.5, site, rounding="nearest")
        # 13.7 / 0.46 = 29.78 -> round = 30 -> 30 * 0.46 = 13.80
        # 5.5 / 2.72 = 2.022 -> round = 2 -> 2 * 2.72 = 5.44
        assert x == pytest.approx(13.80, abs=1e-6)
        assert y == pytest.approx(5.44, abs=1e-6)

    def test_snap_nearest_exact_multiple(self, site: PlacementSite) -> None:
        """Already on grid -> no change."""
        x, y = snap_to_grid(0.92, 5.44, site, rounding="nearest")
        assert x == pytest.approx(0.92, abs=1e-6)
        assert y == pytest.approx(5.44, abs=1e-6)


class TestSnapFloor:
    """test_snap_floor -- floor rounding."""

    def test_snap_floor(self, site: PlacementSite) -> None:
        x, y = snap_to_grid(13.7, 5.5, site, rounding="floor")
        # 13.7 / 0.46 = 29.78 -> floor = 29 -> 29 * 0.46 = 13.34
        # 5.5 / 2.72 = 2.022 -> floor = 2 -> 2 * 2.72 = 5.44
        assert x == pytest.approx(13.34, abs=1e-6)
        assert y == pytest.approx(5.44, abs=1e-6)

    def test_snap_floor_already_on_grid(self, site: PlacementSite) -> None:
        x, y = snap_to_grid(0.92, 2.72, site, rounding="floor")
        assert x == pytest.approx(0.92, abs=1e-6)
        assert y == pytest.approx(2.72, abs=1e-6)


class TestSnapCeil:
    """test_snap_ceil -- ceil rounding."""

    def test_snap_ceil(self, site: PlacementSite) -> None:
        x, y = snap_to_grid(13.7, 5.5, site, rounding="ceil")
        # 13.7 / 0.46 = 29.78 -> ceil = 30 -> 30 * 0.46 = 13.80
        # 5.5 / 2.72 = 2.022 -> ceil = 3 -> 3 * 2.72 = 8.16
        assert x == pytest.approx(13.80, abs=1e-6)
        assert y == pytest.approx(8.16, abs=1e-6)


class TestDBURoundtrip:
    """test_dbu_roundtrip -- DBU conversion produces clean integer DBU values."""

    def test_dbu_roundtrip_default(self, site: PlacementSite) -> None:
        x, y = snap_to_grid(13.7, 5.5, site, dbu_per_um=1000.0)
        # After snap and DBU roundtrip, x*1000 and y*1000 must be integers
        assert x * 1000 == pytest.approx(round(x * 1000), abs=1e-9)
        assert y * 1000 == pytest.approx(round(y * 1000), abs=1e-9)

    def test_dbu_roundtrip_custom(self, site: PlacementSite) -> None:
        x, y = snap_to_grid(13.7, 5.5, site, dbu_per_um=2000.0)
        assert x * 2000 == pytest.approx(round(x * 2000), abs=1e-9)
        assert y * 2000 == pytest.approx(round(y * 2000), abs=1e-9)


# ---------------------------------------------------------------------------
# Hint-to-Coords Tests
# ---------------------------------------------------------------------------


class TestHintToCoords:
    """Tests for resolve_hint_to_coords."""

    def test_hint_to_coords_sw(self, core_bbox: CoreBBox) -> None:
        """SW hint -> (10% of width, 10% of height)."""
        x, y = resolve_hint_to_coords("SW", core_bbox)
        assert x == pytest.approx(100.0)
        assert y == pytest.approx(100.0)

    def test_hint_to_coords_center(self, core_bbox: CoreBBox) -> None:
        """CENTER hint -> (50%, 50%)."""
        x, y = resolve_hint_to_coords("CENTER", core_bbox)
        assert x == pytest.approx(500.0)
        assert y == pytest.approx(500.0)

    def test_hint_to_coords_ne(self, core_bbox: CoreBBox) -> None:
        """NE hint -> (90%, 90%)."""
        x, y = resolve_hint_to_coords("NE", core_bbox)
        assert x == pytest.approx(900.0)
        assert y == pytest.approx(900.0)

    def test_hint_to_coords_nw(self, core_bbox: CoreBBox) -> None:
        """NW hint -> (10%, 90%)."""
        x, y = resolve_hint_to_coords("NW", core_bbox)
        assert x == pytest.approx(100.0)
        assert y == pytest.approx(900.0)

    def test_hint_to_coords_se(self, core_bbox: CoreBBox) -> None:
        """SE hint -> (90%, 10%)."""
        x, y = resolve_hint_to_coords("SE", core_bbox)
        assert x == pytest.approx(900.0)
        assert y == pytest.approx(100.0)

    def test_hint_to_coords_periphery(self, core_bbox: CoreBBox) -> None:
        """PERIPHERY hint -> (10%, 50%)."""
        x, y = resolve_hint_to_coords("PERIPHERY", core_bbox)
        assert x == pytest.approx(100.0)
        assert y == pytest.approx(500.0)

    def test_hint_to_coords_case_insensitive(self, core_bbox: CoreBBox) -> None:
        """Lowercase hint works."""
        x, y = resolve_hint_to_coords("ne", core_bbox)
        assert x == pytest.approx(900.0)
        assert y == pytest.approx(900.0)

    def test_hint_to_coords_unknown(self, core_bbox: CoreBBox) -> None:
        """Unknown hint raises ValueError."""
        with pytest.raises(ValueError, match="Unknown location hint"):
            resolve_hint_to_coords("NORTH", core_bbox)

    def test_hint_to_coords_offset_bbox(self) -> None:
        """Non-zero origin bbox."""
        bbox = CoreBBox(x_min=100.0, y_min=200.0, x_max=600.0, y_max=700.0)
        x, y = resolve_hint_to_coords("SW", bbox)
        # x = 100 + 0.1 * 500 = 150
        # y = 200 + 0.1 * 500 = 250
        assert x == pytest.approx(150.0)
        assert y == pytest.approx(250.0)


# ---------------------------------------------------------------------------
# Orientation Validation Tests
# ---------------------------------------------------------------------------


class TestValidateOrientation:
    """Tests for validate_orientation."""

    @pytest.mark.parametrize("orient", ["N", "S", "E", "W", "FN", "FS", "FE", "FW"])
    def test_valid_orientations(self, orient: str) -> None:
        """N, S, E, W, FN, FS, FE, FW all pass."""
        validate_orientation(orient)  # Should not raise

    @pytest.mark.parametrize("orient", ["n", "fn", "fe"])
    def test_valid_orientations_case_insensitive(self, orient: str) -> None:
        """Lowercase valid orientations pass."""
        validate_orientation(orient)

    def test_invalid_orientation(self) -> None:
        """'X' raises ValueError."""
        with pytest.raises(ValueError, match="Invalid orientation"):
            validate_orientation("X")

    def test_invalid_orientation_empty(self) -> None:
        """Empty string raises ValueError."""
        with pytest.raises(ValueError, match="Invalid orientation"):
            validate_orientation("")


# ---------------------------------------------------------------------------
# Bounds Validation Tests
# ---------------------------------------------------------------------------


class TestValidateWithinBounds:
    """Tests for validate_within_bounds."""

    def test_within_bounds_pass(self, core_bbox: CoreBBox) -> None:
        """Valid coordinates pass."""
        validate_within_bounds(500.0, 500.0, core_bbox, "TEST")

    def test_within_bounds_at_edge(self, core_bbox: CoreBBox) -> None:
        """Coordinates at the exact edge pass."""
        validate_within_bounds(0.0, 0.0, core_bbox, "TEST")
        validate_within_bounds(1000.0, 1000.0, core_bbox, "TEST")

    def test_within_bounds_fail_x_low(self, core_bbox: CoreBBox) -> None:
        """x below x_min raises ValueError."""
        with pytest.raises(ValueError, match="outside core bounds"):
            validate_within_bounds(-1.0, 500.0, core_bbox, "TEST")

    def test_within_bounds_fail_x_high(self, core_bbox: CoreBBox) -> None:
        """x above x_max raises ValueError."""
        with pytest.raises(ValueError, match="outside core bounds"):
            validate_within_bounds(1001.0, 500.0, core_bbox, "TEST")

    def test_within_bounds_fail_y_low(self, core_bbox: CoreBBox) -> None:
        """y below y_min raises ValueError."""
        with pytest.raises(ValueError, match="outside core bounds"):
            validate_within_bounds(500.0, -1.0, core_bbox, "TEST")

    def test_within_bounds_fail_y_high(self, core_bbox: CoreBBox) -> None:
        """y above y_max raises ValueError."""
        with pytest.raises(ValueError, match="outside core bounds"):
            validate_within_bounds(500.0, 1001.0, core_bbox, "TEST")


# ---------------------------------------------------------------------------
# Collision Detection Tests
# ---------------------------------------------------------------------------


class TestCollisionDetection:
    """Tests for detect_collisions and resolve_collisions_with_offset."""

    def test_collision_detected(self) -> None:
        """Two overlapping macros detected."""
        macros = [
            ResolvedMacro("A", x_um=0.0, y_um=0.0, orientation="N",
                          width_um=50.0, height_um=50.0),
            ResolvedMacro("B", x_um=25.0, y_um=25.0, orientation="N",
                          width_um=50.0, height_um=50.0),
        ]
        collisions = detect_collisions(macros)
        assert len(collisions) == 1
        assert collisions[0] == ("A", "B")

    def test_no_collision(self) -> None:
        """Non-overlapping macros produce empty collision list."""
        macros = [
            ResolvedMacro("A", x_um=0.0, y_um=0.0, orientation="N",
                          width_um=50.0, height_um=50.0),
            ResolvedMacro("B", x_um=100.0, y_um=100.0, orientation="N",
                          width_um=50.0, height_um=50.0),
        ]
        collisions = detect_collisions(macros)
        assert collisions == []

    def test_touching_not_overlapping(self) -> None:
        """Macros that exactly touch but don't overlap are not collisions."""
        macros = [
            ResolvedMacro("A", x_um=0.0, y_um=0.0, orientation="N",
                          width_um=50.0, height_um=50.0),
            ResolvedMacro("B", x_um=50.0, y_um=0.0, orientation="N",
                          width_um=50.0, height_um=50.0),
        ]
        collisions = detect_collisions(macros)
        assert collisions == []

    def test_collision_resolution(self) -> None:
        """Colliding macros get offset applied."""
        macros = [
            ResolvedMacro("A", x_um=0.0, y_um=0.0, orientation="N",
                          width_um=50.0, height_um=50.0),
            ResolvedMacro("B", x_um=25.0, y_um=25.0, orientation="N",
                          width_um=50.0, height_um=50.0),
        ]
        resolved = resolve_collisions_with_offset(macros, offset_step_um=60.0)
        # After resolution, no collisions should remain
        collisions = detect_collisions(resolved)
        assert collisions == []

    def test_collision_resolution_preserves_first(self) -> None:
        """First macro (by sorted name) is not moved during collision resolution."""
        macros = [
            ResolvedMacro("A", x_um=0.0, y_um=0.0, orientation="N",
                          width_um=50.0, height_um=50.0),
            ResolvedMacro("B", x_um=25.0, y_um=25.0, orientation="N",
                          width_um=50.0, height_um=50.0),
        ]
        resolved = resolve_collisions_with_offset(macros, offset_step_um=60.0)
        a_macro = next(m for m in resolved if m.instance == "A")
        assert a_macro.x_um == pytest.approx(0.0)
        assert a_macro.y_um == pytest.approx(0.0)

    def test_zero_size_macros_no_collision(self) -> None:
        """Macros with zero width/height never collide."""
        macros = [
            ResolvedMacro("A", x_um=100.0, y_um=100.0, orientation="N",
                          width_um=0.0, height_um=0.0),
            ResolvedMacro("B", x_um=100.0, y_um=100.0, orientation="N",
                          width_um=0.0, height_um=0.0),
        ]
        collisions = detect_collisions(macros)
        assert collisions == []


# ---------------------------------------------------------------------------
# Sorted Instance Names
# ---------------------------------------------------------------------------


class TestSortedInstanceNames:
    """test_sorted_instance_names -- Output is sorted by instance name."""

    def test_sorted_output(self) -> None:
        macros = [
            ResolvedMacro("Z_SRAM", x_um=0.0, y_um=0.0, orientation="N",
                          width_um=10.0, height_um=10.0),
            ResolvedMacro("A_SRAM", x_um=100.0, y_um=100.0, orientation="N",
                          width_um=10.0, height_um=10.0),
            ResolvedMacro("M_SRAM", x_um=200.0, y_um=200.0, orientation="N",
                          width_um=10.0, height_um=10.0),
        ]
        resolved = resolve_collisions_with_offset(macros, offset_step_um=10.0)
        names = [m.instance for m in resolved]
        assert names == sorted(names)


# ---------------------------------------------------------------------------
# Full Pipeline Tests
# ---------------------------------------------------------------------------


class TestResolveMacroPlacements:
    """Tests for the full resolve_macro_placements pipeline."""

    def test_resolve_with_hint(
        self, core_bbox: CoreBBox, site: PlacementSite
    ) -> None:
        """Full pipeline with location_hint."""
        placements = [
            MacroPlacement(instance="U_SRAM_0", location_hint="NE"),
        ]
        result = resolve_macro_placements(
            placements, core_bbox, site, dbu_per_um=1000.0
        )
        assert len(result) == 1
        assert result[0].instance == "U_SRAM_0"
        # NE -> 90% of 1000 = 900, then snapped to site grid
        # Snapped coordinates should be close to 900
        assert result[0].x_um > 800.0
        assert result[0].y_um > 800.0

    def test_resolve_with_explicit_coords(
        self, core_bbox: CoreBBox, site: PlacementSite
    ) -> None:
        """Full pipeline with x_um/y_um."""
        placements = [
            MacroPlacement(instance="U_SRAM_0", x_um=500.0, y_um=500.0),
        ]
        result = resolve_macro_placements(
            placements, core_bbox, site, dbu_per_um=1000.0
        )
        assert len(result) == 1
        assert result[0].instance == "U_SRAM_0"
        # 500 / 0.46 = 1086.96 -> round = 1087 -> 1087 * 0.46 = 500.02
        assert result[0].x_um == pytest.approx(500.02, abs=0.01)

    def test_unknown_instance_rejected(
        self, core_bbox: CoreBBox, site: PlacementSite
    ) -> None:
        """Unknown instance raises ValueError."""
        placements = [
            MacroPlacement(instance="U_UNKNOWN", location_hint="CENTER"),
        ]
        with pytest.raises(ValueError, match="Unknown macro instance"):
            resolve_macro_placements(
                placements,
                core_bbox,
                site,
                known_instances={"U_SRAM_0", "U_SRAM_1"},
            )

    def test_known_instance_accepted(
        self, core_bbox: CoreBBox, site: PlacementSite
    ) -> None:
        """Known instance passes validation."""
        placements = [
            MacroPlacement(instance="U_SRAM_0", location_hint="CENTER"),
        ]
        result = resolve_macro_placements(
            placements,
            core_bbox,
            site,
            known_instances={"U_SRAM_0"},
        )
        assert len(result) == 1

    def test_no_coords_or_hint_raises(
        self, core_bbox: CoreBBox, site: PlacementSite
    ) -> None:
        """Neither location_hint nor x_um/y_um raises ValueError."""
        placements = [
            MacroPlacement(instance="U_SRAM_0"),
        ]
        with pytest.raises(ValueError, match="must specify either"):
            resolve_macro_placements(placements, core_bbox, site)

    def test_snap_disabled(
        self, core_bbox: CoreBBox, site: PlacementSite
    ) -> None:
        """snap_enabled=False skips grid snap."""
        placements = [
            MacroPlacement(instance="U_SRAM_0", x_um=13.7, y_um=5.5),
        ]
        result = resolve_macro_placements(
            placements, core_bbox, site, snap_enabled=False
        )
        assert result[0].x_um == pytest.approx(13.7)
        assert result[0].y_um == pytest.approx(5.5)

    def test_invalid_orientation_in_pipeline(
        self, core_bbox: CoreBBox, site: PlacementSite
    ) -> None:
        """Invalid orientation raises ValueError in pipeline."""
        placements = [
            MacroPlacement(
                instance="U_SRAM_0", location_hint="CENTER", orientation="X"
            ),
        ]
        with pytest.raises(ValueError, match="Invalid orientation"):
            resolve_macro_placements(placements, core_bbox, site)

    def test_pipeline_with_collision_resolution(
        self, core_bbox: CoreBBox, site: PlacementSite
    ) -> None:
        """Pipeline resolves collisions when macro_sizes provided."""
        placements = [
            MacroPlacement(instance="U_SRAM_0", x_um=500.0, y_um=500.0),
            MacroPlacement(instance="U_SRAM_1", x_um=500.0, y_um=500.0),
        ]
        sizes = {
            "U_SRAM_0": (50.0, 50.0),
            "U_SRAM_1": (50.0, 50.0),
        }
        result = resolve_macro_placements(
            placements,
            core_bbox,
            site,
            macro_sizes=sizes,
            max_iterations=5,
        )
        assert len(result) == 2
        # After collision resolution the two should not overlap
        collisions = detect_collisions(result)
        assert collisions == []

    def test_multiple_placements_sorted(
        self, core_bbox: CoreBBox, site: PlacementSite
    ) -> None:
        """Output is sorted by instance name regardless of input order."""
        placements = [
            MacroPlacement(instance="Z_SRAM", location_hint="NE"),
            MacroPlacement(instance="A_SRAM", location_hint="SW"),
            MacroPlacement(instance="M_SRAM", location_hint="CENTER"),
        ]
        result = resolve_macro_placements(placements, core_bbox, site)
        names = [m.instance for m in result]
        assert names == ["A_SRAM", "M_SRAM", "Z_SRAM"]


# ---------------------------------------------------------------------------
# Determinism Tests
# ---------------------------------------------------------------------------


class TestDeterminism:
    """test_deterministic_offsets -- Same input -> same output every time."""

    def test_deterministic_offsets(
        self, core_bbox: CoreBBox, site: PlacementSite
    ) -> None:
        """Running resolve_macro_placements twice gives identical results."""
        placements = [
            MacroPlacement(instance="U_SRAM_0", x_um=500.0, y_um=500.0),
            MacroPlacement(instance="U_SRAM_1", x_um=500.0, y_um=500.0),
        ]
        sizes = {
            "U_SRAM_0": (50.0, 50.0),
            "U_SRAM_1": (50.0, 50.0),
        }
        result1 = resolve_macro_placements(
            placements, core_bbox, site, macro_sizes=sizes
        )
        result2 = resolve_macro_placements(
            placements, core_bbox, site, macro_sizes=sizes
        )
        for a, b in zip(result1, result2, strict=True):
            assert a.instance == b.instance
            assert a.x_um == pytest.approx(b.x_um)
            assert a.y_um == pytest.approx(b.y_um)
            assert a.orientation == b.orientation

    def test_deterministic_different_input_order(
        self, core_bbox: CoreBBox, site: PlacementSite
    ) -> None:
        """Different input order produces same result (sorted by name)."""
        p1 = [
            MacroPlacement(instance="U_SRAM_1", location_hint="NE"),
            MacroPlacement(instance="U_SRAM_0", location_hint="SW"),
        ]
        p2 = [
            MacroPlacement(instance="U_SRAM_0", location_hint="SW"),
            MacroPlacement(instance="U_SRAM_1", location_hint="NE"),
        ]
        r1 = resolve_macro_placements(p1, core_bbox, site)
        r2 = resolve_macro_placements(p2, core_bbox, site)
        for a, b in zip(r1, r2, strict=True):
            assert a.instance == b.instance
            assert a.x_um == pytest.approx(b.x_um)
            assert a.y_um == pytest.approx(b.y_um)


# ---------------------------------------------------------------------------
# Property Test
# ---------------------------------------------------------------------------


class TestPropertyGridSnap:
    """test_property_grid_snap_always_valid -- for any float coordinate,
    snap produces a value that is a clean multiple of site dimensions.

    Uses simple iteration instead of hypothesis.
    """

    def test_property_grid_snap_always_valid(self, site: PlacementSite) -> None:
        """For 200 random coordinates, snap produces valid grid multiples."""
        rng = random.Random(42)
        for _ in range(200):
            x = rng.uniform(-1000.0, 5000.0)
            y = rng.uniform(-1000.0, 5000.0)
            sx, sy = snap_to_grid(x, y, site, dbu_per_um=1000.0)

            # After snapping, coordinate should be a multiple of site dimension
            # within DBU precision (1/1000 um)
            x_remainder = (sx / site.width_um) - round(sx / site.width_um)
            y_remainder = (sy / site.height_um) - round(sy / site.height_um)
            assert abs(x_remainder) < 1e-6, (
                f"x={x} -> sx={sx} not a clean multiple of {site.width_um}"
            )
            assert abs(y_remainder) < 1e-6, (
                f"y={y} -> sy={sy} not a clean multiple of {site.height_um}"
            )

            # DBU roundtrip: coordinate * 1000 should be (very close to) integer
            assert sx * 1000 == pytest.approx(round(sx * 1000), abs=1e-9)
            assert sy * 1000 == pytest.approx(round(sy * 1000), abs=1e-9)

    def test_property_grid_snap_floor_always_leq(
        self, site: PlacementSite
    ) -> None:
        """Floor snapped value is always <= original."""
        rng = random.Random(123)
        for _ in range(100):
            x = rng.uniform(0.0, 5000.0)
            y = rng.uniform(0.0, 5000.0)
            sx, sy = snap_to_grid(x, y, site, rounding="floor")
            assert sx <= x + 1e-9
            assert sy <= y + 1e-9

    def test_property_grid_snap_ceil_always_geq(
        self, site: PlacementSite
    ) -> None:
        """Ceil snapped value is always >= original."""
        rng = random.Random(456)
        for _ in range(100):
            x = rng.uniform(0.0, 5000.0)
            y = rng.uniform(0.0, 5000.0)
            sx, sy = snap_to_grid(x, y, site, rounding="ceil")
            assert sx >= x - 1e-9
            assert sy >= y - 1e-9
