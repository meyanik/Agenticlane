"""Power metric extractor.

Reads power report files produced by OpenROAD's ``report_power`` command
and extracts total, internal, switching, and leakage power metrics.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional


class PowerExtractor:
    """Extract power metrics from a power report file."""

    name: str = "power"

    def extract(self, attempt_dir: Path, stage_name: str) -> dict[str, Any]:
        """Parse ``artifacts/power.rpt`` if available.

        Returns
        -------
        dict
            Keys: ``total_power_mw``, ``internal_power_mw``,
            ``switching_power_mw``, ``leakage_power_mw``,
            ``leakage_pct`` (all float|None).
        """
        result: dict[str, Any] = {
            "total_power_mw": None,
            "internal_power_mw": None,
            "switching_power_mw": None,
            "leakage_power_mw": None,
            "leakage_pct": None,
        }

        power_path = attempt_dir / "artifacts" / "power.rpt"
        if not power_path.is_file():
            return result

        try:
            text = power_path.read_text(errors="replace")
        except OSError:
            return result

        parsed = _parse_power_components(text)
        result["total_power_mw"] = parsed.get("total")
        result["internal_power_mw"] = parsed.get("internal")
        result["switching_power_mw"] = parsed.get("switching")
        result["leakage_power_mw"] = parsed.get("leakage")
        result["leakage_pct"] = parsed.get("leakage_pct")

        # If we got total but not from tabular, try the summary-line parser
        if result["total_power_mw"] is None:
            result["total_power_mw"] = _parse_total_power_summary(text)

        # Compute leakage_pct from components if not already set
        if (
            result["leakage_pct"] is None
            and result["leakage_power_mw"] is not None
            and result["total_power_mw"] is not None
            and result["total_power_mw"] > 0
        ):
            result["leakage_pct"] = (
                result["leakage_power_mw"] / result["total_power_mw"]
            ) * 100

        # Try explicit "Leakage: X%" line if still missing
        if result["leakage_pct"] is None:
            result["leakage_pct"] = _parse_leakage_pct_line(text)

        return result


def _parse_power_components(text: str) -> dict[str, Optional[float]]:
    """Extract power components from OpenROAD tabular format.

    OpenROAD ``report_power`` outputs a table like:
    4-column: ``Total  <internal>  <switching>  <leakage>  <total>``
    3-column: ``Total  <internal>  <switching>  <total>``

    All values are in Watts; we convert to milliwatts.
    """
    result: dict[str, Optional[float]] = {}

    # 4-column format: "Total  <internal> <switching> <leakage> <total>"
    m = re.search(
        r"^Total\s+([\d.eE+-]+)\s+([\d.eE+-]+)\s+([\d.eE+-]+)\s+([\d.eE+-]+)",
        text,
        re.MULTILINE,
    )
    if m:
        internal_w = float(m.group(1))
        switching_w = float(m.group(2))
        leakage_w = float(m.group(3))
        total_w = float(m.group(4))
        result["internal"] = internal_w * 1000
        result["switching"] = switching_w * 1000
        result["leakage"] = leakage_w * 1000
        result["total"] = total_w * 1000
        if total_w > 0:
            result["leakage_pct"] = (leakage_w / total_w) * 100
        return result

    # 3-column format: "Total  <internal> <switching> <total>"
    m = re.search(
        r"^Total\s+([\d.eE+-]+)\s+([\d.eE+-]+)\s+([\d.eE+-]+)",
        text,
        re.MULTILINE,
    )
    if m:
        internal_w = float(m.group(1))
        switching_w = float(m.group(2))
        total_w = float(m.group(3))
        result["internal"] = internal_w * 1000
        result["switching"] = switching_w * 1000
        result["total"] = total_w * 1000
        # Derive leakage as residual
        leakage_w = total_w - internal_w - switching_w
        if leakage_w >= 0:
            result["leakage"] = leakage_w * 1000
            if total_w > 0:
                result["leakage_pct"] = (leakage_w / total_w) * 100
        return result

    # Mock/simple format: "Total Power: 12.5 mW"
    m = re.search(r"Total\s+[Pp]ower:\s+([\d.]+)\s*mW", text)
    if m:
        result["total"] = float(m.group(1))

    # Try to parse individual component lines (mock format)
    m_int = re.search(r"Internal\s+[Pp]ower:\s+([\d.]+)\s*mW", text)
    if m_int:
        result["internal"] = float(m_int.group(1))

    m_sw = re.search(r"Switching\s+[Pp]ower:\s+([\d.]+)\s*mW", text)
    if m_sw:
        result["switching"] = float(m_sw.group(1))

    m_leak = re.search(r"Leakage\s+[Pp]ower:\s+([\d.]+)\s*mW", text)
    if m_leak:
        result["leakage"] = float(m_leak.group(1))

    return result


def _parse_total_power_summary(text: str) -> Optional[float]:
    """Extract total power from a summary line like 'Total Power = 1.234 mW'."""
    m = re.search(
        r"Total\s+[Pp]ower\s*[=:]\s*([\d.eE+-]+)\s*(mW|W)",
        text,
        re.IGNORECASE,
    )
    if m:
        val = float(m.group(1))
        unit = m.group(2)
        if unit.upper() == "W":
            val *= 1000
        return val
    return None


def _parse_leakage_pct_line(text: str) -> Optional[float]:
    """Extract leakage percentage from an explicit 'Leakage: X%' line."""
    m = re.search(r"[Ll]eakage:\s+([\d.]+)%", text)
    if m:
        return float(m.group(1))
    return None
