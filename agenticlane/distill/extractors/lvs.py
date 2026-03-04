"""LVS (Layout vs. Schematic) extractor.

Derives LVS pass/fail status from a dedicated LVS report or from the
execution result status.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional


class LVSExtractor:
    """Extract LVS pass/fail status."""

    name: str = "lvs"

    def extract(self, attempt_dir: Path, stage_name: str) -> dict[str, Any]:
        """Extract LVS status.

        Checks ``artifacts/lvs.rpt`` first, then falls back to
        ``state_out.json`` execution status.

        Returns
        -------
        dict
            Keys: ``lvs_pass`` (bool|None).
        """
        result: dict[str, Any] = {"lvs_pass": None}

        # Try dedicated LVS report
        lvs_path = attempt_dir / "artifacts" / "lvs.rpt"
        if lvs_path.is_file():
            try:
                text = lvs_path.read_text(errors="replace")
                result["lvs_pass"] = _parse_lvs_status(text)
                return result
            except OSError:
                pass

        # Fallback: derive from state_out.json status
        state_path = attempt_dir / "state_out.json"
        if state_path.is_file():
            try:
                data = json.loads(state_path.read_text(errors="replace"))
                status = data.get("status", "")
                if status == "success":
                    result["lvs_pass"] = True
                elif status in {"failure", "fail", "error"}:
                    result["lvs_pass"] = False
            except (OSError, json.JSONDecodeError, ValueError):
                pass

        return result


def _parse_lvs_status(text: str) -> Optional[bool]:
    """Parse LVS pass/fail from report text."""
    text_lower = text.lower()

    # --- Real Netgen LVS output ---
    # "Circuits match uniquely." → pass
    if re.search(r"circuits?\s+match\s+uniquely", text_lower):
        return True
    # "Circuits match." (non-uniquely but still a match)
    if re.search(r"circuits?\s+match", text_lower):
        return True
    # "Netlists do not match." or "Circuits do not match."
    if re.search(r"(?:netlists?|circuits?)\s+do\s+not\s+match", text_lower):
        return False
    # "Result: PASS" / "Result: FAIL"
    m = re.search(r"result:\s*(pass|fail)", text_lower)
    if m:
        return m.group(1) == "pass"

    # --- Mock / generic format ---
    if re.search(r"lvs\s+(clean|pass|passed)", text_lower):
        return True
    if re.search(r"lvs\s+(fail|failed|dirty|error)", text_lower):
        return False
    # Check for generic result lines
    if "clean" in text_lower and "lvs" in text_lower:
        return True
    if "error" in text_lower or "mismatch" in text_lower:
        return False
    return None
