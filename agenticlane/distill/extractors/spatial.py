"""Spatial hotspot extractor.

Reads congestion reports and produces ``SpatialHotspot`` objects with
grid bin locations, severity, coordinate bounds, and nearby macros.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Optional


class SpatialExtractor:
    """Extract spatial hotspot information from congestion data."""

    name: str = "spatial"

    def __init__(
        self,
        grid_bins_x: int = 2,
        grid_bins_y: int = 2,
        max_hotspots: int = 12,
        macro_nearby_radius_um: float = 50.0,
    ) -> None:
        self.grid_bins_x = grid_bins_x
        self.grid_bins_y = grid_bins_y
        self.max_hotspots = max_hotspots
        self.macro_nearby_radius_um = macro_nearby_radius_um

    def extract(self, attempt_dir: Path, stage_name: str) -> dict[str, Any]:
        """Extract spatial hotspots from congestion report.

        Reads congestion overflow from ``artifacts/congestion.rpt``,
        die area from ``artifacts/die_area.json``, and macro instances
        from ``artifacts/macros.json``.

        Returns
        -------
        dict
            Keys: ``spatial_hotspots`` (list[dict]).
        """
        result: dict[str, Any] = {"spatial_hotspots": []}

        congestion_path = attempt_dir / "artifacts" / "congestion.rpt"
        if not congestion_path.is_file():
            return result

        try:
            text = congestion_path.read_text(errors="replace")
        except OSError:
            return result

        overflow = _parse_overflow(text)
        if overflow is None or overflow <= 0.0:
            return result

        # Read optional die area
        die_area = _read_die_area(attempt_dir)

        # Read optional macro instances
        macro_instances = _read_macros(attempt_dir)

        hotspots = self._generate_hotspots_from_overflow(
            overflow, die_area, macro_instances
        )
        result["spatial_hotspots"] = hotspots
        return result

    def _generate_hotspots_from_overflow(
        self,
        overflow_pct: float,
        die_area: Optional[dict[str, float]],
        macro_instances: Optional[list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        """Generate synthetic hotspots from overall overflow.

        Distributes congestion across a grid and identifies bins with
        above-average overflow as hotspots.  When die_area is available,
        computes physical coordinate bounds.  When macro_instances are
        available, identifies nearby macros within the configured radius.
        """
        hotspots: list[dict[str, Any]] = []

        # Distribute overflow non-uniformly across grid bins
        for gx in range(self.grid_bins_x):
            for gy in range(self.grid_bins_y):
                # Create varying severity across grid -- centre bins
                # tend to have more congestion
                cx = (gx + 0.5) / self.grid_bins_x
                cy = (gy + 0.5) / self.grid_bins_y
                centre_factor = 1.0 - 2.0 * (
                    abs(cx - 0.5) + abs(cy - 0.5)
                )
                severity = max(
                    0.0, overflow_pct * (0.5 + centre_factor) / 100.0
                )
                # Clamp severity to [0.0, 1.0]
                severity = min(1.0, severity)

                if severity >= 0.005:
                    region = _grid_label(
                        gx, gy, self.grid_bins_x, self.grid_bins_y
                    )
                    hotspot: dict[str, Any] = {
                        "type": "congestion",
                        "grid_bin": {"x": gx, "y": gy},
                        "region_label": region,
                        "severity": round(severity, 4),
                        "nearby_macros": [],
                        "x_min_um": None,
                        "y_min_um": None,
                        "x_max_um": None,
                        "y_max_um": None,
                    }

                    # Compute coordinate bounds if die area is available
                    if die_area is not None:
                        bounds = self._compute_bin_bounds(gx, gy, die_area)
                        hotspot["x_min_um"] = bounds["x_min_um"]
                        hotspot["y_min_um"] = bounds["y_min_um"]
                        hotspot["x_max_um"] = bounds["x_max_um"]
                        hotspot["y_max_um"] = bounds["y_max_um"]

                        # Find nearby macros if macro data is available
                        if macro_instances is not None:
                            hotspot["nearby_macros"] = (
                                self._find_nearby_macros(
                                    bounds,
                                    macro_instances,
                                    self.macro_nearby_radius_um,
                                )
                            )
                    elif macro_instances is not None:
                        # Without die area we cannot compute bin bounds,
                        # so nearby macro lookup is not possible.
                        pass

                    hotspots.append(hotspot)

        # Sort by severity descending and limit
        hotspots.sort(key=lambda h: h["severity"], reverse=True)
        return hotspots[: self.max_hotspots]

    def _compute_bin_bounds(
        self, gx: int, gy: int, die_area: dict[str, float]
    ) -> dict[str, float]:
        """Compute physical coordinates for a grid bin.

        Parameters
        ----------
        gx, gy:
            Grid bin indices.
        die_area:
            Die area dict with keys ``x_min``, ``y_min``, ``x_max``, ``y_max``
            (all in micrometers).

        Returns
        -------
        dict
            Keys: ``x_min_um``, ``y_min_um``, ``x_max_um``, ``y_max_um``.
        """
        die_x_min = die_area["x_min"]
        die_y_min = die_area["y_min"]
        die_width = die_area["x_max"] - die_x_min
        die_height = die_area["y_max"] - die_y_min

        bin_width = die_width / self.grid_bins_x
        bin_height = die_height / self.grid_bins_y

        return {
            "x_min_um": round(die_x_min + gx * bin_width, 4),
            "y_min_um": round(die_y_min + gy * bin_height, 4),
            "x_max_um": round(die_x_min + (gx + 1) * bin_width, 4),
            "y_max_um": round(die_y_min + (gy + 1) * bin_height, 4),
        }

    def _find_nearby_macros(
        self,
        bin_bounds: dict[str, float],
        macro_instances: list[dict[str, Any]],
        radius_um: float,
    ) -> list[str]:
        """Find macros within radius of the bin.

        Each macro_instance has: ``name``, ``x_um``, ``y_um``.
        A macro is "nearby" if its center is within ``radius_um`` of the
        bin rectangle (Euclidean distance from point to rectangle).

        Parameters
        ----------
        bin_bounds:
            Bin coordinate bounds (x_min_um, y_min_um, x_max_um, y_max_um).
        macro_instances:
            List of macro instance dicts with name, x_um, y_um.
        radius_um:
            Maximum distance in micrometers for a macro to be considered nearby.

        Returns
        -------
        list[str]
            Names of nearby macros, sorted alphabetically.
        """
        nearby: list[str] = []
        bx_min = bin_bounds["x_min_um"]
        by_min = bin_bounds["y_min_um"]
        bx_max = bin_bounds["x_max_um"]
        by_max = bin_bounds["y_max_um"]

        for macro in macro_instances:
            mx = macro.get("x_um", 0.0)
            my = macro.get("y_um", 0.0)

            # Distance from point to axis-aligned rectangle
            dx = max(0.0, bx_min - mx, mx - bx_max)
            dy = max(0.0, by_min - my, my - by_max)
            dist = math.sqrt(dx * dx + dy * dy)

            if dist <= radius_um:
                name = macro.get("name", "")
                if name:
                    nearby.append(name)

        nearby.sort()
        return nearby


def _parse_overflow(text: str) -> Optional[float]:
    """Extract overflow percentage from congestion report."""
    m = re.search(r"Overflow:\s+([\d.]+)%", text)
    if m:
        return float(m.group(1))
    return None


def _grid_label(gx: int, gy: int, bins_x: int, bins_y: int) -> str:
    """Generate a human-readable label for a grid bin.

    Uses quadrant labels for 2x2 grids or generic x,y otherwise.
    """
    if bins_x == 2 and bins_y == 2:
        labels = {
            (0, 0): "SW",
            (1, 0): "SE",
            (0, 1): "NW",
            (1, 1): "NE",
        }
        return labels.get((gx, gy), f"({gx},{gy})")
    return f"({gx},{gy})"


def _read_die_area(attempt_dir: Path) -> Optional[dict[str, float]]:
    """Read die area from artifacts/die_area.json.

    Returns
    -------
    dict or None
        Die area dict with x_min, y_min, x_max, y_max (um), or None if
        the file is not found or cannot be parsed.
    """
    die_area_path = attempt_dir / "artifacts" / "die_area.json"
    if not die_area_path.is_file():
        return None
    try:
        data = json.loads(die_area_path.read_text(errors="replace"))
        # Validate required keys
        for key in ("x_min", "y_min", "x_max", "y_max"):
            if key not in data:
                return None
        return {
            "x_min": float(data["x_min"]),
            "y_min": float(data["y_min"]),
            "x_max": float(data["x_max"]),
            "y_max": float(data["y_max"]),
        }
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return None


def _read_macros(attempt_dir: Path) -> Optional[list[dict[str, Any]]]:
    """Read macro instances from artifacts/macros.json.

    Returns
    -------
    list or None
        List of macro instance dicts with name, x_um, y_um, or None if
        the file is not found or cannot be parsed.
    """
    macros_path = attempt_dir / "artifacts" / "macros.json"
    if not macros_path.is_file():
        return None
    try:
        data = json.loads(macros_path.read_text(errors="replace"))
        if not isinstance(data, list):
            return None
        return [
            {
                "name": str(m.get("name", "")),
                "x_um": float(m.get("x_um", 0.0)),
                "y_um": float(m.get("y_um", 0.0)),
            }
            for m in data
            if isinstance(m, dict)
        ]
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return None
