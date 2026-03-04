"""Area metric extractor.

Parses ``artifacts/area.rpt`` and extracts core area and utilization.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional


class AreaExtractor:
    """Extract physical area metrics from an area report file."""

    name: str = "area"

    def extract(self, attempt_dir: Path, stage_name: str) -> dict[str, Any]:
        """Parse ``artifacts/area.rpt`` and return area metrics.

        Returns
        -------
        dict
            Keys: ``core_area_um2`` (float|None),
            ``utilization_pct`` (float|None).
        """
        result: dict[str, Any] = {
            "core_area_um2": None,
            "utilization_pct": None,
        }

        area_path = attempt_dir / "artifacts" / "area.rpt"
        if not area_path.is_file():
            return result

        try:
            text = area_path.read_text(errors="replace")
        except OSError:
            return result

        result["core_area_um2"] = _parse_area(text)
        result["utilization_pct"] = _parse_utilization(text)
        return result


def _parse_area(text: str) -> Optional[float]:
    """Extract core area in um^2."""
    # --- Real OpenROAD report_design_area format ---
    # "Design area 12345.678 u^2" or "Design area 12345 um^2"
    m = re.search(r"Design\s+area\s+([\d.]+)\s*(?:u\^2|um\^2|µm²)", text, re.IGNORECASE)
    if m:
        return float(m.group(1))

    # --- Mock format ---
    # "Core area: <val> um^2"
    m = re.search(r"Core\s+area:\s+([\d.]+)\s*um\^2", text)
    if m:
        return float(m.group(1))

    return None


def _parse_utilization(text: str) -> Optional[float]:
    """Extract core utilization percentage."""
    # --- Real OpenROAD format ---
    # "Design area 1234 u^2 56% utilization" or "Utilization: 56.78%"
    m = re.search(r"([\d.]+)%\s*utilization", text, re.IGNORECASE)
    if m:
        return float(m.group(1))

    # --- Mock / structured format ---
    m = re.search(r"Utilization:\s+([\d.]+)%", text)
    if m:
        return float(m.group(1))
    m = re.search(r"Core\s+utilization:\s+([\d.]+)%", text)
    if m:
        return float(m.group(1))

    return None
