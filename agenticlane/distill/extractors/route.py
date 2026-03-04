"""Route (congestion) metric extractor.

Parses ``artifacts/congestion.rpt`` and extracts congestion overflow.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional


class RouteExtractor:
    """Extract routing/congestion metrics from a congestion report."""

    name: str = "route"

    def extract(self, attempt_dir: Path, stage_name: str) -> dict[str, Any]:
        """Parse ``artifacts/congestion.rpt`` and return routing metrics.

        Returns
        -------
        dict
            Keys: ``congestion_overflow_pct`` (float|None).
        """
        result: dict[str, Any] = {
            "congestion_overflow_pct": None,
        }

        congestion_path = attempt_dir / "artifacts" / "congestion.rpt"
        if not congestion_path.is_file():
            return result

        try:
            text = congestion_path.read_text(errors="replace")
        except OSError:
            return result

        result["congestion_overflow_pct"] = _parse_overflow(text)
        return result


def _parse_overflow(text: str) -> Optional[float]:
    """Extract overflow percentage."""
    # --- Real OpenROAD report_routing_metrics format ---
    # "Total overflow: 1234" or "Number of overflow: 56"
    m = re.search(r"[Tt]otal\s+overflow[:\s]+([\d.]+)", text)
    if m:
        return float(m.group(1))

    # "Overflow:" percentage line (from real or mock)
    m = re.search(r"Overflow:\s+([\d.]+)%?", text)
    if m:
        return float(m.group(1))

    # "Number of overflow" (integer count)
    m = re.search(r"[Nn]umber\s+of\s+overflow[:\s]+([\d.]+)", text)
    if m:
        return float(m.group(1))

    return None
