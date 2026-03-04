"""Zero-shot initialization for AgenticLane (P5.4).

Generates the global initialization patch (attempt 0) from an IntentProfile.
All branches start from the same init patch produced here.
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any

from agenticlane.schemas.metrics import SynthesisMetrics
from agenticlane.schemas.patch import Patch

logger = logging.getLogger(__name__)


class ZeroShotInitializer:
    """Generate the global initialization patch from an IntentProfile.

    The zero-shot (attempt 0) produces a global_init_patch.json that
    establishes the starting config for all branches.
    """

    def __init__(
        self,
        *,
        llm_provider: Any | None = None,
        default_config_vars: dict[str, Any] | None = None,
    ) -> None:
        self._llm_provider = llm_provider
        self._default_config_vars = default_config_vars or {}

    async def generate_init_patch(
        self,
        intent: dict[str, Any],
        stage_name: str = "FLOORPLAN",
    ) -> Patch:
        """Generate the initial patch from intent profile.

        If an LLM provider is available, asks the master agent to produce
        an initialization patch.  Otherwise, uses default_config_vars.

        Args:
            intent: Intent profile dict with keys like ``"optimize_for"``,
                ``"target_metrics"``, ``"constraints"``, etc.
            stage_name: Starting stage name.

        Returns:
            A Patch with initial config_vars derived from intent.
        """
        if self._llm_provider is not None:
            return await self._generate_via_llm(intent, stage_name)
        return self._generate_default(intent, stage_name)

    # ------------------------------------------------------------------
    # LLM-based generation
    # ------------------------------------------------------------------

    async def _generate_via_llm(
        self,
        intent: dict[str, Any],
        stage_name: str,
    ) -> Patch:
        """Use master LLM to generate init patch from intent."""
        prompt = self._build_init_prompt(intent, stage_name)

        assert self._llm_provider is not None  # guaranteed by caller
        try:
            result: Patch | None = await self._llm_provider.generate(
                prompt=prompt,
                response_model=Patch,
                role="master",
                stage="INIT",
            )
            if result is not None:
                return result
            return self._generate_default(intent, stage_name)
        except Exception as exc:
            logger.warning(
                "LLM init patch generation failed, falling back to defaults: %s",
                exc,
            )
            return self._generate_default(intent, stage_name)

    # ------------------------------------------------------------------
    # Default (no-LLM) generation
    # ------------------------------------------------------------------

    def _generate_default(
        self,
        intent: dict[str, Any],
        stage_name: str,
    ) -> Patch:
        """Generate a default init patch from intent without LLM."""
        config_vars: dict[str, Any] = dict(self._default_config_vars)

        # Apply intent-driven defaults
        optimize_for = intent.get("optimize_for", "balanced")
        if optimize_for == "timing":
            config_vars.setdefault("FP_CORE_UTIL", 35)
            config_vars.setdefault("FP_ASPECT_RATIO", 1.0)
        elif optimize_for == "area":
            config_vars.setdefault("FP_CORE_UTIL", 65)
            config_vars.setdefault("FP_ASPECT_RATIO", 1.0)
        elif optimize_for == "power":
            config_vars.setdefault("FP_CORE_UTIL", 45)
            config_vars.setdefault("FP_ASPECT_RATIO", 1.0)
        else:  # balanced
            config_vars.setdefault("FP_CORE_UTIL", 50)
            config_vars.setdefault("FP_ASPECT_RATIO", 1.0)

        # Apply any explicit overrides from intent
        for key, value in intent.get("config_overrides", {}).items():
            config_vars[key] = value

        return Patch(
            patch_id="global_init_patch",
            stage=stage_name,
            types=["config_vars"] if config_vars else [],
            config_vars=config_vars,
        )

    # ------------------------------------------------------------------
    # Post-synth refinement
    # ------------------------------------------------------------------

    @staticmethod
    def refine_after_synth(
        synth_metrics: SynthesisMetrics,
        intent: dict[str, Any],
        pdk: str = "sky130A",
    ) -> Patch:
        """Refine init patch using actual synthesis results.

        Uses cell count to compute an appropriate die area, utilization,
        and placement density for the FLOORPLAN stage.
        """
        config_vars: dict[str, Any] = {}

        if synth_metrics.cell_count:
            # Average cell area varies by PDK standard cell library
            avg_cell_area = {"sky130A": 13.0, "gf180mcuD": 20.0}.get(pdk, 15.0)
            cell_area = synth_metrics.cell_count * avg_cell_area

            optimize_for = intent.get("optimize_for", "balanced")
            target_util = {"timing": 35, "area": 60, "power": 45, "balanced": 45}.get(
                optimize_for, 45
            )

            die_area_um2 = cell_area / (target_util / 100.0)
            side = int(math.sqrt(die_area_um2) * 1.20)  # 20% margin for IO/routing
            side = max(side, 100)  # minimum 100um

            config_vars["FP_SIZING"] = "absolute"
            config_vars["DIE_AREA"] = [0, 0, side, side]
            config_vars["FP_CORE_UTIL"] = target_util
            config_vars["PL_TARGET_DENSITY_PCT"] = min(target_util + 10, 80)

            logger.info(
                "Post-synth auto-sizing: %d cells -> %dx%d um die (util=%d%%)",
                synth_metrics.cell_count,
                side,
                side,
                target_util,
            )

        return Patch(
            patch_id="post_synth_refinement",
            stage="FLOORPLAN",
            types=["config_vars"] if config_vars else [],
            config_vars=config_vars,
            rationale=f"Auto-sized from {synth_metrics.cell_count} synthesized cells",
        )

    # ------------------------------------------------------------------
    # Prompt building
    # ------------------------------------------------------------------

    def _build_init_prompt(self, intent: dict[str, Any], stage_name: str) -> str:
        """Build the prompt for the master LLM."""
        lines = [
            f"Generate an initialization patch for stage {stage_name}.",
            f"Optimization target: {intent.get('optimize_for', 'balanced')}",
        ]
        if "target_metrics" in intent:
            lines.append(f"Target metrics: {intent['target_metrics']}")
        if "constraints" in intent:
            lines.append(f"Constraints: {intent['constraints']}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    @staticmethod
    def write_init_patch(patch: Patch, output_dir: Path) -> Path:
        """Write global_init_patch.json to disk.

        Returns:
            Path to the written file.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "global_init_patch.json"
        path.write_text(json.dumps(patch.model_dump(mode="json"), indent=2) + "\n")
        logger.info("Wrote global_init_patch.json to %s", path)
        return path

    @staticmethod
    def load_init_patch(path: Path) -> Patch:
        """Load a global_init_patch.json from disk."""
        data = json.loads(path.read_text())
        return Patch(**data)
