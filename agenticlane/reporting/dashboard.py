"""AgenticLane local dashboard.

Self-contained FastAPI dashboard that reads run folder JSON files.
All CSS/JS is embedded for offline operation.

Displays:
- branches and attempt timelines
- metrics score progression
- judge votes
- constraint digest summaries
- PatchRejected events
- spatial hotspots grid
"""

from __future__ import annotations

import json
import logging
from html import escape
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Check if FastAPI is available (optional dependency)
_HAS_FASTAPI = False
try:
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse

    _HAS_FASTAPI = True
except ImportError:
    pass


# ------------------------------------------------------------------ #
# CSS (embedded for offline use)
# ------------------------------------------------------------------ #

_CSS = """\
:root {
  --bg: #0d1117; --surface: #161b22; --border: #30363d;
  --text: #e6edf3; --text-dim: #8b949e; --accent: #58a6ff;
  --green: #3fb950; --red: #f85149; --yellow: #d29922; --purple: #bc8cff;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, system-ui, sans-serif; background: var(--bg);
       color: var(--text); line-height: 1.6; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
.container { max-width: 1200px; margin: 0 auto; padding: 24px; }
h1 { font-size: 1.8rem; margin-bottom: 8px; }
h2 { font-size: 1.3rem; margin: 24px 0 12px; color: var(--accent); }
h3 { font-size: 1.1rem; margin: 16px 0 8px; }
.subtitle { color: var(--text-dim); margin-bottom: 24px; }
.badge { display: inline-block; padding: 2px 10px; border-radius: 12px;
         font-size: 0.8rem; font-weight: 600; }
.badge-success { background: #238636; color: #fff; }
.badge-fail { background: #da3633; color: #fff; }
.badge-active { background: #1f6feb; color: #fff; }
.badge-pruned { background: #6e7681; color: #fff; }
.card { background: var(--surface); border: 1px solid var(--border);
        border-radius: 8px; padding: 16px; margin-bottom: 16px; }
.grid { display: grid; gap: 16px; }
.grid-2 { grid-template-columns: 1fr 1fr; }
.grid-3 { grid-template-columns: 1fr 1fr 1fr; }
.grid-4 { grid-template-columns: 1fr 1fr 1fr 1fr; }
.stat-label { font-size: 0.8rem; color: var(--text-dim); text-transform: uppercase; }
.stat-value { font-size: 1.4rem; font-weight: 700; }
table { width: 100%; border-collapse: collapse; margin: 8px 0; }
th, td { padding: 8px 12px; text-align: left; border-bottom: 1px solid var(--border); }
th { color: var(--text-dim); font-size: 0.8rem; text-transform: uppercase;
     font-weight: 600; }
tr:hover { background: rgba(88,166,255,0.05); }
.bar-container { background: var(--border); border-radius: 4px; height: 20px;
                 position: relative; overflow: hidden; }
.bar-fill { height: 100%; border-radius: 4px; transition: width 0.3s; }
.bar-label { position: absolute; right: 6px; top: 1px; font-size: 0.75rem;
             color: var(--text); }
.timeline { display: flex; gap: 4px; align-items: end; height: 60px; }
.timeline-bar { flex: 1; min-width: 8px; border-radius: 2px 2px 0 0;
                position: relative; cursor: pointer; }
.timeline-bar:hover::after {
  content: attr(data-tooltip); position: absolute; bottom: 105%;
  left: 50%; transform: translateX(-50%); background: var(--surface);
  border: 1px solid var(--border); padding: 4px 8px; border-radius: 4px;
  font-size: 0.75rem; white-space: nowrap; z-index: 10; }
.accept { background: var(--green); }
.reject { background: var(--red); }
.retry { background: var(--yellow); }
.rollback { background: var(--purple); }
.prune { background: var(--text-dim); }
.hotspot-grid { display: grid; gap: 2px; }
.hotspot-cell { aspect-ratio: 1; border-radius: 2px; position: relative;
                cursor: pointer; min-width: 20px; }
.hotspot-cell:hover::after {
  content: attr(data-tooltip); position: absolute; bottom: 105%;
  left: 50%; transform: translateX(-50%); background: var(--surface);
  border: 1px solid var(--border); padding: 4px 8px; border-radius: 4px;
  font-size: 0.75rem; white-space: nowrap; z-index: 10; }
nav { background: var(--surface); border-bottom: 1px solid var(--border);
      padding: 12px 24px; }
nav a { margin-right: 16px; }
.tag { font-size: 0.75rem; padding: 1px 6px; border-radius: 4px;
       background: var(--border); color: var(--text-dim); }
@media (max-width: 768px) {
  .grid-2, .grid-3, .grid-4 { grid-template-columns: 1fr; }
}
"""


# ------------------------------------------------------------------ #
# Helper: load run data
# ------------------------------------------------------------------ #

def _list_runs(runs_dir: Path) -> list[str]:
    """List available run IDs."""
    if not runs_dir.exists():
        return []
    return sorted(
        d.name
        for d in runs_dir.iterdir()
        if d.is_dir() and (d / "manifest.json").exists()
    )


def _load_manifest(runs_dir: Path, run_id: str) -> dict[str, Any] | None:
    """Load manifest.json for a run."""
    path = runs_dir / run_id / "manifest.json"
    if not path.exists():
        return None
    result: dict[str, Any] = json.loads(path.read_text())
    return result


def _collect_evidence(runs_dir: Path, run_id: str) -> list[dict[str, Any]]:
    """Collect all evidence_pack.json files from a run."""
    run_dir = runs_dir / run_id
    packs = []
    for ep in sorted(run_dir.rglob("evidence_pack.json")):
        try:
            packs.append(json.loads(ep.read_text()))
        except (json.JSONDecodeError, OSError):
            continue
    return packs


def _collect_rejections(runs_dir: Path, run_id: str) -> list[dict[str, Any]]:
    """Collect PatchRejected events from evidence packs and constraint logs."""
    run_dir = runs_dir / run_id
    rejections: list[dict[str, Any]] = []
    for f in sorted(run_dir.rglob("patch_rejected*.json")):
        try:
            rejections.append(json.loads(f.read_text()))
        except (json.JSONDecodeError, OSError):
            continue
    return rejections


# ------------------------------------------------------------------ #
# HTML renderers
# ------------------------------------------------------------------ #

def _render_index(runs: list[str], runs_dir: Path) -> str:
    """Render the index page listing all runs."""
    rows = []
    for run_id in runs:
        m = _load_manifest(runs_dir, run_id)
        if not m:
            continue
        mode = m.get("flow_mode", "flat")
        score = m.get("best_composite_score")
        score_str = f"{score:.3f}" if score is not None else "-"
        stages = m.get("total_stages", 0)
        attempts = m.get("total_attempts", 0)
        duration = m.get("duration_seconds")
        dur_str = f"{duration:.0f}s" if duration else "-"
        rows.append(
            f'<tr><td><a href="/runs/{escape(run_id)}">{escape(run_id)}</a></td>'
            f'<td><span class="tag">{escape(mode)}</span></td>'
            f"<td>{score_str}</td><td>{stages}</td><td>{attempts}</td>"
            f"<td>{dur_str}</td></tr>"
        )
    table = (
        "<table><thead><tr><th>Run ID</th><th>Mode</th><th>Best Score</th>"
        "<th>Stages</th><th>Attempts</th><th>Duration</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )
    return _page("AgenticLane Dashboard", f"<h1>AgenticLane Dashboard</h1>"
                  f'<p class="subtitle">Local run viewer</p>{table}')


def _render_run(run_id: str, manifest: dict[str, Any],
                evidence: list[dict[str, Any]],
                rejections: list[dict[str, Any]]) -> str:
    """Render the run detail page."""
    parts: list[str] = []

    # --- Overview ---
    parts.append(f'<h1>Run: {escape(run_id)}</h1>')
    parts.append('<div class="grid grid-4">')
    _add_stat(parts, "Flow Mode", manifest.get("flow_mode", "flat"))
    score = manifest.get("best_composite_score")
    _add_stat(parts, "Best Score", f"{score:.3f}" if score is not None else "-")
    _add_stat(parts, "Best Branch", manifest.get("best_branch_id", "-"))
    dur = manifest.get("duration_seconds")
    _add_stat(parts, "Duration", f"{dur:.0f}s" if dur else "-")
    parts.append("</div>")
    parts.append('<div class="grid grid-4">')
    _add_stat(parts, "Stages", str(manifest.get("total_stages", 0)))
    _add_stat(parts, "Attempts", str(manifest.get("total_attempts", 0)))
    _add_stat(parts, "Seed", str(manifest.get("random_seed", "-")))
    start = manifest.get("start_time", "")
    _add_stat(parts, "Started", start[:19] if start else "-")
    parts.append("</div>")

    # --- Branch Timeline ---
    parts.append("<h2>Branches</h2>")
    branches = manifest.get("branches", {})
    decisions = manifest.get("decisions", [])
    if branches:
        parts.append('<div class="grid grid-2">')
        for bid, binfo in branches.items():
            status = binfo.get("status", "unknown")
            badge_cls = {
                "completed": "badge-success", "failed": "badge-fail",
                "active": "badge-active", "pruned": "badge-pruned",
            }.get(status, "badge-active")
            bscore = binfo.get("best_score")
            bscore_str = f"{bscore:.3f}" if bscore is not None else "-"
            # Build timeline bars for this branch
            branch_decisions = [d for d in decisions if d.get("branch_id") == bid]
            timeline = _render_timeline(branch_decisions)
            parts.append(
                f'<div class="card"><h3>{escape(bid)} '
                f'<span class="badge {badge_cls}">{escape(status)}</span></h3>'
                f'<p>Score: {bscore_str} | '
                f'Stages: {binfo.get("stages_completed", 0)}</p>'
                f'{timeline}</div>'
            )
        parts.append("</div>")

    # --- Metrics Score Progression ---
    parts.append("<h2>Metrics Score Progression</h2>")
    if decisions:
        parts.append(_render_score_table(decisions))
    else:
        parts.append('<p class="text-dim">No decisions recorded.</p>')

    # --- Judge Votes ---
    parts.append("<h2>Judge Votes</h2>")
    judge_decisions = [d for d in decisions if d.get("action") in ("accept", "reject")]
    if judge_decisions:
        parts.append(_render_judge_table(judge_decisions))
    else:
        parts.append('<p class="text-dim">No judge votes recorded.</p>')

    # --- PatchRejected Events ---
    parts.append("<h2>PatchRejected Events</h2>")
    if rejections:
        parts.append(_render_rejections_table(rejections))
    else:
        parts.append('<p class="text-dim">No constraint rejections recorded.</p>')

    # --- Spatial Hotspots ---
    parts.append("<h2>Spatial Hotspots</h2>")
    hotspots = _extract_hotspots(evidence)
    if hotspots:
        parts.append(_render_hotspots(hotspots))
    else:
        parts.append('<p class="text-dim">No spatial hotspots recorded.</p>')

    # --- Evidence Summary ---
    parts.append("<h2>Evidence Summary</h2>")
    if evidence:
        parts.append(_render_evidence_summary(evidence))
    else:
        parts.append('<p class="text-dim">No evidence packs found.</p>')

    # --- Hierarchical Modules ---
    modules = manifest.get("module_results", {})
    if modules:
        parts.append("<h2>Hierarchical Modules</h2>")
        parts.append(_render_modules(modules))

    nav = '<a href="/">&larr; All Runs</a>'
    return _page(f"Run {run_id}", "".join(parts), nav=nav)


def _add_stat(parts: list[str], label: str, value: str) -> None:
    parts.append(
        f'<div class="card"><div class="stat-label">{escape(label)}</div>'
        f'<div class="stat-value">{escape(value)}</div></div>'
    )


def _render_timeline(decisions: list[dict[str, Any]]) -> str:
    """Render a timeline bar chart for decisions."""
    if not decisions:
        return '<p class="text-dim">No attempts</p>'
    max_score = max(
        (abs(d.get("composite_score") or 0) for d in decisions),
        default=1.0,
    ) or 1.0
    bars = []
    for d in decisions:
        action = d.get("action", "retry")
        score = d.get("composite_score")
        height_pct = (abs(score) / max_score * 100) if score is not None else 10
        height_pct = max(height_pct, 5)
        tooltip = f'{d.get("stage", "?")} A{d.get("attempt", "?")} = {score}'
        bars.append(
            f'<div class="timeline-bar {escape(action)}" '
            f'style="height:{height_pct:.0f}%" '
            f'data-tooltip="{escape(str(tooltip))}"></div>'
        )
    return f'<div class="timeline">{"".join(bars)}</div>'


def _render_score_table(decisions: list[dict[str, Any]]) -> str:
    """Render a table of score progression."""
    rows = []
    for d in decisions:
        score = d.get("composite_score")
        score_str = f"{score:.4f}" if score is not None else "-"
        action = d.get("action", "?")
        action_cls = {
            "accept": "badge-success", "reject": "badge-fail",
            "retry": "badge-active", "rollback": "badge-pruned",
        }.get(action, "")
        rows.append(
            f'<tr><td>{escape(d.get("branch_id", ""))}</td>'
            f'<td>{escape(d.get("stage", ""))}</td>'
            f'<td>{d.get("attempt", "")}</td>'
            f'<td>{score_str}</td>'
            f'<td><span class="badge {action_cls}">{escape(action)}</span></td>'
            f'<td>{escape(d.get("reason", ""))}</td></tr>'
        )
    return (
        "<table><thead><tr><th>Branch</th><th>Stage</th><th>Attempt</th>"
        "<th>Score</th><th>Action</th><th>Reason</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _render_judge_table(decisions: list[dict[str, Any]]) -> str:
    """Render judge vote details."""
    rows = []
    for d in decisions:
        action = d.get("action", "?")
        cls = "badge-success" if action == "accept" else "badge-fail"
        score = d.get("composite_score")
        score_str = f"{score:.4f}" if score is not None else "-"
        rows.append(
            f'<tr><td>{escape(d.get("stage", ""))}</td>'
            f'<td>{d.get("attempt", "")}</td>'
            f'<td><span class="badge {cls}">{escape(action)}</span></td>'
            f'<td>{score_str}</td>'
            f'<td>{escape(d.get("reason", ""))}</td></tr>'
        )
    return (
        "<table><thead><tr><th>Stage</th><th>Attempt</th>"
        "<th>Vote</th><th>Score</th><th>Reason</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _render_rejections_table(rejections: list[dict[str, Any]]) -> str:
    """Render PatchRejected events."""
    rows = []
    for r in rejections:
        rows.append(
            f'<tr><td>{escape(str(r.get("reason_code", "")))}</td>'
            f'<td>{escape(str(r.get("offending_channel", "")))}</td>'
            f'<td>{escape(str(r.get("remediation_hint", "")))}</td>'
            f'<td>{escape(str(r.get("offending_commands", [])))}</td></tr>'
        )
    return (
        "<table><thead><tr><th>Reason</th><th>Channel</th>"
        "<th>Remediation</th><th>Commands</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _extract_hotspots(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract all spatial hotspots from evidence packs."""
    hotspots = []
    for ep in evidence:
        stage = ep.get("stage", "?")
        for hs in ep.get("spatial_hotspots", []):
            hs["_stage"] = stage
            hotspots.append(hs)
    return hotspots


def _render_hotspots(hotspots: list[dict[str, Any]]) -> str:
    """Render spatial hotspots as a table with severity bars."""
    rows = []
    for hs in hotspots:
        severity = hs.get("severity", 0)
        sev_pct = min(severity * 100, 100)
        color = (
            "var(--green)" if sev_pct < 40
            else "var(--yellow)" if sev_pct < 70
            else "var(--red)"
        )
        bar = (
            f'<div class="bar-container">'
            f'<div class="bar-fill" style="width:{sev_pct:.0f}%;background:{color}"></div>'
            f'<div class="bar-label">{severity:.2f}</div></div>'
        )
        rows.append(
            f'<tr><td>{escape(hs.get("_stage", ""))}</td>'
            f'<td>{escape(hs.get("type", ""))}</td>'
            f'<td>{escape(hs.get("region_label", ""))}</td>'
            f"<td>{bar}</td>"
            f'<td>{escape(str(hs.get("nearby_macros", [])))}</td></tr>'
        )
    return (
        "<table><thead><tr><th>Stage</th><th>Type</th><th>Region</th>"
        "<th>Severity</th><th>Nearby Macros</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _render_evidence_summary(evidence: list[dict[str, Any]]) -> str:
    """Render a summary table of evidence packs."""
    rows = []
    for ep in evidence:
        status = ep.get("execution_status", "?")
        cls = "badge-success" if status == "success" else "badge-fail"
        n_errors = len(ep.get("errors", []))
        n_warnings = len(ep.get("warnings", []))
        n_hotspots = len(ep.get("spatial_hotspots", []))
        rows.append(
            f'<tr><td>{escape(ep.get("stage", ""))}</td>'
            f'<td>{ep.get("attempt", "")}</td>'
            f'<td><span class="badge {cls}">{escape(status)}</span></td>'
            f"<td>{n_errors}</td><td>{n_warnings}</td><td>{n_hotspots}</td></tr>"
        )
    return (
        "<table><thead><tr><th>Stage</th><th>Attempt</th><th>Status</th>"
        "<th>Errors</th><th>Warnings</th><th>Hotspots</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _render_modules(modules: dict[str, dict[str, Any]]) -> str:
    """Render hierarchical module results."""
    rows = []
    for name, info in modules.items():
        completed = info.get("completed", False)
        cls = "badge-success" if completed else "badge-fail"
        status_text = "completed" if completed else "incomplete"
        n_stages = info.get("stages_completed", 0)
        failed = info.get("stages_failed", [])
        failed_str = ", ".join(failed) if failed else "-"
        rows.append(
            f'<tr><td>{escape(name)}</td>'
            f'<td><span class="badge {cls}">{escape(status_text)}</span></td>'
            f"<td>{n_stages}</td>"
            f'<td>{escape(failed_str)}</td></tr>'
        )
    return (
        "<table><thead><tr><th>Module</th><th>Status</th>"
        "<th>Stages Done</th><th>Failed Stages</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _page(title: str, body: str, nav: str = "") -> str:
    """Wrap content in the full HTML page."""
    nav_html = f'<nav>{nav}</nav>' if nav else '<nav><strong>AgenticLane</strong></nav>'
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<style>{_CSS}</style>
</head>
<body>
{nav_html}
<div class="container">
{body}
</div>
</body>
</html>"""


# ------------------------------------------------------------------ #
# FastAPI app factory
# ------------------------------------------------------------------ #

def create_dashboard_app(
    runs_dir: Path,
    *,
    dev_mode: bool = False,
    examples_dir: Path | None = None,
    static_dir: Path | None = None,
) -> Any:
    """Create a FastAPI dashboard application.

    Args:
        runs_dir: Directory containing run data.
        dev_mode: If True, skip static file serving (Vite dev server proxies).
        examples_dir: Optional path to ``examples/`` for config browsing.
        static_dir: Path to the built React frontend (``dashboard-ui/dist``).

    Returns:
        A FastAPI application instance.

    Raises:
        ImportError: If FastAPI is not installed.
    """
    if not _HAS_FASTAPI:
        raise ImportError(
            "FastAPI is required for the dashboard. "
            "Install with: pip install fastapi uvicorn"
        )

    from contextlib import asynccontextmanager

    from starlette.responses import StreamingResponse

    from agenticlane.reporting.dashboard_api import create_api_router
    from agenticlane.reporting.dashboard_events import (
        DashboardEventBus,
        RunFileWatcher,
    )
    from agenticlane.reporting.dashboard_runner import DashboardRunManager

    # Shared instances
    event_bus = DashboardEventBus()
    file_watcher = RunFileWatcher(event_bus)
    run_manager = DashboardRunManager()

    @asynccontextmanager
    async def _lifespan(app: Any) -> Any:
        # Startup: begin watching existing runs
        for run_id in _list_runs(runs_dir):
            await file_watcher.watch_run(run_id, runs_dir)
        yield
        # Shutdown: stop all watchers
        file_watcher.stop_all()

    app = FastAPI(title="AgenticLane Dashboard", version="2.0.0", lifespan=_lifespan)

    # Mount API router (all /api/* endpoints)
    api_router = create_api_router(
        runs_dir=runs_dir,
        run_manager=run_manager,
        event_bus=event_bus,
        examples_dir=examples_dir,
    )
    app.include_router(api_router)

    # SSE endpoint for live updates
    @app.get("/api/runs/{run_id}/events")
    async def sse_run_events(run_id: str) -> StreamingResponse:
        """Server-Sent Events stream for a specific run."""
        import json as _json

        async def event_stream() -> Any:
            async for event in event_bus.subscribe(run_id):
                data = _json.dumps(event)
                yield f"event: {event['type']}\ndata: {data}\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/api/events")
    async def sse_global_events() -> StreamingResponse:
        """Global SSE stream for all run events."""
        import json as _json

        async def event_stream() -> Any:
            async for event in event_bus.subscribe_global():
                data = _json.dumps(event)
                yield f"event: {event['type']}\ndata: {data}\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # Legacy HTML endpoints (fallback when React is not built)
    @app.get("/legacy", response_class=HTMLResponse)
    async def legacy_index() -> str:
        runs = _list_runs(runs_dir)
        return _render_index(runs, runs_dir)

    @app.get("/legacy/runs/{run_id}", response_class=HTMLResponse)
    async def legacy_run_detail(run_id: str) -> HTMLResponse:
        manifest = _load_manifest(runs_dir, run_id)
        if manifest is None:
            return HTMLResponse(
                content=_page("Not Found", "<h1>Run not found</h1>"),
                status_code=404,
            )
        evidence = _collect_evidence(runs_dir, run_id)
        rejections = _collect_rejections(runs_dir, run_id)
        return HTMLResponse(
            content=_render_run(run_id, manifest, evidence, rejections)
        )

    # Serve React static files (production mode)
    if not dev_mode:
        _dist = static_dir or Path(__file__).resolve().parent.parent.parent / "dashboard-ui" / "dist"
        if _dist.exists() and (_dist / "index.html").exists():
            from starlette.staticfiles import StaticFiles

            # Mount /assets for built JS/CSS
            assets_dir = _dist / "assets"
            if assets_dir.exists():
                app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

            # SPA fallback: serve index.html for all non-API routes
            _index_html = (_dist / "index.html").read_text()

            @app.get("/{full_path:path}", response_class=HTMLResponse)
            async def spa_fallback(full_path: str) -> str:
                # Serve static files that exist on disk
                candidate = _dist / full_path
                if candidate.exists() and candidate.is_file():
                    return candidate.read_text()
                return _index_html
        else:
            # No React build available — redirect / to legacy
            @app.get("/")
            async def redirect_to_legacy() -> HTMLResponse:
                runs = _list_runs(runs_dir)
                return HTMLResponse(content=_render_index(runs, runs_dir))

    return app
