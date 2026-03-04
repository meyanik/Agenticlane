"""Tests for dashboard (P5.10)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def _has_fastapi() -> bool:
    try:
        import fastapi  # noqa: F401
        import httpx  # noqa: F401

        return True
    except ImportError:
        return False


def _write_manifest(runs_dir: Path, run_id: str) -> None:
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_id": run_id,
        "best_branch_id": "B0",
        "best_composite_score": 0.85,
        "branches": {
            "B0": {"status": "completed", "best_score": 0.85},
            "B1": {"status": "pruned", "best_score": 0.3},
        },
        "decisions": [
            {
                "stage": "FLOORPLAN",
                "branch_id": "B0",
                "attempt": 1,
                "action": "accept",
                "composite_score": 0.85,
            },
        ],
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest))


class TestDashboard:
    def test_dashboard_import(self) -> None:
        """Dashboard module is importable."""
        from agenticlane.reporting.dashboard import create_dashboard_app

        assert callable(create_dashboard_app)

    @pytest.mark.skipif(
        not _has_fastapi(),
        reason="FastAPI not installed",
    )
    def test_dashboard_server_starts(self, tmp_path: Path) -> None:
        from agenticlane.reporting.dashboard import create_dashboard_app

        app = create_dashboard_app(tmp_path)
        assert app is not None
        assert app.title == "AgenticLane Dashboard"

    @pytest.mark.skipif(
        not _has_fastapi(),
        reason="FastAPI not installed",
    )
    @pytest.mark.asyncio
    async def test_dashboard_index_page_loads(self, tmp_path: Path) -> None:
        from httpx import ASGITransport, AsyncClient

        from agenticlane.reporting.dashboard import create_dashboard_app

        _write_manifest(tmp_path, "run_001")
        app = create_dashboard_app(tmp_path)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/")
            assert response.status_code == 200
            assert "AgenticLane Dashboard" in response.text

    @pytest.mark.skipif(
        not _has_fastapi(),
        reason="FastAPI not installed",
    )
    @pytest.mark.asyncio
    async def test_dashboard_branch_timeline(self, tmp_path: Path) -> None:
        from httpx import ASGITransport, AsyncClient

        from agenticlane.reporting.dashboard import create_dashboard_app

        _write_manifest(tmp_path, "run_001")
        app = create_dashboard_app(tmp_path)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/runs/run_001/branches")
            assert response.status_code == 200
            data = response.json()
            assert "B0" in data["branches"]

    @pytest.mark.skipif(
        not _has_fastapi(),
        reason="FastAPI not installed",
    )
    @pytest.mark.asyncio
    async def test_dashboard_metrics_plots(self, tmp_path: Path) -> None:
        from httpx import ASGITransport, AsyncClient

        from agenticlane.reporting.dashboard import create_dashboard_app

        _write_manifest(tmp_path, "run_001")
        app = create_dashboard_app(tmp_path)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/runs/run_001/metrics")
            assert response.status_code == 200
            data = response.json()
            assert "branch_scores" in data

    @pytest.mark.skipif(
        not _has_fastapi(),
        reason="FastAPI not installed",
    )
    def test_dashboard_readonly(self, tmp_path: Path) -> None:
        """POST endpoints only on run-management routes."""
        from agenticlane.reporting.dashboard import create_dashboard_app

        app = create_dashboard_app(tmp_path)
        # Run management endpoints are allowed to have POST
        allowed_post = {"/api/runs/start", "/api/runs/{run_id}/stop"}
        for route in app.routes:
            if hasattr(route, "methods"):
                methods = route.methods or set()
                path = getattr(route, "path", "")
                write_methods = methods.intersection({"POST", "PUT", "DELETE"})
                if write_methods and path not in allowed_post:
                    raise AssertionError(
                        f"Route {path} has non-readonly methods: {write_methods}"
                    )

    @pytest.mark.skipif(
        not _has_fastapi(),
        reason="FastAPI not installed",
    )
    @pytest.mark.asyncio
    async def test_dashboard_from_golden_data(self, tmp_path: Path) -> None:
        from httpx import ASGITransport, AsyncClient

        from agenticlane.reporting.dashboard import create_dashboard_app

        _write_manifest(tmp_path, "run_001")
        app = create_dashboard_app(tmp_path)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/runs")
            data = response.json()
            run_ids = [r["run_id"] if isinstance(r, dict) else r for r in data["runs"]]
            assert "run_001" in run_ids
