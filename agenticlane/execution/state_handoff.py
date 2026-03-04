"""State baton I/O -- tokenize, save, load, and rebase state files.

LibreLane state files may contain absolute paths that are only valid on
the machine / workspace where they were produced.  This module provides
helpers that:

1. **Tokenize** absolute paths so they become portable
   (``/abs/run_root/foo`` -> ``{{RUN_ROOT}}/foo``).
2. **Detokenize** them back when loading into a (potentially different)
   workspace.
3. **Save / load** state dicts as JSON with automatic token round-trip.
4. **Write a rebase map** that logs every path transformation for
   auditability.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_TOKEN = "{{RUN_ROOT}}"


# ------------------------------------------------------------------
# Single-path helpers
# ------------------------------------------------------------------


def tokenize_path(abs_path: str, run_root: str) -> str:
    """Convert an absolute path under *run_root* to a tokenized form.

    Example::

        tokenize_path("/tmp/runs/foo/bar.json", "/tmp/runs")
        # => "{{RUN_ROOT}}/foo/bar.json"

    If *abs_path* does not fall under *run_root* it is returned
    unchanged.
    """
    # Normalize both paths so trailing-slash differences don't matter.
    norm_abs = os.path.normpath(abs_path)
    norm_root = os.path.normpath(run_root)

    try:
        rel = os.path.relpath(norm_abs, norm_root)
    except ValueError:
        # On Windows, relpath raises ValueError for paths on different drives.
        return abs_path

    # relpath returns paths starting with ".." when the target is
    # outside run_root -- keep those untouched.
    if rel.startswith(".."):
        return abs_path

    return f"{_TOKEN}/{rel}"


def detokenize_path(tokenized: str, run_root: str) -> str:
    """Resolve a tokenized path back to an absolute path.

    Example::

        detokenize_path("{{RUN_ROOT}}/foo/bar.json", "/tmp/runs")
        # => "/tmp/runs/foo/bar.json"
    """
    if _TOKEN in tokenized:
        return tokenized.replace(_TOKEN, os.path.normpath(run_root))
    return tokenized


# ------------------------------------------------------------------
# Recursive dict helpers
# ------------------------------------------------------------------


def _looks_like_path(value: str) -> bool:
    """Heuristic: treat a string as path-like if it starts with ``/``
    or contains the run-root token."""
    return value.startswith("/") or _TOKEN in value


def tokenize_state(state_data: dict[str, Any], run_root: str) -> dict[str, Any]:
    """Recursively tokenize all path-like string values in *state_data*.

    Returns a **new** dict (the original is not mutated).
    """
    result: dict[str, Any] = _walk(state_data, lambda v: tokenize_path(v, run_root), run_root)
    return result


def detokenize_state(state_data: dict[str, Any], run_root: str) -> dict[str, Any]:
    """Recursively detokenize all tokenized string values in *state_data*.

    Returns a **new** dict (the original is not mutated).
    """
    result: dict[str, Any] = _walk(
        state_data, lambda v: detokenize_path(v, run_root), run_root
    )
    return result


def _walk(
    obj: Any,
    transform: Any,
    run_root: str,
) -> Any:
    """Recursively walk *obj*, applying *transform* to path-like strings."""
    if isinstance(obj, dict):
        return {k: _walk(v, transform, run_root) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_walk(item, transform, run_root) for item in obj]
    if isinstance(obj, str) and _looks_like_path(obj):
        return transform(obj)
    return obj


# ------------------------------------------------------------------
# Persist / load
# ------------------------------------------------------------------


def save_state(
    state_data: dict[str, Any],
    path: Path,
    run_root: str,
) -> dict[str, str]:
    """Tokenize *state_data*, write it to *path* as JSON, and return
    a rebase map recording every path transformation.

    The rebase map is a ``{original_path: tokenized_path}`` dict.
    """
    rebase_map: dict[str, str] = {}

    def _tokenize_and_record(value: str) -> str:
        tokenized = tokenize_path(value, run_root)
        if tokenized != value:
            rebase_map[value] = tokenized
        return tokenized

    tokenized_state = _walk(state_data, _tokenize_and_record, run_root)

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(tokenized_state, fh, indent=2)

    logger.info("Saved state to %s (%d paths tokenized)", path, len(rebase_map))
    return rebase_map


def load_state(path: Path, run_root: str) -> dict[str, Any]:
    """Read a tokenized state JSON from *path* and detokenize it."""
    with open(path, encoding="utf-8") as fh:
        raw: dict[str, Any] = json.load(fh)
    return detokenize_state(raw, run_root)


def write_rebase_map(rebase_map: dict[str, str], path: Path) -> None:
    """Write the rebase map to *path* as JSON for auditability."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(rebase_map, fh, indent=2)
    logger.info("Wrote rebase map to %s (%d entries)", path, len(rebase_map))
