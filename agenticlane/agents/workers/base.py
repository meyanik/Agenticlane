"""Base worker agent for AgenticLane.

Proposes optimized patches for a specific stage based on current metrics,
evidence, and history.  Stage-specific workers inherit and customize knob
filtering and prompt rendering.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Optional

import jinja2

from agenticlane.agents.llm_provider import LLMProvider
from agenticlane.config.knobs import KnobSpec, get_knobs_for_stage
from agenticlane.config.models import AgenticLaneConfig
from agenticlane.orchestration.compaction import LessonsLearned
from agenticlane.schemas.constraints import ConstraintDigest
from agenticlane.schemas.evidence import EvidencePack
from agenticlane.schemas.metrics import MetricsPayload
from agenticlane.schemas.patch import Patch, PatchRejected

logger = logging.getLogger(__name__)

# Default template directory
_DEFAULT_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "prompts"


class WorkerAgent:
    """Base worker agent that proposes patches via LLM.

    Builds a context dict from metrics/evidence/constraints, renders
    a Jinja2 prompt template, calls the LLM for structured output,
    and returns a Patch proposal.
    """

    def __init__(
        self,
        llm_provider: LLMProvider,
        stage_name: str,
        config: AgenticLaneConfig,
        template_dir: Optional[Path] = None,
    ) -> None:
        self.llm_provider = llm_provider
        self.stage_name = stage_name
        self.config = config
        tpl_dir = template_dir or _DEFAULT_TEMPLATE_DIR
        self.jinja_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(tpl_dir)),
            undefined=jinja2.StrictUndefined,
        )

    async def propose_patch(
        self,
        current_metrics: MetricsPayload,
        evidence_pack: EvidencePack,
        *,
        constraint_digest: Optional[ConstraintDigest] = None,
        attempt_number: int = 1,
        last_rejection: Optional[PatchRejected] = None,
        lessons_learned: Optional[LessonsLearned] = None,
        lessons_markdown: Optional[str] = None,
        synth_stats: Any = None,
        post_synth_patch: Any = None,
        module_context: Optional[dict[str, Any]] = None,
        rag_context: Optional[str] = None,
    ) -> Patch | None:
        """Propose a patch for the current stage.

        Returns Patch on success, None on LLM failure.
        """
        logger.info(
            "WorkerAgent proposing patch for stage=%s attempt=%d has_rejection=%s",
            self.stage_name,
            attempt_number,
            last_rejection is not None,
            extra={
                "agent": "worker",
                "event": "propose_patch_start",
                "stage": self.stage_name,
                "attempt": attempt_number,
                "has_last_rejection": last_rejection is not None,
                "has_lessons": bool(lessons_markdown),
                "has_module_context": module_context is not None,
            },
        )

        context = self._build_context(
            current_metrics=current_metrics,
            evidence_pack=evidence_pack,
            constraint_digest=constraint_digest,
            attempt_number=attempt_number,
            last_rejection=last_rejection,
            lessons_markdown=lessons_markdown,
            synth_stats=synth_stats,
            post_synth_patch=post_synth_patch,
            module_context=module_context,
            rag_context=rag_context,
        )
        prompt = self._render_prompt(context)

        logger.debug(
            "WorkerAgent calling LLM for stage=%s attempt=%d prompt_len=%d",
            self.stage_name,
            attempt_number,
            len(prompt),
            extra={
                "agent": "worker",
                "event": "llm_call",
                "stage": self.stage_name,
                "attempt": attempt_number,
                "prompt_length": len(prompt),
            },
        )

        t0 = time.monotonic()
        patch = await self.llm_provider.generate(
            prompt=prompt,
            response_model=Patch,
            stage=self.stage_name,
            attempt=attempt_number,
            role="worker",
        )
        latency_ms = (time.monotonic() - t0) * 1000

        if patch is None:
            logger.warning(
                "WorkerAgent LLM call returned None for stage=%s attempt=%d latency_ms=%.1f",
                self.stage_name,
                attempt_number,
                latency_ms,
                extra={
                    "agent": "worker",
                    "event": "llm_failure",
                    "stage": self.stage_name,
                    "attempt": attempt_number,
                    "latency_ms": round(latency_ms, 1),
                },
            )
        else:
            knob_count = len(patch.config_vars) if patch.config_vars else 0
            logger.info(
                "WorkerAgent patch proposed for stage=%s attempt=%d "
                "patch_id=%s knobs=%d latency_ms=%.1f rationale=%s",
                self.stage_name,
                attempt_number,
                patch.patch_id,
                knob_count,
                latency_ms,
                (patch.rationale or "")[:120],
                extra={
                    "agent": "worker",
                    "event": "propose_patch_done",
                    "stage": self.stage_name,
                    "attempt": attempt_number,
                    "patch_id": patch.patch_id,
                    "patch_types": patch.types,
                    "knob_count": knob_count,
                    "knob_keys": list(patch.config_vars.keys()) if patch.config_vars else [],
                    "latency_ms": round(latency_ms, 1),
                    "rationale_summary": (patch.rationale or "")[:120],
                },
            )

        return patch

    def _build_context(
        self,
        *,
        current_metrics: MetricsPayload,
        evidence_pack: EvidencePack,
        constraint_digest: Optional[ConstraintDigest],
        attempt_number: int,
        last_rejection: Optional[PatchRejected],
        lessons_markdown: Optional[str],
        synth_stats: Any = None,
        post_synth_patch: Any = None,
        module_context: Optional[dict[str, Any]] = None,
        rag_context: Optional[str] = None,
    ) -> dict[str, Any]:
        """Assemble all context for prompt rendering."""
        allowed_knobs = self._get_allowed_knobs()
        locked_vars = self.config.constraints.locked_vars

        ctx: dict[str, Any] = {
            "stage": self.stage_name,
            "attempt_number": attempt_number,
            "intent_summary": self._format_intent(),
            "allowed_knobs": allowed_knobs,
            "knobs_table": self._format_knobs_table(allowed_knobs),
            "locked_constraints": locked_vars,
            "metrics_summary": self._format_metrics(current_metrics),
            "evidence_summary": self._format_evidence(evidence_pack),
            "constraint_digest": (
                constraint_digest.model_dump(mode="json") if constraint_digest else None
            ),
            "lessons_learned": lessons_markdown or "",
            "last_rejection_feedback": (
                last_rejection.remediation_hint if last_rejection else None
            ),
            "patch_schema": Patch.model_json_schema(),
            "synth_stats": synth_stats,
            "post_synth_patch": post_synth_patch,
            "module_context": module_context,
            "rag_context": rag_context or "",
        }
        return ctx

    def _render_prompt(self, context: dict[str, Any]) -> str:
        """Render the stage-specific Jinja2 template."""
        template_name = f"{self.stage_name.lower()}.j2"
        try:
            template = self.jinja_env.get_template(template_name)
            logger.debug(
                "WorkerAgent using stage-specific template %s for stage=%s",
                template_name,
                self.stage_name,
                extra={
                    "agent": "worker",
                    "event": "template_loaded",
                    "stage": self.stage_name,
                    "template": template_name,
                    "fallback": False,
                },
            )
        except jinja2.TemplateNotFound:
            # Fall back to generic worker template
            template = self.jinja_env.get_template("worker_base.j2")
            logger.debug(
                "WorkerAgent falling back to worker_base.j2 for stage=%s",
                self.stage_name,
                extra={
                    "agent": "worker",
                    "event": "template_loaded",
                    "stage": self.stage_name,
                    "template": "worker_base.j2",
                    "fallback": True,
                },
            )
        return template.render(**context)

    def _get_allowed_knobs(self) -> dict[str, KnobSpec]:
        """Return knobs applicable to this stage, excluding locked ones."""
        locked = set(self.config.constraints.locked_vars)
        stage_knobs = get_knobs_for_stage(self.stage_name)
        return {spec.name: spec for spec in stage_knobs if spec.name not in locked}

    def _format_intent(self) -> str:
        """Format intent weights as readable string."""
        weights = self.config.intent.weights_hint
        parts = [f"{k}: {v * 100:.0f}%" for k, v in weights.items()]
        prompt = self.config.intent.prompt
        if prompt:
            return f"{prompt} ({', '.join(parts)})"
        return ", ".join(parts)

    @staticmethod
    def _format_metrics(metrics: MetricsPayload) -> str:
        """Format metrics payload as a concise text summary."""
        lines: list[str] = []
        if metrics.timing and metrics.timing.setup_wns_ns:
            for corner, wns in metrics.timing.setup_wns_ns.items():
                lines.append(f"  - Setup WNS ({corner}): {wns} ns")
        if metrics.physical:
            if metrics.physical.core_area_um2 is not None:
                lines.append(f"  - Core area: {metrics.physical.core_area_um2} um\u00b2")
            if metrics.physical.utilization_pct is not None:
                lines.append(f"  - Utilization: {metrics.physical.utilization_pct}%")
        if metrics.route and metrics.route.congestion_overflow_pct is not None:
            lines.append(f"  - Congestion overflow: {metrics.route.congestion_overflow_pct}%")
        if metrics.signoff and metrics.signoff.drc_count is not None:
            lines.append(f"  - DRC violations: {metrics.signoff.drc_count}")
        if metrics.synthesis:
            if metrics.synthesis.cell_count is not None:
                lines.append(f"  - Synth cell count: {metrics.synthesis.cell_count}")
            if metrics.synthesis.net_count is not None:
                lines.append(f"  - Synth net count: {metrics.synthesis.net_count}")
            if metrics.synthesis.area_estimate_um2 is not None:
                lines.append(f"  - Synth area estimate: {metrics.synthesis.area_estimate_um2} um\u00b2")
        return "\n".join(lines) if lines else "No metrics available."

    @staticmethod
    def _format_evidence(evidence: EvidencePack) -> str:
        """Format evidence pack as a concise text summary."""
        lines: list[str] = []
        if evidence.crash_info:
            lines.append(f"  - CRASH: {evidence.crash_info.crash_type}")
        for err in evidence.errors[:5]:
            lines.append(f"  - ERROR [{err.source}]: {err.message}")
        for warn in evidence.warnings[:5]:
            lines.append(f"  - WARNING [{warn.source}]: {warn.message}")
        for hs in evidence.spatial_hotspots[:3]:
            lines.append(
                f"  - HOTSPOT ({hs.type}): bin ({hs.grid_bin.get('x', '?')}, "
                f"{hs.grid_bin.get('y', '?')}) severity={hs.severity}"
            )
        return "\n".join(lines) if lines else "No issues found."

    @staticmethod
    def _format_knobs_table(knobs: dict[str, KnobSpec]) -> str:
        """Format allowed knobs as a markdown table."""
        if not knobs:
            return "No knobs available."
        lines = ["| Knob | Type | Min | Max | Default |"]
        lines.append("|---|---|---|---|---|")
        for name, spec in knobs.items():
            dtype = spec.dtype.__name__
            rmin = spec.range_min if spec.range_min is not None else "-"
            rmax = spec.range_max if spec.range_max is not None else "-"
            default = spec.default
            lines.append(f"| {name} | {dtype} | {rmin} | {rmax} | {default} |")
        return "\n".join(lines)
