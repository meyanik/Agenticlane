"""Runtime metric extractor.

Reads runtime information from ``state_out.json`` or derives it from
the ``ExecutionResult.runtime_seconds`` field.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class RuntimeExtractor:
    """Extract runtime metrics."""

    name: str = "runtime"

    def extract(self, attempt_dir: Path, stage_name: str) -> dict[str, Any]:
        """Extract runtime seconds from state_out.json.

        Returns
        -------
        dict
            Keys: ``stage_seconds`` (float|None).
        """
        result: dict[str, Any] = {"stage_seconds": None}

        state_path = attempt_dir / "state_out.json"
        if not state_path.is_file():
            return result

        try:
            data = json.loads(state_path.read_text(errors="replace"))
            snapshot = data.get("metrics_snapshot", {})
            runtime = snapshot.get("runtime_seconds")
            if runtime is not None:
                result["stage_seconds"] = float(runtime)
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            pass

        return result
