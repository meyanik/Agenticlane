"""Tests for report generation (P5.9)."""
from __future__ import annotations

import json

from agenticlane.reporting.report import (
    ReportGenerator,
)


def _make_manifest_data() -> dict:
    return {
        "run_id": "run_001",
        "best_branch_id": "B0",
        "best_composite_score": 0.85,
        "total_stages": 10,
        "total_attempts": 15,
        "duration_seconds": 120.5,
        "branches": {
            "B0": {"status": "completed", "best_score": 0.85, "stages_completed": 10},
            "B1": {"status": "pruned", "best_score": 0.3, "stages_completed": 5},
            "B2": {"status": "completed", "best_score": 0.7, "stages_completed": 10},
        },
        "decisions": [
            {
                "stage": "FLOORPLAN",
                "branch_id": "B0",
                "attempt": 1,
                "action": "accept",
                "composite_score": 0.85,
            },
            {
                "stage": "FLOORPLAN",
                "branch_id": "B1",
                "attempt": 1,
                "action": "reject",
                "composite_score": 0.3,
            },
            {
                "stage": "FLOORPLAN",
                "branch_id": "B2",
                "attempt": 1,
                "action": "accept",
                "composite_score": 0.7,
            },
            {
                "stage": "PLACE_GLOBAL",
                "branch_id": "B0",
                "attempt": 2,
                "action": "accept",
                "composite_score": 0.82,
            },
        ],
    }


class TestReportGenerator:
    def test_report_from_manifest(self) -> None:
        data = _make_manifest_data()
        report = ReportGenerator.from_manifest(data)
        assert report.run_id == "run_001"
        assert report.best_branch_id == "B0"
        assert report.best_score == 0.85

    def test_report_branch_comparison(self) -> None:
        data = _make_manifest_data()
        report = ReportGenerator.from_manifest(data)
        assert len(report.branch_reports) == 3
        assert report.completed_branches == 2
        assert report.pruned_branches == 1

    def test_report_best_metrics(self) -> None:
        data = _make_manifest_data()
        report = ReportGenerator.from_manifest(data)
        b0 = next(br for br in report.branch_reports if br.branch_id == "B0")
        assert b0.best_score == 0.85
        assert b0.stages_completed == 10

    def test_report_per_stage_analysis(self) -> None:
        data = _make_manifest_data()
        report = ReportGenerator.from_manifest(data)
        assert len(report.stage_reports) >= 1
        fp_stage = next(sr for sr in report.stage_reports if sr.stage_name == "FLOORPLAN")
        assert len(fp_stage.branches) == 3

    def test_report_json_output(self) -> None:
        data = _make_manifest_data()
        report = ReportGenerator.from_manifest(data)
        json_str = ReportGenerator.to_json(report)
        parsed = json.loads(json_str)
        assert parsed["run_id"] == "run_001"

    def test_report_terminal_output(self) -> None:
        data = _make_manifest_data()
        report = ReportGenerator.from_manifest(data)
        output = ReportGenerator.render_terminal(report)
        assert "run_001" in output
        assert "B0" in output
        assert "completed" in output

    def test_golden_report(self) -> None:
        data = _make_manifest_data()
        report = ReportGenerator.from_manifest(data)
        output = ReportGenerator.render_terminal(report)
        assert "Best Branch: B0" in output
        assert "0.8500" in output

    def test_empty_manifest(self) -> None:
        report = ReportGenerator.from_manifest({"run_id": "empty"})
        assert report.total_branches == 0
        assert report.branch_reports == []
