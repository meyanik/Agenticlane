"""Tests for the local dashboard HTML rendering and helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agenticlane.reporting.dashboard import (
    _collect_evidence,
    _collect_rejections,
    _extract_hotspots,
    _list_runs,
    _load_manifest,
    _render_index,
    _render_run,
)


@pytest.fixture()
def runs_dir(tmp_path: Path) -> Path:
    """Create a temporary runs directory with sample run data."""
    run_dir = tmp_path / "run_test_001"
    run_dir.mkdir()

    manifest = {
        "run_id": "run_test_001",
        "flow_mode": "flat",
        "best_composite_score": 0.85,
        "best_branch_id": "B0",
        "total_stages": 10,
        "total_attempts": 15,
        "duration_seconds": 120.5,
        "start_time": "2026-03-01T12:00:00Z",
        "end_time": "2026-03-01T12:02:00Z",
        "random_seed": 42,
        "branches": {
            "B0": {
                "status": "completed",
                "best_score": 0.85,
                "stages_completed": 10,
            }
        },
        "decisions": [
            {
                "stage": "SYNTH",
                "branch_id": "B0",
                "attempt": 1,
                "action": "accept",
                "composite_score": 0.7,
                "reason": "Timing met",
            },
            {
                "stage": "FLOORPLAN",
                "branch_id": "B0",
                "attempt": 1,
                "action": "reject",
                "composite_score": 0.3,
                "reason": "High congestion",
            },
            {
                "stage": "FLOORPLAN",
                "branch_id": "B0",
                "attempt": 2,
                "action": "accept",
                "composite_score": 0.85,
                "reason": "Improved",
            },
        ],
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest))

    # Evidence pack
    evidence_dir = run_dir / "B0" / "SYNTH" / "attempt_001"
    evidence_dir.mkdir(parents=True)
    evidence_pack = {
        "schema_version": 1,
        "stage": "SYNTH",
        "attempt": 1,
        "execution_status": "success",
        "errors": [],
        "warnings": [{"source": "log", "severity": "warning", "message": "test", "count": 1}],
        "spatial_hotspots": [
            {
                "type": "congestion",
                "grid_bin": {"x": 1, "y": 2},
                "region_label": "NE corner",
                "severity": 0.65,
                "nearby_macros": ["U_RAM_0"],
            }
        ],
        "missing_reports": [],
        "bounded_snippets": [],
    }
    (evidence_dir / "evidence_pack.json").write_text(json.dumps(evidence_pack))

    # PatchRejected
    (evidence_dir / "patch_rejected_001.json").write_text(json.dumps({
        "schema_version": 1,
        "reason_code": "locked_constraint",
        "offending_channel": "config_vars",
        "offending_commands": ["set_clock_uncertainty"],
        "remediation_hint": "Remove clock uncertainty override",
    }))

    return tmp_path


class TestListRuns:
    def test_lists_runs_with_manifest(self, runs_dir: Path) -> None:
        runs = _list_runs(runs_dir)
        assert runs == ["run_test_001"]

    def test_empty_dir(self, tmp_path: Path) -> None:
        runs = _list_runs(tmp_path)
        assert runs == []

    def test_nonexistent_dir(self, tmp_path: Path) -> None:
        runs = _list_runs(tmp_path / "nonexistent")
        assert runs == []

    def test_ignores_dirs_without_manifest(self, tmp_path: Path) -> None:
        (tmp_path / "no_manifest").mkdir()
        runs = _list_runs(tmp_path)
        assert runs == []


class TestLoadManifest:
    def test_loads_manifest(self, runs_dir: Path) -> None:
        m = _load_manifest(runs_dir, "run_test_001")
        assert m is not None
        assert m["run_id"] == "run_test_001"
        assert m["best_composite_score"] == 0.85

    def test_returns_none_for_missing(self, runs_dir: Path) -> None:
        m = _load_manifest(runs_dir, "nonexistent")
        assert m is None


class TestCollectEvidence:
    def test_collects_evidence_packs(self, runs_dir: Path) -> None:
        packs = _collect_evidence(runs_dir, "run_test_001")
        assert len(packs) == 1
        assert packs[0]["stage"] == "SYNTH"

    def test_empty_for_missing_run(self, runs_dir: Path) -> None:
        packs = _collect_evidence(runs_dir, "nonexistent")
        assert packs == []


class TestCollectRejections:
    def test_collects_rejections(self, runs_dir: Path) -> None:
        rejections = _collect_rejections(runs_dir, "run_test_001")
        assert len(rejections) == 1
        assert rejections[0]["reason_code"] == "locked_constraint"

    def test_empty_for_missing_run(self, runs_dir: Path) -> None:
        rejections = _collect_rejections(runs_dir, "nonexistent")
        assert rejections == []


class TestExtractHotspots:
    def test_extracts_hotspots(self, runs_dir: Path) -> None:
        packs = _collect_evidence(runs_dir, "run_test_001")
        hotspots = _extract_hotspots(packs)
        assert len(hotspots) == 1
        assert hotspots[0]["type"] == "congestion"
        assert hotspots[0]["severity"] == 0.65
        assert hotspots[0]["_stage"] == "SYNTH"

    def test_empty_evidence(self) -> None:
        assert _extract_hotspots([]) == []


class TestRenderIndex:
    def test_renders_run_list(self, runs_dir: Path) -> None:
        runs = _list_runs(runs_dir)
        html = _render_index(runs, runs_dir)
        assert "run_test_001" in html
        assert "AgenticLane Dashboard" in html
        assert "0.850" in html
        assert "flat" in html

    def test_empty_runs(self, tmp_path: Path) -> None:
        html = _render_index([], tmp_path)
        assert "AgenticLane Dashboard" in html


class TestRenderRun:
    def test_renders_overview(self, runs_dir: Path) -> None:
        manifest = _load_manifest(runs_dir, "run_test_001")
        assert manifest is not None
        evidence = _collect_evidence(runs_dir, "run_test_001")
        rejections = _collect_rejections(runs_dir, "run_test_001")
        html = _render_run("run_test_001", manifest, evidence, rejections)

        # Overview stats
        assert "0.850" in html
        assert "B0" in html
        assert "120s" in html

        # Branches
        assert "completed" in html

        # Score progression
        assert "SYNTH" in html
        assert "FLOORPLAN" in html

        # Judge votes
        assert "accept" in html
        assert "reject" in html

        # Rejections
        assert "locked_constraint" in html

        # Hotspots
        assert "congestion" in html
        assert "NE corner" in html

        # Evidence
        assert "success" in html

    def test_renders_with_empty_data(self) -> None:
        manifest = {
            "flow_mode": "flat",
            "branches": {},
            "decisions": [],
        }
        html = _render_run("empty", manifest, [], [])
        assert "empty" in html
        assert "No decisions recorded" in html

    def test_renders_hierarchical_modules(self) -> None:
        manifest = {
            "flow_mode": "hierarchical",
            "branches": {},
            "decisions": [],
            "module_results": {
                "picorv32": {
                    "completed": True,
                    "stages_completed": 10,
                    "stages_failed": [],
                },
                "spimemio": {
                    "completed": False,
                    "stages_completed": 6,
                    "stages_failed": ["SIGNOFF"],
                },
            },
        }
        html = _render_run("hier", manifest, [], [])
        assert "picorv32" in html
        assert "spimemio" in html
        assert "SIGNOFF" in html
