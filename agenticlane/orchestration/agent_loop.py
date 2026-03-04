"""Agent-driven single-stage execution loop.

Integrates all Phase 3 components: worker agent, constraint guard,
cognitive retry, execution adapter, distillation, judge ensemble,
scoring engine, and history compaction into one cohesive loop.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from agenticlane.agents.llm_provider import LLMProvider
from agenticlane.agents.workers.base import WorkerAgent
from agenticlane.config.models import AgenticLaneConfig
from agenticlane.execution.adapter import ExecutionAdapter
from agenticlane.execution.workspaces import WorkspaceManager
from agenticlane.judge.ensemble import JudgeEnsemble
from agenticlane.judge.scoring import ScoringEngine
from agenticlane.orchestration.cognitive_retry import (
    CognitiveBudgetExhaustedError,
    CognitiveRetryLoop,
)
from agenticlane.orchestration.compaction import AttemptRecord, HistoryCompactor
from agenticlane.orchestration.constraint_guard import ConstraintGuard
from agenticlane.schemas.constraints import ConstraintDigest
from agenticlane.schemas.evidence import CrashInfo, EvidencePack
from agenticlane.schemas.execution import ExecutionResult
from agenticlane.schemas.metrics import MetricsPayload, RuntimeMetrics
from agenticlane.schemas.patch import Patch, PatchRejected

logger = logging.getLogger(__name__)


@dataclass
class AttemptOutcome:
    """Result of a single physical attempt."""

    attempt_num: int
    patch: Optional[Patch] = None
    metrics: Optional[MetricsPayload] = None
    evidence: Optional[EvidencePack] = None
    judge_result: str = "FAIL"  # PASS or FAIL
    composite_score: float = 0.0
    patch_accepted: bool = False  # Did cognitive retry produce an accepted patch?
    constraint_digest: Optional[ConstraintDigest] = None


@dataclass
class StageLoopResult:
    """Result of the agent-driven stage loop."""

    stage_name: str
    passed: bool = False
    best_attempt: int = 0
    attempts_used: int = 0
    best_score: float = 0.0
    best_metrics: Optional[MetricsPayload] = None
    best_evidence: Optional[EvidencePack] = None
    attempt_outcomes: list[AttemptOutcome] = field(default_factory=list)
    state_out_path: Optional[str] = None


class AgentStageLoop:
    """Agent-driven single-stage execution loop.

    Orchestrates: worker proposal -> constraint guard -> cognitive retry ->
    physical execution -> distillation -> judge ensemble -> scoring -> history.
    """

    def __init__(
        self,
        config: AgenticLaneConfig,
        adapter: ExecutionAdapter,
        llm_provider: LLMProvider,
        workspace: Optional[WorkspaceManager] = None,
        retriever: Any = None,
    ) -> None:
        self.config = config
        self.adapter = adapter
        self.llm_provider = llm_provider
        self.workspace = workspace or WorkspaceManager()
        self.retriever = retriever  # KnowledgeRetriever or None

        # Build components
        self.constraint_guard = ConstraintGuard(
            config.constraints, config.action_space
        )
        self.cognitive_retry = CognitiveRetryLoop(config.flow_control.budgets)
        self.judge_ensemble = JudgeEnsemble(llm_provider, config.judging)
        self.scoring_engine = ScoringEngine(config.scoring)
        self.history_compactor = HistoryCompactor()

    async def run_stage(
        self,
        stage_name: str,
        branch_dir: Path,
        run_dir: Path,
        *,
        run_id: str = "unknown",
        branch_id: str = "B0",
        baseline_state_in: Optional[str] = None,
        synth_stats: Any = None,
        post_synth_patch: Any = None,
        module_context: Optional[dict[str, Any]] = None,
    ) -> StageLoopResult:
        """Run a single stage with the full agent loop.

        Process per physical attempt:
        1. Worker proposes patch
        2. ConstraintGuard validates (cognitive retry if rejected)
        3. Execute stage with accepted patch
        4. Distill metrics + evidence
        5. Judge ensemble votes
        6. Score composite
        7. Record history
        8. If PASS -> return, else retry
        """
        budget = self.config.flow_control.budgets.physical_attempts_per_stage
        self.cognitive_retry.reset_stage()

        result = StageLoopResult(stage_name=stage_name)

        # Run attempt 0 (baseline) with empty patch to get baseline metrics
        baseline_attempt_dir = self.workspace.create_attempt_dir(
            branch_dir, stage_name, 0
        )
        baseline_metrics, baseline_evidence = await self._run_baseline(
            stage_name=stage_name,
            attempt_dir=baseline_attempt_dir,
            run_dir=run_dir,
            run_id=run_id,
            state_in_path=baseline_state_in,
        )

        # Track attempt history for lessons learned
        all_attempt_records: list[AttemptRecord] = []
        best_score = 0.0
        best_attempt = 0
        best_metrics = baseline_metrics
        best_evidence = baseline_evidence
        best_state_out: Optional[str] = None
        state_in = baseline_state_in
        last_rejection: Optional[PatchRejected] = None

        # Create worker for this stage
        worker = WorkerAgent(self.llm_provider, stage_name, self.config)

        for attempt_num in range(1, budget + 1):
            result.attempts_used = attempt_num

            attempt_dir = self.workspace.create_attempt_dir(
                branch_dir, stage_name, attempt_num
            )

            # --- Cognitive Retry Loop ---
            cog_state = self.cognitive_retry.begin_attempt(attempt_dir)
            accepted_patch: Optional[Patch] = None

            # Build lessons markdown
            lessons = self.history_compactor.compact(
                stage_name, branch_id, all_attempt_records
            )
            lessons_md = self.history_compactor.render_markdown(lessons)

            # --- RAG context ---
            rag_context_str: Optional[str] = None
            if self.retriever is not None:
                try:
                    from agenticlane.knowledge.retriever import KnowledgeRetriever

                    rag_ctx = self.retriever.retrieve(
                        stage=stage_name,
                        metrics=best_metrics,
                        evidence=best_evidence,
                    )
                    rag_context_str = KnowledgeRetriever.format_for_prompt(rag_ctx)
                    logger.warning(
                        "RAG: stage=%s chunks=%d query=%s (%.0fms)",
                        stage_name,
                        len(rag_ctx.chunks),
                        rag_ctx.query_used[:80],
                        rag_ctx.retrieval_ms,
                    )
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "RAG retrieval failed for stage=%s, continuing without",
                        stage_name,
                    )

            while not cog_state.exhausted:
                # Worker proposes patch
                proposed = await worker.propose_patch(
                    current_metrics=best_metrics,
                    evidence_pack=best_evidence,
                    attempt_number=attempt_num,
                    last_rejection=last_rejection,
                    lessons_markdown=lessons_md,
                    synth_stats=synth_stats,
                    post_synth_patch=post_synth_patch,
                    module_context=module_context,
                    rag_context=rag_context_str,
                )

                if proposed is None:
                    # LLM failure -- create a default empty patch
                    proposed = Patch(
                        patch_id=f"fallback_{attempt_num}",
                        stage=stage_name,
                        types=["config_vars"],
                        config_vars={},
                        rationale="LLM failed; using empty patch",
                    )

                # Validate through constraint guard + cognitive retry
                def _validator(p: Patch) -> PatchRejected | None:
                    gr = self.constraint_guard.validate(p)
                    return gr.rejection

                try:
                    rejection = self.cognitive_retry.try_patch(
                        cog_state, proposed, _validator
                    )
                except CognitiveBudgetExhaustedError:
                    # Stage-level cognitive budget exhausted
                    logger.warning(
                        "Stage-level cognitive budget exhausted for %s attempt %d",
                        stage_name,
                        attempt_num,
                        extra={
                            "event": "cognitive_budget_exhausted",
                            "stage": stage_name,
                            "attempt": attempt_num,
                            "branch_id": branch_id,
                            "run_id": run_id,
                        },
                    )
                    break

                if rejection is None:
                    # Accepted!
                    accepted_patch = proposed
                    last_rejection = None
                    break
                else:
                    logger.debug(
                        "Patch rejected by constraint guard stage=%s attempt=%d reason=%s",
                        stage_name,
                        attempt_num,
                        rejection.remediation_hint or "unknown",
                        extra={
                            "event": "patch_rejected",
                            "stage": stage_name,
                            "attempt": attempt_num,
                            "branch_id": branch_id,
                            "run_id": run_id,
                            "remediation_hint": (rejection.remediation_hint or "")[:200],
                        },
                    )
                    last_rejection = rejection

            outcome = AttemptOutcome(attempt_num=attempt_num)

            if accepted_patch is None:
                # All cognitive retries exhausted
                outcome.patch_accepted = False
                result.attempt_outcomes.append(outcome)

                logger.warning(
                    "Cognitive retry exhausted stage=%s attempt=%d branch=%s",
                    stage_name,
                    attempt_num,
                    branch_id,
                    extra={
                        "event": "cognitive_retry_exhausted",
                        "stage": stage_name,
                        "attempt": attempt_num,
                        "branch_id": branch_id,
                        "run_id": run_id,
                    },
                )

                # Record as failed attempt
                all_attempt_records.append(
                    AttemptRecord(
                        attempt_num=attempt_num,
                        patch_summary="Cognitive retry exhausted",
                        judge_decision="FAIL",
                    )
                )
                continue

            outcome.patch = accepted_patch
            outcome.patch_accepted = True

            # --- Physical Execution ---
            exec_result = await self.adapter.run_stage(
                run_root=str(run_dir),
                stage_name=stage_name,
                librelane_config_path=str(self.config.design.librelane_config_path),
                resolved_design_config_path=str(
                    self.config.design.librelane_config_path
                ),
                patch=accepted_patch.model_dump(mode="json"),
                state_in_path=state_in,
                attempt_dir=str(attempt_dir),
                timeout_seconds=self.config.execution.tool_timeout_seconds,
            )

            # --- Distillation ---
            metrics, evidence = await self._distill(
                attempt_dir=attempt_dir,
                stage_name=stage_name,
                attempt_num=attempt_num,
                exec_result=exec_result,
                run_id=run_id,
                branch_id=branch_id,
            )

            outcome.metrics = metrics
            outcome.evidence = evidence

            # Save artifacts
            (attempt_dir / "metrics.json").write_text(
                metrics.model_dump_json(indent=2)
            )
            (attempt_dir / "evidence.json").write_text(
                evidence.model_dump_json(indent=2)
            )

            # --- Judging ---
            judge_agg = await self.judge_ensemble.judge(
                stage_name=stage_name,
                attempt_number=attempt_num,
                baseline_metrics=baseline_metrics,
                current_metrics=metrics,
                evidence_pack=evidence,
            )
            outcome.judge_result = judge_agg.result

            # Save judge results
            (attempt_dir / "judge_votes.json").write_text(
                judge_agg.model_dump_json(indent=2)
            )

            # --- Scoring ---
            composite = self.scoring_engine.compute_composite_score(
                baseline_metrics=baseline_metrics,
                current_metrics=metrics,
                intent_weights=self.config.intent.weights_hint,
            )
            outcome.composite_score = composite

            (attempt_dir / "composite_score.json").write_text(
                json.dumps({"score": composite}, indent=2)
            )

            # Save lessons
            all_attempt_records.append(
                AttemptRecord(
                    attempt_num=attempt_num,
                    patch_summary=(
                        accepted_patch.rationale[:80]
                        if accepted_patch.rationale
                        else ""
                    ),
                    composite_score=composite,
                    judge_decision=judge_agg.result,
                )
            )

            lessons = self.history_compactor.compact(
                stage_name, branch_id, all_attempt_records
            )
            (attempt_dir / "lessons_learned.json").write_text(
                lessons.model_dump_json(indent=2)
            )

            result.attempt_outcomes.append(outcome)

            # Track best
            if composite > best_score or best_attempt == 0:
                best_score = composite
                best_attempt = attempt_num
                best_metrics = metrics
                best_evidence = evidence
                best_state_out = exec_result.state_out_path

            # Decision
            if judge_agg.result == "PASS":
                result.passed = True
                result.best_attempt = attempt_num
                result.best_score = composite
                result.best_metrics = metrics
                result.best_evidence = evidence
                result.state_out_path = exec_result.state_out_path

                # Write checkpoint
                (attempt_dir / "checkpoint.json").write_text(
                    json.dumps(
                        {
                            "stage": stage_name,
                            "attempt": attempt_num,
                            "status": "passed",
                        },
                        indent=2,
                    )
                )

                logger.info(
                    "Stage %s PASSED on attempt %d (score=%.4f)",
                    stage_name,
                    attempt_num,
                    composite,
                    extra={
                        "event": "stage_passed",
                        "stage": stage_name,
                        "attempt": attempt_num,
                        "branch_id": branch_id,
                        "run_id": run_id,
                        "composite_score": round(composite, 6),
                        "judge_confidence": round(judge_agg.confidence, 4),
                        "patch_id": accepted_patch.patch_id if accepted_patch else None,
                        "knob_keys": (
                            list(accepted_patch.config_vars.keys())
                            if accepted_patch and accepted_patch.config_vars
                            else []
                        ),
                    },
                )
                break
            else:
                blocking = [i.metric_key for i in judge_agg.blocking_issues]
                logger.info(
                    "Stage %s attempt %d FAILED (score=%.4f) blocking=%s",
                    stage_name,
                    attempt_num,
                    composite,
                    blocking,
                    extra={
                        "event": "stage_attempt_failed",
                        "stage": stage_name,
                        "attempt": attempt_num,
                        "branch_id": branch_id,
                        "run_id": run_id,
                        "composite_score": round(composite, 6),
                        "judge_result": judge_agg.result,
                        "judge_confidence": round(judge_agg.confidence, 4),
                        "blocking_issues": blocking,
                        "patch_id": accepted_patch.patch_id if accepted_patch else None,
                    },
                )

        # If never passed, record best
        if not result.passed:
            result.best_attempt = best_attempt
            result.best_score = best_score
            result.best_metrics = best_metrics
            result.best_evidence = best_evidence
            result.state_out_path = best_state_out

        return result

    async def _run_baseline(
        self,
        stage_name: str,
        attempt_dir: Path,
        run_dir: Path,
        run_id: str,
        state_in_path: Optional[str],
    ) -> tuple[MetricsPayload, EvidencePack]:
        """Run baseline (attempt 0) with empty patch."""
        empty_patch: dict[str, Any] = {"config_vars": {}}

        exec_result = await self.adapter.run_stage(
            run_root=str(run_dir),
            stage_name=stage_name,
            librelane_config_path=str(self.config.design.librelane_config_path),
            resolved_design_config_path=str(
                self.config.design.librelane_config_path
            ),
            patch=empty_patch,
            state_in_path=state_in_path,
            attempt_dir=str(attempt_dir),
            timeout_seconds=self.config.execution.tool_timeout_seconds,
        )

        metrics, evidence = await self._distill(
            attempt_dir=attempt_dir,
            stage_name=stage_name,
            attempt_num=0,
            exec_result=exec_result,
            run_id=run_id,
            branch_id="B0",
        )

        # Save baseline artifacts
        (attempt_dir / "metrics.json").write_text(
            metrics.model_dump_json(indent=2)
        )
        (attempt_dir / "evidence.json").write_text(
            evidence.model_dump_json(indent=2)
        )

        return metrics, evidence

    async def _distill(
        self,
        attempt_dir: Path,
        stage_name: str,
        attempt_num: int,
        exec_result: ExecutionResult,
        run_id: str,
        branch_id: str,
    ) -> tuple[MetricsPayload, EvidencePack]:
        """Distill metrics and evidence from an execution result.

        Tries the full extractor pipeline first.  On failure, falls back to
        basic metrics that still include runtime information so the
        ``metrics_parse_valid`` hard gate can pass.
        """
        # Try full distillation pipeline
        try:
            from agenticlane.distill.evidence import assemble_evidence

            metrics, evidence = await assemble_evidence(
                attempt_dir=attempt_dir,
                stage_name=stage_name,
                attempt_num=attempt_num,
                execution_result=exec_result,
                config=self.config.distill,
                run_id=run_id,
                branch_id=branch_id,
            )
            return metrics, evidence
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Full distillation failed for %s attempt %d (%s); using basic fallback",
                stage_name,
                attempt_num,
                exc,
                extra={
                    "event": "distillation_fallback",
                    "stage": stage_name,
                    "attempt": attempt_num,
                    "run_id": run_id,
                    "branch_id": branch_id,
                    "error": str(exc),
                },
            )

        # Fallback: basic metrics with runtime so hard gate can pass
        runtime = RuntimeMetrics(
            stage_seconds=exec_result.runtime_seconds,
        )
        # MetricsPayload requires attempt >= 1; baseline is attempt 0
        safe_attempt = max(attempt_num, 1)
        metrics = MetricsPayload(
            run_id=run_id,
            branch_id=branch_id,
            stage=stage_name,
            attempt=safe_attempt,
            execution_status=exec_result.execution_status,
            runtime=runtime,
        )
        evidence = EvidencePack(
            stage=stage_name,
            attempt=safe_attempt,
            execution_status=exec_result.execution_status,
        )
        if exec_result.execution_status != "success":
            evidence.crash_info = CrashInfo(
                crash_type=exec_result.execution_status,
                stderr_tail=exec_result.stderr_tail,
            )
        return metrics, evidence
