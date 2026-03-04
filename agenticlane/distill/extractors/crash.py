"""Crash diagnostic extractor.

CRITICAL: This extractor must NEVER itself raise an exception.  Every
code path is wrapped in try/except so that a crash during distillation
does not hide the original tool crash.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional


class CrashExtractor:
    """Extract crash diagnostics from crash.log.

    This extractor is designed to be maximally resilient -- it will
    never raise an exception regardless of the input.
    """

    name: str = "crash"

    def extract(self, attempt_dir: Path, stage_name: str) -> dict[str, Any]:
        """Read ``crash.log`` and produce crash diagnostics.

        Returns
        -------
        dict
            Keys: ``crash_info`` (dict|None).  The inner dict has keys
            ``crash_type``, ``stderr_tail``, ``error_signature``.
        """
        try:
            return self._safe_extract(attempt_dir, stage_name)
        except Exception:
            # Absolute last resort -- return a minimal crash_info
            return {
                "crash_info": {
                    "crash_type": "unknown",
                    "stderr_tail": None,
                    "error_signature": "distillation_error",
                }
            }

    def _safe_extract(
        self, attempt_dir: Path, stage_name: str
    ) -> dict[str, Any]:
        """Inner extraction logic (may raise, caught by ``extract``)."""
        crash_path = attempt_dir / "crash.log"
        if not crash_path.is_file():
            return {"crash_info": None}

        try:
            text = crash_path.read_text(errors="replace")
        except OSError:
            return {
                "crash_info": {
                    "crash_type": "unknown",
                    "stderr_tail": None,
                    "error_signature": "crash_log_unreadable",
                }
            }

        crash_type = _detect_crash_type(text)
        stderr_tail = _get_tail(text, max_lines=200)
        error_sig = _extract_signature(text)

        return {
            "crash_info": {
                "crash_type": crash_type,
                "stderr_tail": stderr_tail,
                "error_signature": error_sig,
            }
        }


def _detect_crash_type(text: str) -> str:
    """Heuristically determine crash type from log content."""
    text_lower = text.lower()
    if "oom" in text_lower or "out of memory" in text_lower:
        return "oom_killed"
    if "timeout" in text_lower or "exceeded timeout" in text_lower:
        return "timeout"
    if "sigsegv" in text_lower or "core dumped" in text_lower:
        return "tool_crash"
    if "sigkill" in text_lower or "killed" in text_lower:
        return "oom_killed"
    if "error" in text_lower or "abort" in text_lower:
        return "tool_crash"
    return "unknown"


def _get_tail(text: str, max_lines: int = 200) -> Optional[str]:
    """Return the last ``max_lines`` lines of the text."""
    if not text.strip():
        return None
    lines = text.splitlines()
    tail_lines = lines[-max_lines:]
    return "\n".join(tail_lines)


def _extract_signature(text: str) -> Optional[str]:
    """Extract a short error signature for deduplication."""
    # Look for common error patterns
    # 1. Segfault with function name
    m = re.search(r"(SIGSEGV|Segmentation fault).*?(\w+::\w+)", text)
    if m:
        return f"{m.group(1)}:{m.group(2)}"

    # 2. OpenROAD crash with source location
    m = re.search(r"at\s+(\w+\.\w+:\d+)", text)
    if m:
        return f"crash_at:{m.group(1)}"

    # 3. OOM
    m = re.search(r"(Out of memory|OOM).*?(\d+\.?\d*\s*GB)", text, re.IGNORECASE)
    if m:
        return f"OOM:{m.group(2).strip()}"

    # 4. Timeout
    m = re.search(r"(timeout|exceeded).*?(\d+\.?\d*s)", text, re.IGNORECASE)
    if m:
        return f"timeout:{m.group(2)}"

    # 5. Generic first error line
    for line in text.splitlines():
        line_stripped = line.strip()
        if line_stripped and not line_stripped.startswith("#"):
            # Use first 80 chars of the first non-comment line
            return line_stripped[:80]

    return None
