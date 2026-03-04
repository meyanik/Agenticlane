"""DRC (Design Rule Check) extractor.

Reads DRC report files or falls back to ``state_out.json`` metrics
to extract violation count and types.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional


class DRCExtractor:
    """Extract DRC violation metrics."""

    name: str = "drc"

    def extract(self, attempt_dir: Path, stage_name: str) -> dict[str, Any]:
        """Extract DRC violation count.

        Tries ``artifacts/drc.rpt`` first, then ``state_out.json``.

        Returns
        -------
        dict
            Keys: ``drc_count`` (int|None), ``drc_types`` (list[str]).
        """
        result: dict[str, Any] = {
            "drc_count": None,
            "drc_types": [],
        }

        # Try dedicated DRC report
        drc_path = attempt_dir / "artifacts" / "drc.rpt"
        if drc_path.is_file():
            try:
                text = drc_path.read_text(errors="replace")
                count = _parse_drc_count(text)
                if count is not None:
                    result["drc_count"] = count
                    result["drc_types"] = _parse_drc_types(text)
                    return result
            except OSError:
                pass

        # Fallback to state_out.json
        state_path = attempt_dir / "state_out.json"
        if state_path.is_file():
            try:
                data = json.loads(state_path.read_text(errors="replace"))
                snapshot = data.get("metrics_snapshot", {})
                drc = snapshot.get("drc_count")
                if drc is not None:
                    result["drc_count"] = int(drc)
            except (OSError, json.JSONDecodeError, ValueError, TypeError):
                pass

        return result


def _parse_drc_count(text: str) -> Optional[int]:
    """Parse total DRC violation count from report text."""
    # --- Real Magic DRC output ---
    # Final line: "[INFO]: TOTAL ERRORS: 0" or
    # "Total DRC errors: 5" or just a count of violation lines
    m = re.search(r"TOTAL\s+ERRORS[:\s]+(\d+)", text, re.IGNORECASE)
    if m:
        return int(m.group(1))

    # --- Real KLayout DRC output ---
    # Typically ends with counts per category
    m = re.search(r"Total\s+(?:DRC\s+)?errors?[:\s]+(\d+)", text, re.IGNORECASE)
    if m:
        return int(m.group(1))

    # --- Mock / common patterns ---
    # "Total violations: 5" or "DRC violations: 5"
    m = re.search(r"(?:Total|DRC)\s+violations?:\s*(\d+)", text, re.IGNORECASE)
    if m:
        return int(m.group(1))

    # --- Magic DRC: count individual violation lines ---
    # Lines like "(Cell:) DRC violation text"
    # Lines starting with a number followed by violation description
    violation_lines = re.findall(
        r"^[\s]*\d+\.\s+.+$|^[\s]*-+\s+.+error.+$",
        text,
        re.MULTILINE | re.IGNORECASE,
    )
    if violation_lines:
        return len(violation_lines)

    # Fallback: count "violation" keyword occurrences
    violations = re.findall(r"violation", text, re.IGNORECASE)
    return len(violations) if violations else None


def _parse_drc_types(text: str) -> list[str]:
    """Extract unique DRC violation type names."""
    types: list[str] = []

    # --- Real Magic DRC: category headers ---
    # Lines like "Metal1.MinWidth" or "Metal2.Spacing" followed by counts
    for m in re.finditer(r"^[\s]*([A-Z]\w+\.\w+)", text, re.MULTILINE):
        t = m.group(1).strip()
        if t and t not in types:
            types.append(t)

    if types:
        return types

    # --- Mock format ---
    # "Type: <name>"
    for m in re.finditer(r"Type:\s*(.+)", text):
        t = m.group(1).strip()
        if t and t not in types:
            types.append(t)
    return types
