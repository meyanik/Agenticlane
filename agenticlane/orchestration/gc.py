"""Artifact garbage collection for AgenticLane runs.

Classifies every file produced by an EDA run into one of three tiers
and applies a configurable GC policy to reclaim disk space from failed
or superseded attempts while preserving reproducibility-critical ledger
files.

Tiers
-----
- **Ledger** (``.json``, ``.jsonl``, ``.md``, ``.yaml``):
  Always kept.  These are the provenance trail.
- **Medium** (``.rpt``, ``.log``, ``.txt``, ``.sdc``, ``.tcl``, ``.v``):
  Kept by default; may be compressed or trimmed in future policies.
- **Heavy** (``.odb``, ``.def``, ``.spef``, ``.gds``, ``.spice``):
  GC candidates -- these dominate disk usage and are deleted from
  non-tip, non-passed attempts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Tier classification
# ---------------------------------------------------------------------------


class ArtifactTier(str, Enum):
    """Classification tier for run artifacts."""

    LEDGER = "ledger"   # Always keep: provenance files
    MEDIUM = "medium"   # Policy-based: reports, logs
    HEAVY = "heavy"     # GC candidates: large binary EDA outputs


#: Map from file extension to tier.  Multi-part extensions (e.g.
#: ``.nl.v``) are checked first.
TIER_MAP: dict[str, ArtifactTier] = {
    # Ledger -- never delete
    ".json": ArtifactTier.LEDGER,
    ".jsonl": ArtifactTier.LEDGER,
    ".md": ArtifactTier.LEDGER,
    ".yaml": ArtifactTier.LEDGER,
    ".yml": ArtifactTier.LEDGER,
    # Medium -- keep by default
    ".rpt": ArtifactTier.MEDIUM,
    ".log": ArtifactTier.MEDIUM,
    ".txt": ArtifactTier.MEDIUM,
    ".sdc": ArtifactTier.MEDIUM,
    ".tcl": ArtifactTier.MEDIUM,
    ".v": ArtifactTier.MEDIUM,
    ".nl.v": ArtifactTier.MEDIUM,
    # Heavy -- GC candidates
    ".odb": ArtifactTier.HEAVY,
    ".def": ArtifactTier.HEAVY,
    ".spef": ArtifactTier.HEAVY,
    ".gds": ArtifactTier.HEAVY,
    ".spice": ArtifactTier.HEAVY,
}


def classify_file(path: Path) -> ArtifactTier:
    """Classify a file by its artifact tier.

    Checks multi-part extensions (e.g. ``.nl.v``) before falling back
    to the final suffix.  Unknown extensions default to
    :data:`ArtifactTier.MEDIUM`.

    Args:
        path: Path to the file to classify.

    Returns:
        The corresponding ArtifactTier.
    """
    # Check for multi-part extensions (e.g. foo.nl.v -> ".nl.v")
    if len(path.suffixes) >= 2:
        double_suffix = "".join(path.suffixes[-2:]).lower()
        if double_suffix in TIER_MAP:
            return TIER_MAP[double_suffix]

    suffix = path.suffix.lower()
    return TIER_MAP.get(suffix, ArtifactTier.MEDIUM)


# ---------------------------------------------------------------------------
# GC result
# ---------------------------------------------------------------------------


@dataclass
class GCResult:
    """Summary of a garbage-collection run."""

    files_scanned: int = 0
    files_deleted: int = 0
    bytes_freed: int = 0
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Garbage collector
# ---------------------------------------------------------------------------


class ArtifactGC:
    """Configurable garbage collector for AgenticLane run directories.

    The collector walks attempt directories inside a run and removes
    **heavy-tier** files from attempts that are neither branch tips nor
    in the *passed* set.  Ledger files are *never* deleted regardless of
    policy.

    Args:
        policy: GC policy name.  ``"keep_pass_and_tips"`` keeps heavy
            artifacts only for passed attempts and branch tips.
            ``"keep_all"`` disables deletion.  ``"keep_none"`` deletes
            all heavy artifacts except from tips.
        max_run_disk_gb: Disk-usage threshold (in GiB) above which GC
            should run.
        keep_failed_attempt_artifacts: Number of most-recent failed
            attempts whose heavy artifacts are preserved.
        keep_branch_tips: If ``True``, branch tip attempts are never
            pruned.
        compress_pass_artifacts: *(Future)* Whether to compress rather
            than delete heavy artifacts from passed attempts.
    """

    def __init__(
        self,
        policy: str = "keep_pass_and_tips",
        max_run_disk_gb: float = 40.0,
        keep_failed_attempt_artifacts: int = 1,
        keep_branch_tips: bool = True,
        compress_pass_artifacts: bool = True,
    ) -> None:
        self.policy = policy
        self.max_run_disk_gb = max_run_disk_gb
        self.keep_failed_attempt_artifacts = keep_failed_attempt_artifacts
        self.keep_branch_tips = keep_branch_tips
        self.compress_pass_artifacts = compress_pass_artifacts

    # -- helpers -----------------------------------------------------------

    def get_disk_usage_bytes(self, run_dir: Path) -> int:
        """Calculate total disk usage of *run_dir* in bytes.

        Walks the directory tree and sums file sizes.  Symlinks are not
        followed.

        Args:
            run_dir: Root of the run directory to measure.

        Returns:
            Total size in bytes.
        """
        total = 0
        if not run_dir.exists():
            return 0
        for file_path in run_dir.rglob("*"):
            if file_path.is_file() and not file_path.is_symlink():
                total += file_path.stat().st_size
        return total

    def should_gc(self, run_dir: Path) -> bool:
        """Check whether GC should run based on current disk usage.

        Args:
            run_dir: Root of the run directory to check.

        Returns:
            ``True`` if disk usage exceeds :attr:`max_run_disk_gb`.
        """
        usage_bytes = self.get_disk_usage_bytes(run_dir)
        limit_bytes = int(self.max_run_disk_gb * (1024 ** 3))
        return usage_bytes > limit_bytes

    # -- core collect ------------------------------------------------------

    def collect(
        self,
        run_dir: Path,
        branch_tips: Optional[set[str]] = None,
        passed_attempts: Optional[set[str]] = None,
        dry_run: bool = False,
    ) -> GCResult:
        """Run garbage collection on a run directory.

        Walks every file under *run_dir*.  For each file:

        1. **Ledger** files are *never* deleted.
        2. **Medium** files are kept (current policy does not touch them).
        3. **Heavy** files are deleted **unless** the file lives inside
           an attempt directory that is a branch tip or a passed attempt.

        An "attempt directory" is identified by checking whether any
        ancestor directory name is present in *branch_tips* or
        *passed_attempts*.

        Args:
            run_dir: Root of the run directory.
            branch_tips: Set of attempt directory names that are current
                branch tips (never pruned).
            passed_attempts: Set of attempt directory names that passed
                gating (kept under ``keep_pass_and_tips`` policy).
            dry_run: If ``True``, report what would be deleted but do
                not actually remove files.

        Returns:
            A :class:`GCResult` summarising what was (or would be)
            deleted.
        """
        if branch_tips is None:
            branch_tips = set()
        if passed_attempts is None:
            passed_attempts = set()

        result = GCResult()

        if not run_dir.exists():
            return result

        # Under "keep_all" policy, never delete anything.
        if self.policy == "keep_all":
            return result

        for file_path in run_dir.rglob("*"):
            if not file_path.is_file() or file_path.is_symlink():
                continue

            result.files_scanned += 1
            tier = classify_file(file_path)

            # Ledger files are never deleted
            if tier == ArtifactTier.LEDGER:
                continue

            # Only delete heavy files
            if tier != ArtifactTier.HEAVY:
                continue

            # Check if this file belongs to a protected attempt
            if self._is_protected(file_path, run_dir, branch_tips, passed_attempts):
                continue

            # This heavy file is a GC candidate
            file_size = file_path.stat().st_size
            if not dry_run:
                try:
                    file_path.unlink()
                    result.files_deleted += 1
                    result.bytes_freed += file_size
                except OSError as exc:
                    result.errors.append(f"Failed to delete {file_path}: {exc}")
            else:
                # Dry run: count what *would* be deleted
                result.files_deleted += 1
                result.bytes_freed += file_size

        return result

    def _is_protected(
        self,
        file_path: Path,
        run_dir: Path,
        branch_tips: set[str],
        passed_attempts: set[str],
    ) -> bool:
        """Check if a file is inside a protected attempt directory.

        A file is protected if any component of its path relative to
        *run_dir* matches a branch tip name or a passed attempt name.
        """
        try:
            rel = file_path.relative_to(run_dir)
        except ValueError:
            return False

        parts = rel.parts
        for part in parts:
            if self.keep_branch_tips and part in branch_tips:
                return True
            if self.policy == "keep_pass_and_tips" and part in passed_attempts:
                return True

        return False
