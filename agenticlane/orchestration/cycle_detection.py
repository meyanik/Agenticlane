"""P5.6 Cycle Detection for AgenticLane.

Detects when the optimization loop is proposing patches that have already
been tried, indicating a cycle.  Uses deterministic SHA-256 hashing of
patch data with key-order-independent serialization.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


class CycleDetector:
    """Detect repeated (cyclic) patches via deterministic hashing."""

    def __init__(self) -> None:
        self._seen_hashes: dict[str, int] = {}  # hash -> attempt_num

    def compute_patch_hash(self, patch_data: dict[str, object]) -> str:
        """Return a deterministic SHA-256 hex digest of *patch_data*.

        Keys are sorted recursively so that insertion order does not
        affect the hash.
        """
        canonical = json.dumps(patch_data, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def check_and_record(
        self, patch_data: dict[str, object], attempt_num: int
    ) -> tuple[bool, int | None]:
        """Check whether *patch_data* has been seen before.

        Returns ``(is_cycle, previous_attempt_num)``.  If the patch is
        new, it is recorded and ``(False, None)`` is returned.
        """
        h = self.compute_patch_hash(patch_data)
        if h in self._seen_hashes:
            return True, self._seen_hashes[h]
        self._seen_hashes[h] = attempt_num
        return False, None

    def log_cycle_event(
        self,
        log_path: Path,
        patch_hash: str,
        current_attempt: int,
        previous_attempt: int,
    ) -> None:
        """Append a cycle event as a JSON line to *log_path*."""
        event = {
            "event": "cycle_detected",
            "patch_hash": patch_hash,
            "current_attempt": current_attempt,
            "previous_attempt": previous_attempt,
        }
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, sort_keys=True) + "\n")

    def reset(self) -> None:
        """Clear all recorded hashes."""
        self._seen_hashes.clear()
