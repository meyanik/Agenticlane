"""Tests for agenticlane.orchestration.gc -- Artifact GC (P1.10).

Covers file classification, pruning logic, tip preservation,
disk-limit checking, and dry-run mode.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agenticlane.orchestration.gc import (
    ArtifactGC,
    ArtifactTier,
    GCResult,
    classify_file,
)

# ---------------------------------------------------------------------------
# File classification
# ---------------------------------------------------------------------------


class TestClassifyFile:
    """Test classify_file maps extensions to the correct tier."""

    @pytest.mark.parametrize(
        "filename, expected_tier",
        [
            ("run_log.json", ArtifactTier.LEDGER),
            ("events.jsonl", ArtifactTier.LEDGER),
            ("README.md", ArtifactTier.LEDGER),
            ("config.yaml", ArtifactTier.LEDGER),
            ("config.yml", ArtifactTier.LEDGER),
        ],
    )
    def test_classify_ledger_files(
        self, filename: str, expected_tier: ArtifactTier
    ) -> None:
        """.json, .jsonl, .md, .yaml are LEDGER (never GC'd)."""
        assert classify_file(Path(filename)) == expected_tier

    @pytest.mark.parametrize(
        "filename, expected_tier",
        [
            ("design.odb", ArtifactTier.HEAVY),
            ("floorplan.def", ArtifactTier.HEAVY),
            ("parasitic.spef", ArtifactTier.HEAVY),
            ("layout.gds", ArtifactTier.HEAVY),
            ("netlist.spice", ArtifactTier.HEAVY),
        ],
    )
    def test_classify_heavy_files(
        self, filename: str, expected_tier: ArtifactTier
    ) -> None:
        """.odb, .def, .spef, .gds, .spice are HEAVY (GC candidates)."""
        assert classify_file(Path(filename)) == expected_tier

    @pytest.mark.parametrize(
        "filename, expected_tier",
        [
            ("timing.rpt", ArtifactTier.MEDIUM),
            ("run.log", ArtifactTier.MEDIUM),
            ("notes.txt", ArtifactTier.MEDIUM),
            ("constraints.sdc", ArtifactTier.MEDIUM),
            ("hooks.tcl", ArtifactTier.MEDIUM),
            ("design.v", ArtifactTier.MEDIUM),
        ],
    )
    def test_classify_medium_files(
        self, filename: str, expected_tier: ArtifactTier
    ) -> None:
        """.rpt, .log, .txt, .sdc, .tcl, .v are MEDIUM."""
        assert classify_file(Path(filename)) == expected_tier

    def test_classify_multi_part_extension(self) -> None:
        """.nl.v is recognized as a multi-part extension -> MEDIUM."""
        assert classify_file(Path("design.nl.v")) == ArtifactTier.MEDIUM

    def test_unknown_extension_defaults_to_medium(self) -> None:
        """An unrecognized extension defaults to MEDIUM."""
        assert classify_file(Path("data.xyz_unknown")) == ArtifactTier.MEDIUM


# ---------------------------------------------------------------------------
# Helpers: build a fake run directory
# ---------------------------------------------------------------------------


def _make_attempt(
    run_dir: Path,
    attempt_name: str,
    *,
    heavy_files: list[str] | None = None,
    ledger_files: list[str] | None = None,
    medium_files: list[str] | None = None,
) -> Path:
    """Create a fake attempt directory with dummy files."""
    attempt_dir = run_dir / attempt_name
    attempt_dir.mkdir(parents=True, exist_ok=True)

    for fname in heavy_files or ["design.odb", "floorplan.def"]:
        f = attempt_dir / fname
        f.write_text("heavy data " * 100)  # ~1 KB each

    for fname in ledger_files or ["metrics.json", "patch.json"]:
        f = attempt_dir / fname
        f.write_text('{"key": "value"}')

    for fname in medium_files or ["timing.rpt"]:
        f = attempt_dir / fname
        f.write_text("report content")

    return attempt_dir


# ---------------------------------------------------------------------------
# GC pruning logic
# ---------------------------------------------------------------------------


class TestGCCollect:
    """Test the ArtifactGC.collect method."""

    def test_gc_prunes_heavy_only(self, tmp_path: Path) -> None:
        """After GC, heavy files are gone but ledger and medium remain."""
        run_dir = tmp_path / "run_001"
        _make_attempt(run_dir, "attempt_001")

        gc = ArtifactGC(policy="keep_pass_and_tips")
        result = gc.collect(
            run_dir,
            branch_tips=set(),
            passed_attempts=set(),
        )

        # Heavy files should be deleted
        assert result.files_deleted >= 2  # design.odb + floorplan.def
        assert result.bytes_freed > 0

        # Ledger files MUST survive
        assert (run_dir / "attempt_001" / "metrics.json").exists()
        assert (run_dir / "attempt_001" / "patch.json").exists()

        # Medium files MUST survive
        assert (run_dir / "attempt_001" / "timing.rpt").exists()

        # Heavy files should be gone
        assert not (run_dir / "attempt_001" / "design.odb").exists()
        assert not (run_dir / "attempt_001" / "floorplan.def").exists()

    def test_gc_preserves_tips(self, tmp_path: Path) -> None:
        """Branch tip attempt directories are never pruned."""
        run_dir = tmp_path / "run_001"
        _make_attempt(run_dir, "attempt_001")
        _make_attempt(run_dir, "attempt_002")

        gc = ArtifactGC(policy="keep_pass_and_tips")
        gc.collect(
            run_dir,
            branch_tips={"attempt_002"},
            passed_attempts=set(),
        )

        # attempt_002 is a tip -- its heavy files survive
        assert (run_dir / "attempt_002" / "design.odb").exists()
        assert (run_dir / "attempt_002" / "floorplan.def").exists()

        # attempt_001 is NOT a tip -- heavy files should be deleted
        assert not (run_dir / "attempt_001" / "design.odb").exists()

    def test_gc_preserves_passed_attempts(self, tmp_path: Path) -> None:
        """Passed attempts are kept under 'keep_pass_and_tips' policy."""
        run_dir = tmp_path / "run_001"
        _make_attempt(run_dir, "attempt_001")
        _make_attempt(run_dir, "attempt_002")
        _make_attempt(run_dir, "attempt_003")

        gc = ArtifactGC(policy="keep_pass_and_tips")
        gc.collect(
            run_dir,
            branch_tips=set(),
            passed_attempts={"attempt_001"},
        )

        # Passed attempt heavy files survive
        assert (run_dir / "attempt_001" / "design.odb").exists()
        # Non-passed, non-tip attempts get pruned
        assert not (run_dir / "attempt_002" / "design.odb").exists()
        assert not (run_dir / "attempt_003" / "design.odb").exists()

    def test_gc_dry_run(self, tmp_path: Path) -> None:
        """dry_run=True reports what would be deleted without deleting."""
        run_dir = tmp_path / "run_001"
        _make_attempt(run_dir, "attempt_001")

        gc = ArtifactGC(policy="keep_pass_and_tips")
        result = gc.collect(
            run_dir,
            branch_tips=set(),
            passed_attempts=set(),
            dry_run=True,
        )

        # Should report deletions
        assert result.files_deleted >= 2
        assert result.bytes_freed > 0

        # But files should still exist
        assert (run_dir / "attempt_001" / "design.odb").exists()
        assert (run_dir / "attempt_001" / "floorplan.def").exists()

    def test_gc_keep_all_policy_deletes_nothing(self, tmp_path: Path) -> None:
        """'keep_all' policy does not delete any files."""
        run_dir = tmp_path / "run_001"
        _make_attempt(run_dir, "attempt_001")

        gc = ArtifactGC(policy="keep_all")
        result = gc.collect(
            run_dir,
            branch_tips=set(),
            passed_attempts=set(),
        )

        assert result.files_deleted == 0
        assert result.bytes_freed == 0
        assert (run_dir / "attempt_001" / "design.odb").exists()

    def test_gc_nonexistent_run_dir(self, tmp_path: Path) -> None:
        """GC on a non-existent run_dir returns empty result without error."""
        gc = ArtifactGC()
        result = gc.collect(
            tmp_path / "does_not_exist",
            branch_tips=set(),
            passed_attempts=set(),
        )
        assert result.files_scanned == 0
        assert result.files_deleted == 0

    def test_gc_multiple_attempts_mixed(self, tmp_path: Path) -> None:
        """GC handles a mix of tips, passed, and unpassed attempts."""
        run_dir = tmp_path / "run_001"
        _make_attempt(run_dir, "attempt_001")  # passed
        _make_attempt(run_dir, "attempt_002")  # not protected
        _make_attempt(run_dir, "attempt_003")  # tip

        gc = ArtifactGC(policy="keep_pass_and_tips")
        gc.collect(
            run_dir,
            branch_tips={"attempt_003"},
            passed_attempts={"attempt_001"},
        )

        # Passed: kept
        assert (run_dir / "attempt_001" / "design.odb").exists()
        # Not protected: pruned
        assert not (run_dir / "attempt_002" / "design.odb").exists()
        # Tip: kept
        assert (run_dir / "attempt_003" / "design.odb").exists()


# ---------------------------------------------------------------------------
# Disk usage & should_gc
# ---------------------------------------------------------------------------


class TestDiskUsage:
    """Test disk usage calculation and GC triggering threshold."""

    def test_get_disk_usage_bytes(self, tmp_path: Path) -> None:
        """get_disk_usage_bytes returns correct total."""
        run_dir = tmp_path / "run_001"
        run_dir.mkdir()
        (run_dir / "file_a.txt").write_bytes(b"A" * 1000)
        (run_dir / "file_b.txt").write_bytes(b"B" * 500)

        gc = ArtifactGC()
        usage = gc.get_disk_usage_bytes(run_dir)
        assert usage == 1500

    def test_get_disk_usage_empty(self, tmp_path: Path) -> None:
        """Empty directory returns 0."""
        run_dir = tmp_path / "run_001"
        run_dir.mkdir()
        gc = ArtifactGC()
        assert gc.get_disk_usage_bytes(run_dir) == 0

    def test_get_disk_usage_nonexistent(self, tmp_path: Path) -> None:
        """Non-existent directory returns 0."""
        gc = ArtifactGC()
        assert gc.get_disk_usage_bytes(tmp_path / "nope") == 0

    def test_should_gc_under_limit(self, tmp_path: Path) -> None:
        """should_gc returns False when under the disk limit."""
        run_dir = tmp_path / "run_001"
        run_dir.mkdir()
        (run_dir / "small.txt").write_bytes(b"x" * 100)

        gc = ArtifactGC(max_run_disk_gb=1.0)
        assert gc.should_gc(run_dir) is False

    def test_should_gc_over_limit(self, tmp_path: Path) -> None:
        """should_gc returns True when over the disk limit."""
        run_dir = tmp_path / "run_001"
        run_dir.mkdir()
        (run_dir / "big.txt").write_bytes(b"x" * 100)

        # Set absurdly small limit (1 byte)
        gc = ArtifactGC(max_run_disk_gb=0.0000000001)
        assert gc.should_gc(run_dir) is True


# ---------------------------------------------------------------------------
# GCResult dataclass
# ---------------------------------------------------------------------------


class TestGCResult:
    """Test the GCResult dataclass."""

    def test_default_errors_is_empty_list(self) -> None:
        """Default errors field is an empty list (not None)."""
        result = GCResult()
        assert result.errors == []
        assert isinstance(result.errors, list)

    def test_separate_error_lists(self) -> None:
        """Each GCResult instance has its own errors list."""
        r1 = GCResult()
        r2 = GCResult()
        r1.errors.append("error_a")
        assert r2.errors == []
