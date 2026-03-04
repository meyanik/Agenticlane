"""Tests for manifest and reproducibility (P5.8)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from agenticlane.orchestration.manifest import (
    ManifestBuilder,
    RunManifest,
    StageDecision,
)


class TestRunManifest:
    def test_manifest_has_tool_versions(self) -> None:
        manifest = RunManifest(run_id="run_001")
        assert manifest.python_version == sys.version
        assert manifest.platform_info  # non-empty
        assert manifest.agenticlane_version == "0.1.0"

    def test_manifest_has_config(self) -> None:
        manifest = RunManifest(
            run_id="run_001",
            resolved_config={"FP_CORE_UTIL": 50, "parallel_jobs": 3},
        )
        assert manifest.resolved_config["FP_CORE_UTIL"] == 50

    def test_manifest_has_seed(self) -> None:
        manifest = RunManifest(run_id="run_001", random_seed=42)
        assert manifest.random_seed == 42

    def test_manifest_has_timing(self) -> None:
        manifest = RunManifest(
            run_id="run_001",
            start_time="2026-02-26T10:00:00+00:00",
            end_time="2026-02-26T10:05:00+00:00",
            duration_seconds=300.0,
        )
        assert manifest.duration_seconds == 300.0
        assert manifest.start_time
        assert manifest.end_time


class TestManifestBuilder:
    def test_record_decisions(self) -> None:
        builder = ManifestBuilder(run_id="run_001")
        builder.record_decision(StageDecision(
            stage="FLOORPLAN", branch_id="B0", attempt=1,
            action="accept", composite_score=0.8,
        ))
        builder.record_decision(StageDecision(
            stage="FLOORPLAN", branch_id="B1", attempt=1,
            action="reject", reason="low score",
        ))
        manifest = builder.finalize()
        assert len(manifest.decisions) == 2
        assert manifest.total_attempts == 2

    def test_manifest_has_all_decisions(self) -> None:
        builder = ManifestBuilder(run_id="run_001")
        for i in range(5):
            builder.record_decision(StageDecision(
                stage=f"STAGE_{i}", branch_id="B0", attempt=i,
                action="accept",
            ))
        manifest = builder.finalize()
        assert len(manifest.decisions) == 5

    def test_manifest_has_best_branch(self) -> None:
        builder = ManifestBuilder(run_id="run_001")
        builder.set_winner("B2", 0.95)
        manifest = builder.finalize()
        assert manifest.best_branch_id == "B2"
        assert manifest.best_composite_score == 0.95

    def test_record_branches(self) -> None:
        builder = ManifestBuilder(run_id="run_001")
        builder.record_branch("B0", "completed", best_score=0.8, stages_completed=10)
        builder.record_branch("B1", "pruned", best_score=0.3, stages_completed=5)
        manifest = builder.finalize()
        assert manifest.branches["B0"]["status"] == "completed"
        assert manifest.branches["B1"]["status"] == "pruned"

    def test_finalize_sets_timing(self) -> None:
        builder = ManifestBuilder(run_id="run_001")
        manifest = builder.finalize()
        assert manifest.start_time
        assert manifest.end_time
        assert manifest.duration_seconds is not None
        assert manifest.duration_seconds >= 0

    def test_set_stages(self) -> None:
        builder = ManifestBuilder(run_id="run_001")
        builder.set_stages(10)
        manifest = builder.finalize()
        assert manifest.total_stages == 10

    def test_set_resumed(self) -> None:
        builder = ManifestBuilder(run_id="run_001")
        builder.set_resumed("/path/to/checkpoint.json")
        manifest = builder.finalize()
        assert manifest.resumed is True
        assert manifest.resume_from == "/path/to/checkpoint.json"

    def test_config_and_seed_passed(self) -> None:
        builder = ManifestBuilder(
            run_id="run_001",
            config={"FP_CORE_UTIL": 50},
            seed=42,
        )
        manifest = builder.finalize()
        assert manifest.resolved_config["FP_CORE_UTIL"] == 50
        assert manifest.random_seed == 42


class TestManifestPersistence:
    def test_write_and_load_roundtrip(self, tmp_path: Path) -> None:
        builder = ManifestBuilder(run_id="run_001", config={"key": "value"}, seed=42)
        builder.record_decision(StageDecision(
            stage="FLOORPLAN", branch_id="B0", attempt=1,
            action="accept", composite_score=0.85,
        ))
        builder.record_branch("B0", "completed", best_score=0.85)
        builder.set_winner("B0", 0.85)
        builder.set_stages(10)
        manifest = builder.finalize()

        path = ManifestBuilder.write_manifest(manifest, tmp_path)
        assert path.exists()
        assert path.name == "manifest.json"

        loaded = ManifestBuilder.load_manifest(path)
        assert loaded.run_id == "run_001"
        assert loaded.random_seed == 42
        assert loaded.best_branch_id == "B0"
        assert len(loaded.decisions) == 1
        assert loaded.branches["B0"]["status"] == "completed"

    def test_manifest_json_valid(self, tmp_path: Path) -> None:
        manifest = RunManifest(run_id="run_001")
        path = ManifestBuilder.write_manifest(manifest, tmp_path)
        data = json.loads(path.read_text())
        assert data["run_id"] == "run_001"
        assert "python_version" in data
