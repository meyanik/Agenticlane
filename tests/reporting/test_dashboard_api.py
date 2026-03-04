"""Tests for the dashboard REST API endpoints."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _has_fastapi() -> bool:
    try:
        import fastapi  # noqa: F401
        return True
    except ImportError:
        return False


def _write_run(runs_dir: Path, run_id: str) -> None:
    """Create a minimal run with stages, attempts, and all JSON artifacts."""
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "manifest.json").write_text(json.dumps({
        "run_id": run_id,
        "flow_mode": "flat",
        "best_composite_score": 0.75,
        "best_branch_id": "B0",
        "total_stages": 3,
        "total_attempts": 4,
        "duration_seconds": 60,
        "start_time": "2026-03-01T12:00:00Z",
        "random_seed": 42,
        "branches": {"B0": {"status": "completed", "best_score": 0.75, "stages_completed": 3}},
        "decisions": [
            {"stage": "SYNTH", "branch_id": "B0", "attempt": 1, "action": "accept", "composite_score": 0.7, "reason": "OK"},
        ],
    }))

    # Create stages with attempts
    for stage in ["SYNTH", "FLOORPLAN"]:
        for attempt in [0, 1]:
            att_dir = run_dir / "branches" / "B0" / "stages" / stage / f"attempt_{attempt:03d}"
            att_dir.mkdir(parents=True, exist_ok=True)
            (att_dir / "metrics.json").write_text(json.dumps({
                "schema_version": 3, "run_id": run_id, "branch_id": "B0",
                "stage": stage, "attempt": attempt, "execution_status": "success",
                "runtime": {"stage_seconds": 2.0}, "timing": None,
                "physical": None, "route": None, "signoff": None, "power": None,
                "synthesis": None, "missing_metrics": [],
            }))
            (att_dir / "evidence.json").write_text(json.dumps({
                "stage": stage, "attempt": attempt, "execution_status": "success",
                "errors": [], "warnings": [], "spatial_hotspots": [],
            }))
            (att_dir / "composite_score.json").write_text(json.dumps({"score": 0.5 + attempt * 0.1}))
            if attempt == 1:
                (att_dir / "checkpoint.json").write_text(json.dumps({
                    "stage": stage, "attempt": attempt, "status": "passed",
                }))
                (att_dir / "judge_votes.json").write_text(json.dumps({
                    "votes": [{"judge_id": "j0", "model": "test", "vote": "PASS", "confidence": 0.9, "blocking_issues": [], "reason": "OK"}],
                    "result": "PASS", "confidence": 0.9, "blocking_issues": [],
                }))
                (att_dir / "patch.json").write_text(json.dumps({
                    "patch_id": f"p_{stage}_{attempt}", "stage": stage,
                    "types": ["config_vars"], "config_vars": {"TEST": "1"},
                    "rationale": "Test patch",
                }))


@pytest.fixture()
def runs_dir(tmp_path: Path) -> Path:
    _write_run(tmp_path, "run_api_001")
    return tmp_path


@pytest.mark.skipif(not _has_fastapi(), reason="FastAPI not installed")
class TestDashboardAPI:
    @pytest.mark.asyncio
    async def test_list_runs_with_metadata(self, runs_dir: Path) -> None:
        from httpx import ASGITransport, AsyncClient

        from agenticlane.reporting.dashboard import create_dashboard_app

        app = create_dashboard_app(runs_dir)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/runs")
            assert response.status_code == 200
            data = response.json()
            runs = data["runs"]
            assert len(runs) == 1
            assert runs[0]["run_id"] == "run_api_001"
            assert runs[0]["flow_mode"] == "flat"
            assert runs[0]["best_composite_score"] == 0.75

    @pytest.mark.asyncio
    async def test_get_stages(self, runs_dir: Path) -> None:
        from httpx import ASGITransport, AsyncClient

        from agenticlane.reporting.dashboard import create_dashboard_app

        app = create_dashboard_app(runs_dir)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/runs/run_api_001/stages")
            assert response.status_code == 200
            data = response.json()
            stages = data["stages"]
            assert len(stages) == 10  # All 10 stages returned
            synth = next(s for s in stages if s["stage"] == "SYNTH")
            assert synth["status"] == "passed"
            assert synth["attempts_count"] == 2

    @pytest.mark.asyncio
    async def test_get_stage_attempts(self, runs_dir: Path) -> None:
        from httpx import ASGITransport, AsyncClient

        from agenticlane.reporting.dashboard import create_dashboard_app

        app = create_dashboard_app(runs_dir)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/runs/run_api_001/stages/SYNTH/attempts")
            assert response.status_code == 200
            data = response.json()
            assert data["stage"] == "SYNTH"
            assert len(data["attempts"]) == 2

    @pytest.mark.asyncio
    async def test_get_attempt_detail(self, runs_dir: Path) -> None:
        from httpx import ASGITransport, AsyncClient

        from agenticlane.reporting.dashboard import create_dashboard_app

        app = create_dashboard_app(runs_dir)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/runs/run_api_001/stages/SYNTH/attempts/1")
            assert response.status_code == 200
            data = response.json()
            assert data["stage"] == "SYNTH"
            assert data["attempt"] == 1
            assert data["metrics"] is not None
            assert data["judge_votes"] is not None
            assert data["patch"] is not None

    @pytest.mark.asyncio
    async def test_get_attempt_detail_404(self, runs_dir: Path) -> None:
        from httpx import ASGITransport, AsyncClient

        from agenticlane.reporting.dashboard import create_dashboard_app

        app = create_dashboard_app(runs_dir)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/runs/run_api_001/stages/SYNTH/attempts/99")
            assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_patches(self, runs_dir: Path) -> None:
        from httpx import ASGITransport, AsyncClient

        from agenticlane.reporting.dashboard import create_dashboard_app

        app = create_dashboard_app(runs_dir)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/runs/run_api_001/patches")
            assert response.status_code == 200
            data = response.json()
            patches = data["patches"]
            assert len(patches) >= 1  # At least our test patches

    @pytest.mark.asyncio
    async def test_get_agent_log(self, runs_dir: Path) -> None:
        from httpx import ASGITransport, AsyncClient

        from agenticlane.reporting.dashboard import create_dashboard_app

        app = create_dashboard_app(runs_dir)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/runs/run_api_001/agents")
            assert response.status_code == 200
            data = response.json()
            assert "llm_calls" in data
            assert "decisions" in data
            assert len(data["decisions"]) == 1

    @pytest.mark.asyncio
    async def test_get_stage_info(self, runs_dir: Path) -> None:
        from httpx import ASGITransport, AsyncClient

        from agenticlane.reporting.dashboard import create_dashboard_app

        app = create_dashboard_app(runs_dir)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/config/stages")
            assert response.status_code == 200
            data = response.json()
            assert len(data["stages"]) == 10
            assert "SYNTH" in data["descriptions"]

    @pytest.mark.asyncio
    async def test_get_models(self, runs_dir: Path) -> None:
        from httpx import ASGITransport, AsyncClient

        from agenticlane.reporting.dashboard import create_dashboard_app

        app = create_dashboard_app(runs_dir)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/config/models")
            assert response.status_code == 200
            data = response.json()
            assert "models" in data
            # Cloud models always present
            model_ids = [m["id"] for m in data["models"]]
            assert "gemini/gemini-2.5-pro" in model_ids

    @pytest.mark.asyncio
    async def test_get_active_runs_empty(self, runs_dir: Path) -> None:
        from httpx import ASGITransport, AsyncClient

        from agenticlane.reporting.dashboard import create_dashboard_app

        app = create_dashboard_app(runs_dir)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/runs/active")
            assert response.status_code == 200
            assert response.json()["active"] == []

    @pytest.mark.asyncio
    async def test_sse_endpoint_exists(self, runs_dir: Path) -> None:
        from agenticlane.reporting.dashboard import create_dashboard_app

        app = create_dashboard_app(runs_dir)

        # Verify SSE route is registered (streaming endpoints hang, so don't call them directly)
        routes = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/api/runs/{run_id}/events" in routes
        assert "/api/events" in routes

    @pytest.mark.asyncio
    async def test_legacy_html_fallback(self, runs_dir: Path) -> None:
        from httpx import ASGITransport, AsyncClient

        from agenticlane.reporting.dashboard import create_dashboard_app

        app = create_dashboard_app(runs_dir)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/legacy")
            assert response.status_code == 200
            assert "AgenticLane" in response.text
