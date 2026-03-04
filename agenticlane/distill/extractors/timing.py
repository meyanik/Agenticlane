"""Timing metric extractor.

Parses ``artifacts/timing.rpt`` written by MockExecutionAdapter (or real
OpenROAD STA reports) and extracts setup WNS, TNS, and clock period.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional


class TimingExtractor:
    """Extract timing metrics from a timing report file."""

    name: str = "timing"

    def extract(self, attempt_dir: Path, stage_name: str) -> dict[str, Any]:
        """Parse ``artifacts/timing.rpt`` and return timing metrics.

        Returns
        -------
        dict
            Keys: ``setup_wns_ns`` (dict[str, float|None]),
            ``tns_ns`` (float|None), ``clock_period_ns`` (float|None).
        """
        result: dict[str, Any] = {
            "setup_wns_ns": {},
            "tns_ns": None,
            "clock_period_ns": None,
        }

        timing_path = attempt_dir / "artifacts" / "timing.rpt"
        if not timing_path.is_file():
            return result

        try:
            text = timing_path.read_text(errors="replace")
        except OSError:
            return result

        result["setup_wns_ns"] = _parse_wns(text)
        result["tns_ns"] = _parse_tns(text)
        result["clock_period_ns"] = _parse_clock_period(text)
        return result


def _parse_wns(text: str) -> dict[str, Optional[float]]:
    """Extract per-corner setup WNS values.

    Tries real OpenSTA ``report_checks`` output first, then falls back
    to mock format.
    """
    wns: dict[str, Optional[float]] = {}

    # --- Real OpenSTA format ---
    # "worst slack -0.15" or "worst negative slack -0.15"
    m = re.search(r"worst\s+(?:negative\s+)?slack\s+([-+]?\d+\.?\d*)", text, re.IGNORECASE)
    if m:
        wns["default"] = float(m.group(1))
        return wns

    # OpenSTA per-corner: "Startpoint: ... slack (MET|VIOLATED) -0.15"
    # Look for "slack" value at end of path summary
    m = re.search(r"slack\s+\((?:MET|VIOLATED)\)\s+([-+]?\d+\.?\d*)", text)
    if m:
        wns["default"] = float(m.group(1))
        return wns

    # --- Mock format ---
    # "Setup WNS: <val> ns"
    m = re.search(r"Setup\s+WNS:\s+([-+]?\d+\.?\d*)\s*ns", text)
    if m:
        wns["default"] = float(m.group(1))
        return wns

    # Fallback: bare "wns <value>"
    m = re.search(r"^wns\s+([-+]?\d+\.?\d*)", text, re.MULTILINE)
    if m:
        wns["default"] = float(m.group(1))

    return wns


def _parse_tns(text: str) -> Optional[float]:
    """Extract total negative slack."""
    # --- Real OpenSTA format ---
    # "tns -1.234" in summary line
    m = re.search(r"^tns\s+([-+]?\d+\.?\d*)", text, re.MULTILINE | re.IGNORECASE)
    if m:
        return float(m.group(1))

    # "total negative slack" or "Total Negative Slack: -1.234"
    m = re.search(r"total\s+negative\s+slack[:\s]+([-+]?\d+\.?\d*)", text, re.IGNORECASE)
    if m:
        return float(m.group(1))

    # --- Mock format ---
    m = re.search(r"Setup\s+TNS:\s+([-+]?\d+\.?\d*)\s*ns", text)
    if m:
        return float(m.group(1))

    return None


def _parse_clock_period(text: str) -> Optional[float]:
    """Extract clock period in ns."""
    # --- Real OpenSTA format ---
    # "Clock clk  Period: 10.000" or "period 10.000"
    m = re.search(r"[Pp]eriod[:\s]+([\d.]+)", text)
    if m:
        return float(m.group(1))

    # --- Mock format ---
    m = re.search(r"Clock\s+\w+\s+Period:\s+([-+]?\d+\.?\d*)", text)
    if m:
        return float(m.group(1))
    return None
