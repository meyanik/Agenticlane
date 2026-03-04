"""Constraint digest extractor.

Reads SDC files from ``artifacts/`` to extract a ``ConstraintDigest``
with clock definitions, exception counts, and delay counts.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


class ConstraintExtractor:
    """Extract constraint digest from SDC files."""

    name: str = "constraints"

    def extract(self, attempt_dir: Path, stage_name: str) -> dict[str, Any]:
        """Parse SDC files and produce a constraint digest.

        Scans ``artifacts/*.sdc`` for clock definitions, timing
        exceptions, and delay constraints.

        Returns
        -------
        dict
            Keys: ``constraint_digest`` (dict) with sub-keys
            ``clocks``, ``exceptions``, ``delays``, ``uncertainty``,
            ``opaque``, ``notes``.
        """
        digest: dict[str, Any] = {
            "constraint_digest": {
                "opaque": False,
                "clocks": [],
                "exceptions": {
                    "false_path_count": 0,
                    "multicycle_path_count": 0,
                    "disable_timing_count": 0,
                },
                "delays": {
                    "set_max_delay_count": 0,
                    "set_min_delay_count": 0,
                },
                "uncertainty": {
                    "set_clock_uncertainty_count": 0,
                },
                "notes": [],
            }
        }

        artifacts_dir = attempt_dir / "artifacts"
        if not artifacts_dir.is_dir():
            digest["constraint_digest"]["notes"].append("No artifacts directory found")
            return digest

        sdc_files = sorted(artifacts_dir.glob("*.sdc"))
        if not sdc_files:
            digest["constraint_digest"]["notes"].append("No SDC files found")
            return digest

        for sdc_path in sdc_files:
            try:
                text = sdc_path.read_text(errors="replace")
                self._parse_sdc(text, digest["constraint_digest"])
            except OSError:
                digest["constraint_digest"]["notes"].append(
                    f"Could not read {sdc_path.name}"
                )

        return digest

    def _parse_sdc(self, text: str, digest: dict[str, Any]) -> None:
        """Parse a single SDC file and update the digest."""
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # Clock definitions
            m = re.match(
                r"create_clock\s+.*-period\s+([\d.]+)\s+.*?(\[get_ports\s+(\w+)\]|(\w+))",
                line,
            )
            if m:
                period = float(m.group(1))
                port = m.group(3) or m.group(4) or "unknown"
                # Derive clock name from the port
                clock_name = _find_clock_name(line) or port
                digest["clocks"].append(
                    {
                        "name": clock_name,
                        "period_ns": period,
                        "targets": [port],
                    }
                )
                continue

            # Simpler create_clock pattern
            m = re.match(r"create_clock\s+.*-period\s+([\d.]+)", line)
            if m:
                period = float(m.group(1))
                clock_name = _find_clock_name(line) or "clk"
                digest["clocks"].append(
                    {
                        "name": clock_name,
                        "period_ns": period,
                        "targets": [],
                    }
                )
                continue

            # Exception counts
            if line.startswith("set_false_path"):
                digest["exceptions"]["false_path_count"] += 1
            elif line.startswith("set_multicycle_path"):
                digest["exceptions"]["multicycle_path_count"] += 1
            elif line.startswith("set_disable_timing"):
                digest["exceptions"]["disable_timing_count"] += 1

            # Delay counts
            if line.startswith("set_max_delay"):
                digest["delays"]["set_max_delay_count"] += 1
            elif line.startswith("set_min_delay"):
                digest["delays"]["set_min_delay_count"] += 1

            # Uncertainty
            if line.startswith("set_clock_uncertainty"):
                digest["uncertainty"]["set_clock_uncertainty_count"] += 1


def _find_clock_name(line: str) -> str | None:
    """Extract -name <clock_name> from a create_clock command."""
    m = re.search(r"-name\s+(\w+)", line)
    return m.group(1) if m else None
