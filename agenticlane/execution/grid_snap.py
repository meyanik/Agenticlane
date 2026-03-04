"""Grid snap and macro placement resolution for AgenticLane.

Implements the deterministic hint->coords resolver, placement grid snapping
(site size + DBU roundtrip), and collision detection per Appendix D of
the Build Spec v0.6.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Literal, Optional

from agenticlane.schemas.patch import MacroPlacement

logger = logging.getLogger(__name__)

# Valid orientations per spec
VALID_ORIENTATIONS = {"N", "S", "E", "W", "FN", "FS", "FE", "FW"}

# Location hint -> (x_pct, y_pct) of core bbox
HINT_COORDS: dict[str, tuple[float, float]] = {
    "SW": (0.1, 0.1),
    "SE": (0.9, 0.1),
    "NW": (0.1, 0.9),
    "NE": (0.9, 0.9),
    "CENTER": (0.5, 0.5),
    "PERIPHERY": (0.1, 0.5),
}


@dataclass
class CoreBBox:
    """Core bounding box in micrometers."""

    x_min: float
    y_min: float
    x_max: float
    y_max: float

    @property
    def width(self) -> float:
        return self.x_max - self.x_min

    @property
    def height(self) -> float:
        return self.y_max - self.y_min


@dataclass
class PlacementSite:
    """Placement site dimensions from tech LEF."""

    width_um: float
    height_um: float


@dataclass
class ResolvedMacro:
    """A macro placement with resolved coordinates."""

    instance: str
    x_um: float
    y_um: float
    orientation: str
    width_um: float = 0.0
    height_um: float = 0.0


def resolve_hint_to_coords(
    hint: str,
    core_bbox: CoreBBox,
) -> tuple[float, float]:
    """Convert a location hint to (x_um, y_um) coordinates.

    Args:
        hint: One of NW, NE, SW, SE, CENTER, PERIPHERY.
        core_bbox: Core bounding box.

    Returns:
        (x_um, y_um) coordinate pair.

    Raises:
        ValueError: If hint is not recognized.
    """
    hint_upper = hint.upper()
    if hint_upper not in HINT_COORDS:
        raise ValueError(
            f"Unknown location hint: {hint!r}. "
            f"Valid: {sorted(HINT_COORDS.keys())}"
        )
    x_pct, y_pct = HINT_COORDS[hint_upper]
    x = core_bbox.x_min + x_pct * core_bbox.width
    y = core_bbox.y_min + y_pct * core_bbox.height
    return (x, y)


def snap_to_grid(
    x: float,
    y: float,
    site: PlacementSite,
    dbu_per_um: float = 1000.0,
    rounding: Literal["nearest", "floor", "ceil"] = "nearest",
) -> tuple[float, float]:
    """Snap coordinates to placement site grid with DBU roundtrip.

    Algorithm (Appendix D):
    1. Snap to site grid: x = round(x / w) * w
    2. DBU roundtrip: x_dbu = int(round(x * dbu_per_um)); x = x_dbu / dbu_per_um
    """
    # Step 1: Snap to site grid
    if rounding == "nearest":
        sx = round(x / site.width_um) * site.width_um
        sy = round(y / site.height_um) * site.height_um
    elif rounding == "floor":
        sx = math.floor(x / site.width_um) * site.width_um
        sy = math.floor(y / site.height_um) * site.height_um
    else:  # ceil
        sx = math.ceil(x / site.width_um) * site.width_um
        sy = math.ceil(y / site.height_um) * site.height_um

    # Step 2: DBU roundtrip
    sx = int(round(sx * dbu_per_um)) / dbu_per_um
    sy = int(round(sy * dbu_per_um)) / dbu_per_um

    return (sx, sy)


def validate_orientation(orientation: str) -> None:
    """Validate macro orientation.

    Raises ValueError if orientation is not in the allowlist.
    """
    if orientation.upper() not in VALID_ORIENTATIONS:
        raise ValueError(
            f"Invalid orientation: {orientation!r}. "
            f"Valid: {sorted(VALID_ORIENTATIONS)}"
        )


def validate_within_bounds(
    x: float,
    y: float,
    core_bbox: CoreBBox,
    instance: str = "",
) -> None:
    """Validate that coordinates are within core bounds.

    Raises ValueError if out of bounds.
    """
    if x < core_bbox.x_min or x > core_bbox.x_max:
        raise ValueError(
            f"Macro {instance!r} x={x} outside core bounds "
            f"[{core_bbox.x_min}, {core_bbox.x_max}]"
        )
    if y < core_bbox.y_min or y > core_bbox.y_max:
        raise ValueError(
            f"Macro {instance!r} y={y} outside core bounds "
            f"[{core_bbox.y_min}, {core_bbox.y_max}]"
        )


def detect_collisions(
    macros: list[ResolvedMacro],
) -> list[tuple[str, str]]:
    """Detect overlapping macros.

    Returns list of (instance_a, instance_b) collision pairs.
    Simple AABB overlap check using macro width/height.
    """
    collisions: list[tuple[str, str]] = []
    for i in range(len(macros)):
        for j in range(i + 1, len(macros)):
            a, b = macros[i], macros[j]
            if _aabb_overlap(a, b):
                collisions.append((a.instance, b.instance))
    return collisions


def _aabb_overlap(a: ResolvedMacro, b: ResolvedMacro) -> bool:
    """Check if two macros overlap (AABB check)."""
    a_x_max = a.x_um + a.width_um
    a_y_max = a.y_um + a.height_um
    b_x_max = b.x_um + b.width_um
    b_y_max = b.y_um + b.height_um

    return (
        a.x_um < b_x_max
        and a_x_max > b.x_um
        and a.y_um < b_y_max
        and a_y_max > b.y_um
    )


def resolve_collisions_with_offset(
    macros: list[ResolvedMacro],
    offset_step_um: float = 10.0,
    max_iterations: int = 5,
) -> list[ResolvedMacro]:
    """Resolve collisions by applying deterministic offsets.

    Sort macros by instance name for determinism. For each collision,
    shift the later macro (by sorted name) by offset_step_um.

    Args:
        macros: List of resolved macros.
        offset_step_um: Step size for offset.
        max_iterations: Maximum offset iterations.

    Returns:
        List of macros with resolved positions.
    """
    # Sort by instance name for determinism
    sorted_macros = sorted(macros, key=lambda m: m.instance)

    for _iteration in range(max_iterations):
        collisions = detect_collisions(sorted_macros)
        if not collisions:
            break

        # Apply offset to the second macro in each collision pair
        shifted: set[str] = set()
        for _a_name, b_name in collisions:
            if b_name not in shifted:
                for m in sorted_macros:
                    if m.instance == b_name:
                        m.x_um += offset_step_um
                        m.y_um += offset_step_um
                        shifted.add(b_name)
                        break

    return sorted_macros


def resolve_macro_placements(
    placements: list[MacroPlacement],
    core_bbox: CoreBBox,
    site: PlacementSite,
    *,
    known_instances: Optional[set[str]] = None,
    macro_sizes: Optional[dict[str, tuple[float, float]]] = None,
    dbu_per_um: float = 1000.0,
    rounding: Literal["nearest", "floor", "ceil"] = "nearest",
    snap_enabled: bool = True,
    max_iterations: int = 5,
) -> list[ResolvedMacro]:
    """Full macro placement resolution pipeline.

    Steps:
    1. Validate instance names against known_instances (if provided)
    2. Validate orientations
    3. Resolve hint -> coords (or use explicit x/y)
    4. Grid snap
    5. Validate within bounds
    6. Collision detection + resolution

    Args:
        placements: List of MacroPlacement from patch.
        core_bbox: Core bounding box.
        site: Placement site dimensions.
        known_instances: Set of valid macro instance names (optional).
        macro_sizes: Dict of instance -> (width_um, height_um) for collision
            detection.
        dbu_per_um: DBU per micrometer (default 1000).
        rounding: Snap rounding mode.
        snap_enabled: Whether to snap to grid.
        max_iterations: Max collision resolution iterations.

    Returns:
        List of ResolvedMacro with validated, snapped, collision-free positions.

    Raises:
        ValueError: On validation failures.
    """
    resolved: list[ResolvedMacro] = []

    # Sort by instance name for determinism
    sorted_placements = sorted(placements, key=lambda p: p.instance)

    for placement in sorted_placements:
        # Step 1: Validate instance name
        if known_instances is not None and placement.instance not in known_instances:
            raise ValueError(
                f"Unknown macro instance: {placement.instance!r}. "
                f"Known: {sorted(known_instances)}"
            )

        # Step 2: Validate orientation
        validate_orientation(placement.orientation)

        # Step 3: Resolve coordinates
        if placement.x_um is not None and placement.y_um is not None:
            x, y = placement.x_um, placement.y_um
        elif placement.location_hint:
            x, y = resolve_hint_to_coords(placement.location_hint, core_bbox)
        else:
            raise ValueError(
                f"Macro {placement.instance!r}: must specify either "
                f"location_hint or explicit x_um/y_um coordinates"
            )

        # Step 4: Grid snap
        if snap_enabled:
            x, y = snap_to_grid(x, y, site, dbu_per_um, rounding)

        # Step 5: Validate within bounds
        validate_within_bounds(x, y, core_bbox, placement.instance)

        # Build resolved macro
        width, height = 0.0, 0.0
        if macro_sizes and placement.instance in macro_sizes:
            width, height = macro_sizes[placement.instance]

        resolved.append(
            ResolvedMacro(
                instance=placement.instance,
                x_um=x,
                y_um=y,
                orientation=placement.orientation,
                width_um=width,
                height_um=height,
            )
        )

    # Step 6: Collision detection + resolution
    if macro_sizes:
        # Compute offset step as the maximum macro dimension so that a single
        # shift is guaranteed to clear the overlap.
        max_dim = max(
            max(w, h) for w, h in macro_sizes.values()
        ) if macro_sizes else site.width_um * 10
        offset = max(max_dim, site.width_um * 10)
        resolved = resolve_collisions_with_offset(
            resolved,
            offset_step_um=offset,
            max_iterations=max_iterations,
        )

    return resolved
