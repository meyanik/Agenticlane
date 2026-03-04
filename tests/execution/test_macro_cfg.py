"""Tests for MACRO_PLACEMENT_CFG materialization (P4.4).

Verifies:
- format_macro_cfg produces correct LibreLane MACRO_PLACEMENT_CFG format
- write_macro_cfg creates/skips files correctly
- parse_macro_cfg round-trips with format_macro_cfg
- PatchMaterializer steps 4+5 integrate with macro resolution and CFG writing
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agenticlane.execution.grid_snap import (
    CoreBBox,
    PlacementSite,
    ResolvedMacro,
)
from agenticlane.execution.macro_cfg import (
    format_macro_cfg,
    parse_macro_cfg,
    write_macro_cfg,
)
from agenticlane.execution.patch_materialize import (
    EarlyRejectionError,
    PatchMaterializer,
)
from agenticlane.schemas.patch import MacroPlacement, Patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_macro(
    instance: str = "U_SRAM_0",
    x: float = 100.0,
    y: float = 200.0,
    orientation: str = "N",
) -> ResolvedMacro:
    return ResolvedMacro(
        instance=instance,
        x_um=x,
        y_um=y,
        orientation=orientation,
    )


def _make_patch_with_macros(
    macros: list[MacroPlacement] | None = None,
    patch_id: str = "test-macro-001",
) -> Patch:
    return Patch(
        patch_id=patch_id,
        stage="FLOORPLAN",
        types=["macro_placements"] if macros else [],
        macro_placements=macros or [],
    )


# ---------------------------------------------------------------------------
# format_macro_cfg tests
# ---------------------------------------------------------------------------


class TestFormatMacroCfg:
    """Test the MACRO_PLACEMENT_CFG text format generation."""

    def test_single_macro(self) -> None:
        macros = [_make_macro("U_SRAM_0", 100.0, 200.0, "N")]
        result = format_macro_cfg(macros)
        assert result == "U_SRAM_0 100.000 200.000 N\n"

    def test_multiple_macros_sorted(self) -> None:
        macros = [
            _make_macro("U_SRAM_1", 500.0, 600.0, "FN"),
            _make_macro("U_ROM_0", 300.0, 400.0, "S"),
            _make_macro("U_SRAM_0", 100.0, 200.0, "N"),
        ]
        result = format_macro_cfg(macros)
        lines = result.strip().splitlines()
        assert len(lines) == 3
        # Sorted by instance name
        assert lines[0].startswith("U_ROM_0")
        assert lines[1].startswith("U_SRAM_0")
        assert lines[2].startswith("U_SRAM_1")

    def test_empty_returns_empty(self) -> None:
        assert format_macro_cfg([]) == ""

    def test_coordinates_3_decimals(self) -> None:
        macros = [_make_macro("M0", 1.23456, 7.89012, "E")]
        result = format_macro_cfg(macros)
        assert "1.235" in result  # rounded to 3 decimals
        assert "7.890" in result

    def test_trailing_newline(self) -> None:
        macros = [_make_macro()]
        result = format_macro_cfg(macros)
        assert result.endswith("\n")


# ---------------------------------------------------------------------------
# write_macro_cfg tests
# ---------------------------------------------------------------------------


class TestWriteMacroCfg:
    """Test writing MACRO_PLACEMENT_CFG to disk."""

    def test_creates_file(self, tmp_path: Path) -> None:
        macros = [_make_macro("U_SRAM_0", 100.0, 200.0, "N")]
        path = write_macro_cfg(macros, tmp_path)
        assert path is not None
        assert path.exists()
        assert path.name == "macro_placement.cfg"

    def test_empty_returns_none(self, tmp_path: Path) -> None:
        path = write_macro_cfg([], tmp_path)
        assert path is None
        # No file should be created
        assert not (tmp_path / "macro_placement.cfg").exists()

    def test_custom_filename(self, tmp_path: Path) -> None:
        macros = [_make_macro()]
        path = write_macro_cfg(macros, tmp_path, filename="custom.cfg")
        assert path is not None
        assert path.name == "custom.cfg"

    def test_file_content_matches_format(self, tmp_path: Path) -> None:
        macros = [
            _make_macro("B_MACRO", 50.0, 60.0, "S"),
            _make_macro("A_MACRO", 10.0, 20.0, "N"),
        ]
        path = write_macro_cfg(macros, tmp_path)
        assert path is not None
        content = path.read_text()
        expected = format_macro_cfg(macros)
        assert content == expected


# ---------------------------------------------------------------------------
# parse_macro_cfg tests
# ---------------------------------------------------------------------------


class TestParseMacroCfg:
    """Test parsing MACRO_PLACEMENT_CFG back into data."""

    def test_roundtrip(self) -> None:
        macros = [
            _make_macro("U_SRAM_0", 100.0, 200.0, "N"),
            _make_macro("U_SRAM_1", 500.0, 600.0, "FN"),
        ]
        content = format_macro_cfg(macros)
        parsed = parse_macro_cfg(content)
        assert len(parsed) == 2
        assert parsed[0]["instance"] == "U_SRAM_0"
        assert parsed[0]["x_um"] == 100.0
        assert parsed[0]["y_um"] == 200.0
        assert parsed[0]["orientation"] == "N"
        assert parsed[1]["instance"] == "U_SRAM_1"

    def test_ignores_comments_and_blanks(self) -> None:
        content = "# Header comment\n\nU_M0 10.000 20.000 N\n\n# Footer\n"
        parsed = parse_macro_cfg(content)
        assert len(parsed) == 1
        assert parsed[0]["instance"] == "U_M0"

    def test_empty_string(self) -> None:
        assert parse_macro_cfg("") == []

    def test_golden_macro_cfg(self) -> None:
        """Known placements produce exact expected CFG content."""
        macros = [
            _make_macro("U_ROM_0", 300.0, 400.0, "S"),
            _make_macro("U_SRAM_0", 100.0, 200.0, "N"),
            _make_macro("U_SRAM_1", 500.0, 600.0, "FN"),
        ]
        result = format_macro_cfg(macros)
        expected = (
            "U_ROM_0 300.000 400.000 S\n"
            "U_SRAM_0 100.000 200.000 N\n"
            "U_SRAM_1 500.000 600.000 FN\n"
        )
        assert result == expected


# ---------------------------------------------------------------------------
# PatchMaterializer integration tests
# ---------------------------------------------------------------------------


class TestMaterializerMacroIntegration:
    """Test PatchMaterializer steps 4+5 with macro resolution."""

    @pytest.fixture()
    def core_bbox(self) -> CoreBBox:
        return CoreBBox(x_min=0.0, y_min=0.0, x_max=1000.0, y_max=1000.0)

    @pytest.fixture()
    def site(self) -> PlacementSite:
        return PlacementSite(width_um=0.46, height_um=2.72)

    def test_materializer_writes_cfg(
        self, tmp_path: Path, core_bbox: CoreBBox, site: PlacementSite
    ) -> None:
        """When macros are present and placement info configured, CFG is written."""
        macros = [
            MacroPlacement(instance="U_SRAM_0", x_um=100.0, y_um=200.0, orientation="N"),
        ]
        patch = _make_patch_with_macros(macros)

        materializer = PatchMaterializer(
            core_bbox=core_bbox,
            placement_site=site,
            known_instances={"U_SRAM_0"},
        )
        attempt_dir = tmp_path / "attempt_001"

        ctx = materializer.materialize(
            patch=patch,
            attempt_dir=attempt_dir,
            stage_name="FLOORPLAN",
        )

        assert "macro_resolution" in ctx.steps_completed
        assert "grid_snap" in ctx.steps_completed
        assert ctx.macro_cfg_path is not None
        assert ctx.macro_cfg_path.exists()

        # Verify CFG content is parseable
        content = ctx.macro_cfg_path.read_text()
        parsed = parse_macro_cfg(content)
        assert len(parsed) == 1
        assert parsed[0]["instance"] == "U_SRAM_0"

    def test_materializer_skips_when_no_macros(self, tmp_path: Path) -> None:
        """No macros → steps skipped."""
        patch = _make_patch_with_macros([])
        materializer = PatchMaterializer()
        attempt_dir = tmp_path / "attempt_001"

        ctx = materializer.materialize(
            patch=patch,
            attempt_dir=attempt_dir,
            stage_name="FLOORPLAN",
        )

        assert "macro_resolution_skipped" in ctx.steps_completed
        assert "grid_snap_skipped" in ctx.steps_completed
        assert ctx.macro_cfg_path is None

    def test_materializer_skips_without_placement_info(
        self, tmp_path: Path
    ) -> None:
        """Macros present but no core_bbox/site → skipped."""
        macros = [
            MacroPlacement(instance="U_SRAM_0", x_um=100.0, y_um=200.0),
        ]
        patch = _make_patch_with_macros(macros)

        # No core_bbox or placement_site
        materializer = PatchMaterializer()
        attempt_dir = tmp_path / "attempt_001"

        ctx = materializer.materialize(
            patch=patch,
            attempt_dir=attempt_dir,
            stage_name="FLOORPLAN",
        )

        assert "macro_resolution_skipped" in ctx.steps_completed
        assert "grid_snap_skipped" in ctx.steps_completed

    def test_materializer_rejects_invalid_macro(
        self, tmp_path: Path, core_bbox: CoreBBox, site: PlacementSite
    ) -> None:
        """Invalid instance → EarlyRejectionError."""
        macros = [
            MacroPlacement(instance="NONEXISTENT", x_um=100.0, y_um=200.0),
        ]
        patch = _make_patch_with_macros(macros)

        materializer = PatchMaterializer(
            core_bbox=core_bbox,
            placement_site=site,
            known_instances={"U_SRAM_0"},
        )
        attempt_dir = tmp_path / "attempt_001"

        with pytest.raises(EarlyRejectionError) as exc_info:
            materializer.materialize(
                patch=patch,
                attempt_dir=attempt_dir,
                stage_name="FLOORPLAN",
            )

        assert exc_info.value.rejection.reason_code == "macro_placement_error"
        assert exc_info.value.rejection.offending_channel == "macro_placements"

    def test_materializer_rejects_bad_orientation(
        self, tmp_path: Path, core_bbox: CoreBBox, site: PlacementSite
    ) -> None:
        """Invalid orientation → EarlyRejectionError."""
        macros = [
            MacroPlacement(instance="U_SRAM_0", x_um=100.0, y_um=200.0, orientation="X"),
        ]
        patch = _make_patch_with_macros(macros)

        materializer = PatchMaterializer(
            core_bbox=core_bbox,
            placement_site=site,
            known_instances={"U_SRAM_0"},
        )
        attempt_dir = tmp_path / "attempt_001"

        with pytest.raises(EarlyRejectionError) as exc_info:
            materializer.materialize(
                patch=patch,
                attempt_dir=attempt_dir,
                stage_name="FLOORPLAN",
            )

        assert exc_info.value.rejection.reason_code == "macro_placement_error"

    def test_hint_resolution_and_snap(
        self, tmp_path: Path, core_bbox: CoreBBox, site: PlacementSite
    ) -> None:
        """Macro with location_hint gets resolved and snapped."""
        macros = [
            MacroPlacement(instance="U_SRAM_0", location_hint="CENTER"),
        ]
        patch = _make_patch_with_macros(macros)

        materializer = PatchMaterializer(
            core_bbox=core_bbox,
            placement_site=site,
            known_instances={"U_SRAM_0"},
        )
        attempt_dir = tmp_path / "attempt_001"

        ctx = materializer.materialize(
            patch=patch,
            attempt_dir=attempt_dir,
            stage_name="FLOORPLAN",
        )

        assert "macro_resolution" in ctx.steps_completed
        assert "grid_snap" in ctx.steps_completed
        assert ctx.macro_cfg_path is not None

        # Check the resolved coordinates are snapped
        content = ctx.macro_cfg_path.read_text()
        parsed = parse_macro_cfg(content)
        assert len(parsed) == 1
        # CENTER hint = 50% of 1000 = 500.0 -- should be snapped to grid
        x = parsed[0]["x_um"]
        assert isinstance(x, float)
        # x should be near 500.0, snapped to 0.46um grid
        assert 499.0 < x < 501.0
