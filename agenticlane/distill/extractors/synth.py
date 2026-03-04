"""Synthesis metrics extractor.

Parses yosys synthesis logs and extracts cell count, net count,
and estimated area from the SYNTH stage workspace.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional


class SynthExtractor:
    """Extract synthesis statistics from yosys logs."""

    name: str = "synth"

    def extract(self, attempt_dir: Path, stage_name: str) -> dict[str, Any]:
        """Parse yosys synthesis logs and return synthesis metrics.

        Looks for ``*-yosys-synthesis/yosys-synthesis.log`` first,
        then falls back to ``flow.log`` in the attempt directory.

        Returns
        -------
        dict
            Keys: ``cell_count`` (int|None), ``net_count`` (int|None),
            ``area_estimate_um2`` (float|None).
        """
        result: dict[str, Any] = {
            "cell_count": None,
            "net_count": None,
            "area_estimate_um2": None,
        }

        text = self._find_and_read_log(attempt_dir)
        if text is None:
            return result

        result["cell_count"] = _parse_cell_count(text)
        result["net_count"] = _parse_net_count(text)
        result["area_estimate_um2"] = _parse_area_estimate(text)
        return result

    @staticmethod
    def _find_and_read_log(attempt_dir: Path) -> Optional[str]:
        """Find the best yosys log file in the attempt directory."""
        # Look for yosys-synthesis log in subdirectories
        for log_path in sorted(attempt_dir.rglob("*yosys-synthesis*.log")):
            try:
                return log_path.read_text(errors="replace")
            except OSError:
                continue

        # Fall back to flow.log
        flow_log = attempt_dir / "flow.log"
        if flow_log.is_file():
            try:
                return flow_log.read_text(errors="replace")
            except OSError:
                pass

        # Also check artifacts directory
        artifacts_log = attempt_dir / "artifacts" / "synth.log"
        if artifacts_log.is_file():
            try:
                return artifacts_log.read_text(errors="replace")
            except OSError:
                pass

        return None


def _parse_cell_count(text: str) -> Optional[int]:
    """Extract total cell count from yosys stat output.

    Matches patterns like:
      ``Number of cells:          1234``
      ``   Number of cells:          1234``
    """
    m = re.search(r"Number\s+of\s+cells:\s+(\d+)", text)
    if m:
        return int(m.group(1))
    return None


def _parse_net_count(text: str) -> Optional[int]:
    """Extract net/wire count from yosys stat output.

    Matches patterns like:
      ``Number of wires:          567``
      ``Number of public wires:   123``
    """
    # Prefer total wires over public wires
    m = re.search(r"Number\s+of\s+wires:\s+(\d+)", text)
    if m:
        return int(m.group(1))
    m = re.search(r"Number\s+of\s+public\s+wires:\s+(\d+)", text)
    if m:
        return int(m.group(1))
    return None


def _parse_area_estimate(text: str) -> Optional[float]:
    """Extract chip area estimate from yosys stat output.

    Matches patterns like:
      ``Chip area for module '\\top': 12345.678900``
      ``Chip area for top-level module '\\counter': 5678.123400``
    """
    m = re.search(
        r"Chip\s+area\s+for\s+(?:top-level\s+)?module\s+['\"]?\\?(\S+?)['\"]?\s*:\s+([\d.]+)",
        text,
    )
    if m:
        return float(m.group(2))
    return None
