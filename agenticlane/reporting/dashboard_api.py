"""REST API endpoints for the AgenticLane dashboard.

Provides all ``/api/*`` routes consumed by the React frontend.
Existing endpoints are preserved for backward compatibility;
new endpoints expose per-stage / per-attempt data, agent logs,
patches, config introspection, and run management.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:
    from fastapi import APIRouter, HTTPException
    from fastapi.responses import JSONResponse

    _HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    _HAS_FASTAPI = False

# Stage ordering for presentation.
STAGE_ORDER = [
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


# ------------------------------------------------------------------ #
# Helpers (shared with dashboard.py)
# ------------------------------------------------------------------ #


def list_runs(runs_dir: Path) -> list[str]:
    """List available run IDs."""
    if not runs_dir.exists():
        return []
    return sorted(
        d.name
        for d in runs_dir.iterdir()
        if d.is_dir() and (d / "manifest.json").exists()
    )


def load_manifest(runs_dir: Path, run_id: str) -> dict[str, Any] | None:
    """Load manifest.json for a run."""
    path = runs_dir / run_id / "manifest.json"
    if not path.exists():
        return None
    result: dict[str, Any] = json.loads(path.read_text())
    return result


def collect_evidence(runs_dir: Path, run_id: str) -> list[dict[str, Any]]:
    """Collect all evidence_pack.json / evidence.json files from a run."""
    run_dir = runs_dir / run_id
    packs: list[dict[str, Any]] = []
    for name in ("evidence_pack.json", "evidence.json"):
        for ep in sorted(run_dir.rglob(name)):
            try:
                packs.append(json.loads(ep.read_text()))
            except (json.JSONDecodeError, OSError):
                continue
    return packs


def collect_rejections(runs_dir: Path, run_id: str) -> list[dict[str, Any]]:
    """Collect PatchRejected events."""
    run_dir = runs_dir / run_id
    rejections: list[dict[str, Any]] = []
    for f in sorted(run_dir.rglob("patch_rejected*.json")):
        try:
            rejections.append(json.loads(f.read_text()))
        except (json.JSONDecodeError, OSError):
            continue
    return rejections


def _load_json(path: Path) -> dict[str, Any] | None:
    """Load a JSON file, return None on failure."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())  # type: ignore[no-any-return]
    except (json.JSONDecodeError, OSError):
        return None


# ------------------------------------------------------------------ #
# Router factory
# ------------------------------------------------------------------ #


def create_api_router(
    runs_dir: Path,
    run_manager: Any = None,
    event_bus: Any = None,
    examples_dir: Optional[Path] = None,
) -> Any:
    """Create the FastAPI APIRouter with all endpoints.

    Parameters
    ----------
    runs_dir:
        Root directory containing run folders.
    run_manager:
        Optional :class:`DashboardRunManager` for starting/stopping runs.
    event_bus:
        Optional :class:`DashboardEventBus` for SSE streaming.
    examples_dir:
        Optional path to ``examples/`` directory for config browsing.
    """
    if not _HAS_FASTAPI:
        raise ImportError("FastAPI is required for the dashboard API.")

    router = APIRouter(prefix="/api")

    # ============================================================== #
    # Existing endpoints (backward compatible)
    # ============================================================== #

    @router.get("/runs")
    async def api_list_runs() -> JSONResponse:
        """List all runs with summary metadata."""
        run_ids = list_runs(runs_dir)
        summaries: list[dict[str, Any]] = []
        for rid in run_ids:
            manifest = load_manifest(runs_dir, rid)
            if manifest is None:
                summaries.append({"run_id": rid})
                continue
            summaries.append({
                "run_id": rid,
                "flow_mode": manifest.get("flow_mode", "flat"),
                "best_composite_score": manifest.get("best_composite_score"),
                "best_branch_id": manifest.get("best_branch_id"),
                "total_stages": manifest.get("total_stages", 0),
                "total_attempts": manifest.get("total_attempts", 0),
                "duration_seconds": manifest.get("duration_seconds"),
                "start_time": manifest.get("start_time"),
                "status": manifest.get("status", "completed"),
            })
        return JSONResponse(content={"runs": summaries})

    @router.get("/runs/{run_id}/manifest")
    async def api_get_manifest(run_id: str) -> JSONResponse:
        manifest = load_manifest(runs_dir, run_id)
        if manifest is None:
            raise HTTPException(status_code=404, detail="manifest not found")
        return JSONResponse(content=manifest)

    @router.get("/runs/{run_id}/branches")
    async def api_get_branches(run_id: str) -> JSONResponse:
        manifest = load_manifest(runs_dir, run_id)
        if manifest is None:
            raise HTTPException(status_code=404, detail="manifest not found")
        return JSONResponse(content={
            "branches": manifest.get("branches", {}),
            "best_branch_id": manifest.get("best_branch_id"),
        })

    @router.get("/runs/{run_id}/metrics")
    async def api_get_metrics(run_id: str) -> JSONResponse:
        manifest = load_manifest(runs_dir, run_id)
        if manifest is None:
            raise HTTPException(status_code=404, detail="manifest not found")
        decisions = manifest.get("decisions", [])
        branch_scores: dict[str, list[dict[str, Any]]] = {}
        for d in decisions:
            bid = d.get("branch_id", "unknown")
            if bid not in branch_scores:
                branch_scores[bid] = []
            branch_scores[bid].append({
                "stage": d.get("stage"),
                "attempt": d.get("attempt"),
                "score": d.get("composite_score"),
            })
        return JSONResponse(content={"branch_scores": branch_scores})

    @router.get("/runs/{run_id}/evidence")
    async def api_get_evidence(run_id: str) -> JSONResponse:
        evidence = collect_evidence(runs_dir, run_id)
        return JSONResponse(content={"evidence_packs": evidence})

    @router.get("/runs/{run_id}/rejections")
    async def api_get_rejections(run_id: str) -> JSONResponse:
        rejections = collect_rejections(runs_dir, run_id)
        return JSONResponse(content={"rejections": rejections})

    # ============================================================== #
    # New endpoints: stages / attempts / agents / patches
    # ============================================================== #

    @router.get("/runs/{run_id}/stages")
    async def api_get_stages(run_id: str) -> JSONResponse:
        """All stages with status and best metrics summary."""
        run_dir = runs_dir / run_id
        if not run_dir.exists():
            raise HTTPException(status_code=404, detail="run not found")

        stages: list[dict[str, Any]] = []
        for stage_name in STAGE_ORDER:
            stage_info: dict[str, Any] = {"stage": stage_name, "status": "pending"}
            # Find stage in first branch (B0 by default)
            for branch_dir in sorted(run_dir.glob("branches/*/stages")):
                stage_dir = branch_dir / stage_name
                if not stage_dir.exists():
                    continue
                attempts = sorted(stage_dir.glob("attempt_*"))
                stage_info["attempts_count"] = len(attempts)
                stage_info["branch_id"] = branch_dir.parent.name

                # Load best attempt metrics
                best_score = -1.0
                best_metrics = None
                passed = False
                for att_dir in attempts:
                    score_file = att_dir / "composite_score.json"
                    score_data = _load_json(score_file)
                    score = score_data.get("score", 0) if score_data else 0
                    if score > best_score:
                        best_score = score
                        best_metrics = _load_json(att_dir / "metrics.json")
                    checkpoint = _load_json(att_dir / "checkpoint.json")
                    if checkpoint and checkpoint.get("status") == "passed":
                        passed = True

                stage_info["status"] = "passed" if passed else "failed"
                stage_info["best_score"] = best_score if best_score >= 0 else None
                if best_metrics:
                    stage_info["execution_status"] = best_metrics.get(
                        "execution_status"
                    )
                    if best_metrics.get("timing"):
                        stage_info["timing"] = best_metrics["timing"]
                    if best_metrics.get("physical"):
                        stage_info["physical"] = best_metrics["physical"]
                    if best_metrics.get("signoff"):
                        stage_info["signoff"] = best_metrics["signoff"]
                    if best_metrics.get("power"):
                        stage_info["power"] = best_metrics["power"]
                break  # Only first matching branch

            stages.append(stage_info)
        return JSONResponse(content={"stages": stages})

    @router.get("/runs/{run_id}/stages/{stage}/attempts")
    async def api_get_stage_attempts(run_id: str, stage: str) -> JSONResponse:
        """All attempts for a specific stage."""
        run_dir = runs_dir / run_id
        if not run_dir.exists():
            raise HTTPException(status_code=404, detail="run not found")

        attempts: list[dict[str, Any]] = []
        for branch_dir in sorted(run_dir.glob("branches/*/stages")):
            stage_dir = branch_dir / stage
            if not stage_dir.exists():
                continue
            for att_dir in sorted(stage_dir.glob("attempt_*")):
                att_num = att_dir.name.replace("attempt_", "")
                att_info: dict[str, Any] = {
                    "attempt": att_num,
                    "branch_id": branch_dir.parent.name,
                }
                att_info["metrics"] = _load_json(att_dir / "metrics.json")
                att_info["composite_score"] = _load_json(
                    att_dir / "composite_score.json"
                )
                att_info["judge_votes"] = _load_json(
                    att_dir / "judge_votes.json"
                )
                att_info["checkpoint"] = _load_json(
                    att_dir / "checkpoint.json"
                )
                attempts.append(att_info)
            break
        return JSONResponse(content={"stage": stage, "attempts": attempts})

    @router.get("/runs/{run_id}/stages/{stage}/attempts/{attempt_num}")
    async def api_get_attempt_detail(
        run_id: str, stage: str, attempt_num: int
    ) -> JSONResponse:
        """Full detail for a single attempt."""
        run_dir = runs_dir / run_id
        if not run_dir.exists():
            raise HTTPException(status_code=404, detail="run not found")

        att_name = f"attempt_{attempt_num:03d}"
        for branch_dir in sorted(run_dir.glob("branches/*/stages")):
            att_dir = branch_dir / stage / att_name
            if not att_dir.exists():
                continue
            detail: dict[str, Any] = {
                "run_id": run_id,
                "stage": stage,
                "attempt": attempt_num,
                "branch_id": branch_dir.parent.name,
                "metrics": _load_json(att_dir / "metrics.json"),
                "evidence": _load_json(att_dir / "evidence.json"),
                "patch": _load_json(att_dir / "patch.json"),
                "judge_votes": _load_json(att_dir / "judge_votes.json"),
                "composite_score": _load_json(
                    att_dir / "composite_score.json"
                ),
                "checkpoint": _load_json(att_dir / "checkpoint.json"),
                "lessons_learned": _load_json(
                    att_dir / "lessons_learned.json"
                ),
            }
            return JSONResponse(content=detail)

        raise HTTPException(status_code=404, detail="attempt not found")

    @router.get("/runs/{run_id}/agents")
    async def api_get_agent_log(run_id: str) -> JSONResponse:
        """Aggregated agent activity log parsed from structured JSONL logs."""
        run_dir = runs_dir / run_id
        if not run_dir.exists():
            raise HTTPException(status_code=404, detail="run not found")

        log_entries: list[dict[str, Any]] = []
        # Try to find LLM call logs
        for log_path in sorted(run_dir.rglob("llm_calls.jsonl")):
            try:
                with open(log_path) as fh:
                    for line in fh:
                        line = line.strip()
                        if line:
                            log_entries.append(json.loads(line))
            except (json.JSONDecodeError, OSError):
                continue

        # Also collect decision log from manifest
        manifest = load_manifest(runs_dir, run_id)
        decisions = manifest.get("decisions", []) if manifest else []

        return JSONResponse(content={
            "llm_calls": log_entries,
            "decisions": decisions,
        })

    @router.get("/runs/{run_id}/patches")
    async def api_get_patches(run_id: str) -> JSONResponse:
        """All patches across all stages."""
        run_dir = runs_dir / run_id
        if not run_dir.exists():
            raise HTTPException(status_code=404, detail="run not found")

        patches: list[dict[str, Any]] = []
        for patch_path in sorted(run_dir.rglob("patch.json")):
            patch_data = _load_json(patch_path)
            if patch_data:
                # Add context from path
                parts = patch_path.relative_to(run_dir).parts
                patch_data["_path"] = str(patch_path.relative_to(run_dir))
                if len(parts) >= 4:
                    patch_data["_branch"] = parts[1]
                    patch_data["_stage"] = parts[3]
                    patch_data["_attempt"] = parts[4] if len(parts) > 4 else ""
                patches.append(patch_data)
        return JSONResponse(content={"patches": patches})

    # ============================================================== #
    # Config / introspection endpoints
    # ============================================================== #

    @router.get("/config/models")
    async def api_get_available_models() -> JSONResponse:
        """Query available models from LM Studio or return known models."""
        models: list[dict[str, str]] = []
        # Try LM Studio local API
        try:
            import urllib.request

            lm_studio_url = os.environ.get(
                "LM_STUDIO_URL", "http://127.0.0.1:1234"
            )
            req = urllib.request.Request(
                f"{lm_studio_url}/v1/models",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read())
                for m in data.get("data", []):
                    models.append({
                        "id": m.get("id", ""),
                        "provider": "local",
                        "label": m.get("id", ""),
                    })
        except Exception:  # noqa: BLE001
            pass

        # Always include known cloud models
        cloud_models = [
            {"id": "gemini/gemini-2.5-pro", "provider": "google", "label": "Gemini 2.5 Pro"},
            {"id": "gemini/gemini-2.5-flash", "provider": "google", "label": "Gemini 2.5 Flash"},
            {"id": "anthropic/claude-sonnet-4-6", "provider": "anthropic", "label": "Claude Sonnet 4.6"},
            {"id": "anthropic/claude-opus-4-6", "provider": "anthropic", "label": "Claude Opus 4.6"},
            {"id": "openai/gpt-4o", "provider": "openai", "label": "GPT-4o"},
        ]
        models.extend(cloud_models)
        return JSONResponse(content={"models": models})

    @router.get("/config/examples")
    async def api_get_examples() -> JSONResponse:
        """List example design configs from the examples/ directory."""
        examples: list[dict[str, Any]] = []
        search_dir = examples_dir or Path("examples")
        if not search_dir.exists():
            return JSONResponse(content={"examples": examples})
        for design_dir in sorted(search_dir.iterdir()):
            if not design_dir.is_dir():
                continue
            configs = sorted(design_dir.glob("agentic_config*.yaml"))
            for cfg in configs:
                examples.append({
                    "design": design_dir.name,
                    "config_file": cfg.name,
                    "config_path": str(cfg),
                })
        return JSONResponse(content={"examples": examples})

    @router.get("/config/stages")
    async def api_get_stage_info() -> JSONResponse:
        """Return stage order and descriptions for the UI."""
        stage_descriptions = {
            "SYNTH": "Converts Verilog HDL into a gate-level netlist using logic cells from the PDK library.",
            "FLOORPLAN": "Defines the chip's physical boundaries, I/O pin placement, and macro positions.",
            "PDN": "Creates the power delivery network (VDD/VSS) with metal straps and rings.",
            "PLACE_GLOBAL": "Roughly positions all standard cells to minimize wirelength.",
            "PLACE_DETAILED": "Refines cell positions to fix overlaps and optimize local routing.",
            "CTS": "Builds a clock tree to distribute the clock signal with minimal skew.",
            "ROUTE_GLOBAL": "Plans approximate routing paths for all signal nets.",
            "ROUTE_DETAILED": "Assigns exact metal tracks and vias for every net connection.",
            "FINISH": "Adds filler cells, generates final DEF, and prepares for signoff.",
            "SIGNOFF": "Runs DRC, LVS, antenna checks, and generates the final GDSII layout.",
        }
        return JSONResponse(content={
            "stages": STAGE_ORDER,
            "descriptions": stage_descriptions,
        })

    # ============================================================== #
    # Run management endpoints
    # ============================================================== #

    @router.post("/runs/start")
    async def api_start_run(config: dict[str, Any]) -> JSONResponse:
        """Start a new agenticlane run."""
        if run_manager is None:
            raise HTTPException(
                status_code=501,
                detail="Run manager not available",
            )
        try:
            result = await run_manager.start_run(config, runs_dir)
            return JSONResponse(content=result)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=500, detail=str(exc)
            ) from exc

    @router.post("/runs/{run_id}/stop")
    async def api_stop_run(run_id: str) -> JSONResponse:
        """Stop an active run."""
        if run_manager is None:
            raise HTTPException(
                status_code=501,
                detail="Run manager not available",
            )
        stopped = await run_manager.stop_run(run_id)
        if not stopped:
            raise HTTPException(
                status_code=404, detail="Run not found or not active"
            )
        return JSONResponse(content={"status": "stopped", "run_id": run_id})

    @router.get("/runs/active")
    async def api_get_active_runs() -> JSONResponse:
        """List currently running flows."""
        if run_manager is None:
            return JSONResponse(content={"active": []})
        active = run_manager.get_active()
        return JSONResponse(content={"active": active})

    return router
