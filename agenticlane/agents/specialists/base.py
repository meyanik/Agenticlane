"""Base specialist agent for AgenticLane.

Specialist agents are triggered on plateau detection to provide domain-specific
analysis and recommendations for breaking out of optimization stalls.  Each
specialist focuses on a specific aspect (timing, routability, DRC) and returns
structured advice that the worker agent can incorporate into its next patch.
"""

from __future__ import annotations

import logging
import time
from abc import abstractmethod
from pathlib import Path
from typing import Any, Literal, Optional

import jinja2

from agenticlane.agents.llm_provider import LLMProvider
from agenticlane.config.models import AgenticLaneConfig
from agenticlane.schemas.evidence import EvidencePack
from agenticlane.schemas.metrics import MetricsPayload
from agenticlane.schemas.specialist import SpecialistAdvice

logger = logging.getLogger(__name__)

# Default template directory (same as workers)
_DEFAULT_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "prompts"


class BaseSpecialist:
    """Abstract base class for specialist agents.

    Specialists analyze plateau situations and provide domain-specific
    advice on how to break out of the stall.  Each specialist:

    1. Receives current metrics, evidence, and score history.
    2. Renders a domain-specific Jinja2 prompt template.
    3. Calls the LLM for structured ``SpecialistAdvice`` output.
    4. Returns the advice for the orchestrator/worker to incorporate.
    """

    #: Subclasses must set this to identify the specialist type.
    specialist_type: Literal["timing", "routability", "drc"]

    def __init__(
        self,
        llm_provider: LLMProvider,
        config: AgenticLaneConfig,
        template_dir: Optional[Path] = None,
    ) -> None:
        self.llm_provider = llm_provider
        self.config = config
        tpl_dir = template_dir or _DEFAULT_TEMPLATE_DIR
        self.jinja_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(tpl_dir)),
            undefined=jinja2.StrictUndefined,
        )

    async def analyze(
        self,
        stage: str,
        metrics: MetricsPayload,
        evidence: EvidencePack,
        history: list[float],
        *,
        plateau_info: Optional[dict[str, Any]] = None,
    ) -> SpecialistAdvice | None:
        """Analyze the current plateau and return structured advice.

        Args:
            stage: Stage name where the plateau was detected.
            metrics: Current metrics payload from the latest attempt.
            evidence: Evidence pack from the latest attempt.
            history: Score history for the current branch (list of floats).
            plateau_info: Optional plateau diagnostics from PlateauDetector.

        Returns:
            SpecialistAdvice on success, ``None`` on LLM failure.
        """
        history_len = len(history)
        plateau_window = plateau_info.get("window", history_len) if plateau_info else history_len
        logger.info(
            "Specialist %s analyzing plateau stage=%s history_len=%d plateau_window=%s",
            self.specialist_type,
            stage,
            history_len,
            plateau_window,
            extra={
                "agent": "specialist",
                "specialist_type": self.specialist_type,
                "event": "analyze_start",
                "stage": stage,
                "history_len": history_len,
                "score_history": history,
                "plateau_info": plateau_info or {},
                "has_crash": evidence.crash_info is not None,
                "error_count": len(evidence.errors),
            },
        )

        context = self._build_context(
            stage=stage,
            metrics=metrics,
            evidence=evidence,
            history=history,
            plateau_info=plateau_info,
        )
        prompt = self._render_prompt(context)

        logger.debug(
            "Specialist %s calling LLM stage=%s prompt_len=%d",
            self.specialist_type,
            stage,
            len(prompt),
            extra={
                "agent": "specialist",
                "specialist_type": self.specialist_type,
                "event": "llm_call",
                "stage": stage,
                "prompt_length": len(prompt),
            },
        )

        t0 = time.monotonic()
        advice = await self.llm_provider.generate(
            prompt=prompt,
            response_model=SpecialistAdvice,
            stage=stage,
            attempt=len(history),
            role="specialist",
        )
        latency_ms = (time.monotonic() - t0) * 1000

        if advice is None:
            logger.warning(
                "Specialist %s LLM returned None stage=%s latency_ms=%.1f",
                self.specialist_type,
                stage,
                latency_ms,
                extra={
                    "agent": "specialist",
                    "specialist_type": self.specialist_type,
                    "event": "llm_failure",
                    "stage": stage,
                    "latency_ms": round(latency_ms, 1),
                },
            )
        else:
            # Ensure specialist_type and stage are set correctly
            advice.specialist_type = self.specialist_type
            advice.stage = stage
            if plateau_info is not None:
                advice.plateau_info = plateau_info

            rec_count = len(advice.detailed_recommendations) if advice.detailed_recommendations else 0
            logger.info(
                "Specialist %s advice ready stage=%s "
                "recommendations=%d latency_ms=%.1f summary=%s",
                self.specialist_type,
                stage,
                rec_count,
                latency_ms,
                (advice.strategy_summary or "")[:120],
                extra={
                    "agent": "specialist",
                    "specialist_type": self.specialist_type,
                    "event": "analyze_done",
                    "stage": stage,
                    "recommendation_count": rec_count,
                    "recommendations": [
                        {"knob": r.knob_name, "value": r.recommended_value}
                        for r in (advice.detailed_recommendations or [])
                    ],
                    "recommended_knobs": advice.recommended_knobs,
                    "focus_areas": advice.focus_areas,
                    "confidence": advice.confidence,
                    "latency_ms": round(latency_ms, 1),
                    "strategy_summary": (advice.strategy_summary or "")[:120],
                },
            )

        return advice

    def _build_context(
        self,
        *,
        stage: str,
        metrics: MetricsPayload,
        evidence: EvidencePack,
        history: list[float],
        plateau_info: Optional[dict[str, Any]],
    ) -> dict[str, Any]:
        """Assemble all context for prompt rendering.

        Subclasses can override to add domain-specific context.
        """
        ctx: dict[str, Any] = {
            "specialist_type": self.specialist_type,
            "stage": stage,
            "metrics_summary": self._format_metrics(metrics),
            "evidence_summary": self._format_evidence(evidence),
            "score_history": history,
            "plateau_info": plateau_info or {},
            "intent_summary": self._format_intent(),
            "domain_context": self._get_domain_context(metrics, evidence),
            "advice_schema": SpecialistAdvice.model_json_schema(),
        }
        return ctx

    def _render_prompt(self, context: dict[str, Any]) -> str:
        """Render the specialist-specific Jinja2 template.

        Falls back to ``specialist_base.j2`` if the domain-specific
        template is not found.
        """
        template_name = f"specialist_{self.specialist_type}.j2"
        try:
            template = self.jinja_env.get_template(template_name)
        except jinja2.TemplateNotFound:
            template = self.jinja_env.get_template("specialist_base.j2")
        return template.render(**context)

    @abstractmethod
    def _get_domain_context(
        self,
        metrics: MetricsPayload,
        evidence: EvidencePack,
    ) -> dict[str, Any]:
        """Return domain-specific context for the prompt template.

        Subclasses must implement this to extract relevant metrics
        and evidence for their domain (timing, routability, DRC).
        """
        ...

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
            lines.append(
                f"  - Congestion overflow: {metrics.route.congestion_overflow_pct}%"
            )
        if metrics.signoff and metrics.signoff.drc_count is not None:
            lines.append(f"  - DRC violations: {metrics.signoff.drc_count}")
        if metrics.synthesis and metrics.synthesis.cell_count is not None:
            lines.append(f"  - Synth cell count: {metrics.synthesis.cell_count}")
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
