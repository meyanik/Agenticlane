"""Path rebasing utilities for state dicts.

When a state dict produced under one run root must be consumed under a
different run root (e.g. Docker mount-point change), ``rebase_paths``
rewrites every absolute path that falls under *old_root* so it points
to the corresponding location under *new_root*.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def rebase_paths(
    state_data: dict[str, Any],
    old_root: str,
    new_root: str,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Rewrite all paths under *old_root* to live under *new_root*.

    Parameters
    ----------
    state_data:
        The state dict to rebase (not mutated).
    old_root:
        Absolute path of the original run root.
    new_root:
        Absolute path of the new run root.

    Returns
    -------
    tuple[dict, dict]
        ``(rebased_state, rebase_map)`` where *rebase_map* maps each
        original path to its rebased value.
    """
    rebase_map: dict[str, str] = {}
    norm_old = os.path.normpath(old_root)
    norm_new = os.path.normpath(new_root)

    def _rebase(value: str) -> str:
        norm_val = os.path.normpath(value)
        try:
            rel = os.path.relpath(norm_val, norm_old)
        except ValueError:
            return value

        if rel.startswith(".."):
            return value

        rebased = os.path.join(norm_new, rel)
        if rebased != value:
            rebase_map[value] = rebased
        return rebased

    rebased_state = _walk(state_data, _rebase)

    logger.info(
        "Rebased %d paths from %s -> %s",
        len(rebase_map),
        old_root,
        new_root,
    )
    return rebased_state, rebase_map


# ------------------------------------------------------------------
# Internal recursive walker
# ------------------------------------------------------------------


def _walk(obj: Any, transform: Any) -> Any:
    """Recursively apply *transform* to path-like strings in *obj*."""
    if isinstance(obj, dict):
        return {k: _walk(v, transform) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_walk(item, transform) for item in obj]
    if isinstance(obj, str) and obj.startswith("/"):
        return transform(obj)
    return obj
