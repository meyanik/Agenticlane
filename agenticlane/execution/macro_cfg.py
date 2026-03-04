"""MACRO_PLACEMENT_CFG materialization for AgenticLane.

Converts resolved macro placements to LibreLane's MACRO_PLACEMENT_CFG
text format for manual macro placement control.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from agenticlane.execution.grid_snap import ResolvedMacro

logger = logging.getLogger(__name__)


def format_macro_cfg(macros: list[ResolvedMacro]) -> str:
    """Convert resolved macros to MACRO_PLACEMENT_CFG text format.

    Format: one line per macro, sorted by instance name::

        <instance_name> <x_um> <y_um> <orientation>

    Args:
        macros: List of resolved macro placements.

    Returns:
        MACRO_PLACEMENT_CFG content string, or empty string if no macros.
    """
    if not macros:
        return ""

    sorted_macros = sorted(macros, key=lambda m: m.instance)
    lines: list[str] = []
    for m in sorted_macros:
        lines.append(f"{m.instance} {m.x_um:.3f} {m.y_um:.3f} {m.orientation}")

    return "\n".join(lines) + "\n"


def write_macro_cfg(
    macros: list[ResolvedMacro],
    output_dir: Path,
    filename: str = "macro_placement.cfg",
) -> Optional[Path]:
    """Write MACRO_PLACEMENT_CFG file to disk.

    Args:
        macros: List of resolved macro placements.
        output_dir: Directory to write the file in.
        filename: Output file name.

    Returns:
        Path to the written file, or None if no macros (nothing written).
    """
    content = format_macro_cfg(macros)
    if not content:
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = output_dir / filename
    cfg_path.write_text(content)
    logger.info("Wrote MACRO_PLACEMENT_CFG to %s (%d macros)", cfg_path, len(macros))
    return cfg_path


def parse_macro_cfg(content: str) -> list[dict[str, object]]:
    """Parse a MACRO_PLACEMENT_CFG file back into macro dicts.

    Useful for testing and validation.  Each line::

        <instance_name> <x_um> <y_um> <orientation>

    Returns:
        List of dicts with keys: instance, x_um, y_um, orientation.
    """
    macros: list[dict[str, object]] = []
    for line in content.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 4:
            continue
        macros.append({
            "instance": parts[0],
            "x_um": float(parts[1]),
            "y_um": float(parts[2]),
            "orientation": parts[3],
        })
    return macros
