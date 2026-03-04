"""P4.3 Macro Placement Worker integration tests.

Tests that a worker agent can propose macro_placements in a patch, and that
the grid snap pipeline integrates with the placement resolution correctly.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agenticlane.agents.mock_llm import MockLLMProvider
from agenticlane.agents.workers.base import WorkerAgent
from agenticlane.agents.workers.floorplan import FloorplanWorker
from agenticlane.config.models import AgenticLaneConfig
from agenticlane.execution.grid_snap import (
    CoreBBox,
    PlacementSite,
    detect_collisions,
    resolve_macro_placements,
)
from agenticlane.schemas.evidence import EvidencePack
from agenticlane.schemas.metrics import MetricsPayload
from agenticlane.schemas.patch import MacroPlacement, Patch


def _make_metrics(**kwargs):  # type: ignore[no-untyped-def]
    defaults = dict(
        run_id="test",
        branch_id="B0",
        stage="FLOORPLAN",
        attempt=1,
        execution_status="success",
    )
    defaults.update(kwargs)
    return MetricsPayload(**defaults)


def _make_evidence(**kwargs):  # type: ignore[no-untyped-def]
    defaults = dict(stage="FLOORPLAN", attempt=1, execution_status="success")
    defaults.update(kwargs)
    return EvidencePack(**defaults)


class TestWorkerProposesMacroPlacements:
    """test_worker_proposes_macro_placements -- MockLLMProvider returns a
    Patch with macro_placements, worker processes it.
    """

    @pytest.fixture
    def mock_provider(self, tmp_path: Path) -> MockLLMProvider:
        return MockLLMProvider(log_dir=tmp_path)

    @pytest.fixture
    def config(self) -> AgenticLaneConfig:
        return AgenticLaneConfig()

    @pytest.mark.asyncio
    async def test_worker_proposes_macro_placements(
        self, mock_provider: MockLLMProvider, config: AgenticLaneConfig
    ) -> None:
        """Worker returns a Patch that includes macro_placements."""
        patch = Patch(
            patch_id="macro_test_001",
            stage="FLOORPLAN",
            types=["macro_placements"],
            macro_placements=[
                MacroPlacement(
                    instance="U_SRAM_0",
                    location_hint="NW",
                    orientation="N",
                ),
                MacroPlacement(
                    instance="U_SRAM_1",
                    x_um=800.0,
                    y_um=200.0,
                    orientation="FN",
                ),
            ],
            rationale="Place SRAMs in NW corner and near SE for balanced routing.",
        )
        mock_provider.set_response(patch)

        worker = FloorplanWorker(mock_provider, "FLOORPLAN", config)
        result = await worker.propose_patch(_make_metrics(), _make_evidence())

        assert result is not None
        assert isinstance(result, Patch)
        assert len(result.macro_placements) == 2
        assert result.macro_placements[0].instance == "U_SRAM_0"
        assert result.macro_placements[0].location_hint == "NW"
        assert result.macro_placements[1].instance == "U_SRAM_1"
        assert result.macro_placements[1].x_um == 800.0
        assert result.macro_placements[1].y_um == 200.0
        assert result.macro_placements[1].orientation == "FN"

    @pytest.mark.asyncio
    async def test_worker_patch_types_include_macro_placements(
        self, mock_provider: MockLLMProvider, config: AgenticLaneConfig
    ) -> None:
        """Patch.types includes 'macro_placements' channel."""
        patch = Patch(
            patch_id="macro_test_002",
            stage="FLOORPLAN",
            types=["config_vars", "macro_placements"],
            config_vars={"FP_CORE_UTIL": 45},
            macro_placements=[
                MacroPlacement(instance="U_SRAM_0", location_hint="CENTER"),
            ],
            rationale="Combined config + macro patch.",
        )
        mock_provider.set_response(patch)

        worker = WorkerAgent(mock_provider, "FLOORPLAN", config)
        result = await worker.propose_patch(_make_metrics(), _make_evidence())

        assert result is not None
        assert "macro_placements" in result.types
        assert "config_vars" in result.types
        assert len(result.macro_placements) == 1


class TestGridSnapAppliedInPipeline:
    """test_grid_snap_applied_in_pipeline -- Full resolve_macro_placements
    with snap verifies grid alignment.
    """

    def test_grid_snap_applied_in_pipeline(self) -> None:
        """Resolve placements from a Patch and verify grid snap was applied."""
        core_bbox = CoreBBox(
            x_min=0.0, y_min=0.0, x_max=1000.0, y_max=1000.0
        )
        site = PlacementSite(width_um=0.46, height_um=2.72)

        placements = [
            MacroPlacement(
                instance="U_SRAM_0",
                location_hint="NW",
                orientation="N",
            ),
            MacroPlacement(
                instance="U_SRAM_1",
                x_um=500.5,
                y_um=250.3,
                orientation="FN",
            ),
        ]

        result = resolve_macro_placements(
            placements,
            core_bbox,
            site,
            dbu_per_um=1000.0,
            rounding="nearest",
            snap_enabled=True,
        )

        assert len(result) == 2

        for m in result:
            # Every resolved coordinate must be DBU-clean
            assert m.x_um * 1000 == pytest.approx(
                round(m.x_um * 1000), abs=1e-9
            ), f"{m.instance}: x_um not DBU-clean"
            assert m.y_um * 1000 == pytest.approx(
                round(m.y_um * 1000), abs=1e-9
            ), f"{m.instance}: y_um not DBU-clean"

            # Every coordinate must be a multiple of the site dimension
            x_remainder = (m.x_um / site.width_um) - round(
                m.x_um / site.width_um
            )
            y_remainder = (m.y_um / site.height_um) - round(
                m.y_um / site.height_um
            )
            assert abs(x_remainder) < 1e-6, (
                f"{m.instance}: x not on site grid"
            )
            assert abs(y_remainder) < 1e-6, (
                f"{m.instance}: y not on site grid"
            )

    def test_grid_snap_with_macro_sizes_and_collision(self) -> None:
        """Pipeline resolves collisions for co-located macros."""
        core_bbox = CoreBBox(
            x_min=0.0, y_min=0.0, x_max=2000.0, y_max=2000.0
        )
        site = PlacementSite(width_um=0.46, height_um=2.72)
        sizes = {
            "U_SRAM_0": (80.0, 80.0),
            "U_SRAM_1": (80.0, 80.0),
        }

        placements = [
            MacroPlacement(
                instance="U_SRAM_0", location_hint="CENTER", orientation="N"
            ),
            MacroPlacement(
                instance="U_SRAM_1", location_hint="CENTER", orientation="N"
            ),
        ]

        result = resolve_macro_placements(
            placements,
            core_bbox,
            site,
            macro_sizes=sizes,
            max_iterations=5,
        )

        assert len(result) == 2
        collisions = detect_collisions(result)
        assert collisions == [], (
            "Collision resolution should have separated the macros"
        )
