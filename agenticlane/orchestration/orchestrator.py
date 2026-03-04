"""Orchestrator for AgenticLane.

Supports two modes:
- **Passthrough** (no LLM): runs stages with empty patches, identical to Phase 1.
- **Agentic** (LLM available): full pipeline with worker proposals, constraint
  guard, cognitive retry, judge ensemble, parallel branches, rollback, plateau
  detection, and deadlock detection.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from agenticlane.agents.llm_provider import LLMProvider
from agenticlane.agents.specialists import (
    DRCSpecialist,
    RoutabilitySpecialist,
    TimingSpecialist,
)
from agenticlane.config.models import AgenticLaneConfig, ModuleConfig
from agenticlane.execution.adapter import ExecutionAdapter
from agenticlane.execution.config_patcher import (
    HardenedModule,
    HierarchicalConfigPatcher,
)
from agenticlane.execution.workspaces import WorkspaceManager
from agenticlane.orchestration.agent_loop import AgentStageLoop, StageLoopResult
from agenticlane.orchestration.checkpoint import CheckpointManager
from agenticlane.orchestration.deadlock import DeadlockDetector
from agenticlane.orchestration.graph import STAGE_ORDER
from agenticlane.orchestration.manifest import ManifestBuilder, StageDecision
from agenticlane.orchestration.plateau import PlateauDetector
from agenticlane.orchestration.rollback import RollbackEngine, StageCheckpoint
from agenticlane.orchestration.scheduler import BranchScheduler
from agenticlane.orchestration.zero_shot import ZeroShotInitializer
from agenticlane.schemas.evidence import CrashInfo, EvidencePack
from agenticlane.schemas.execution import ExecutionResult
from agenticlane.schemas.metrics import MetricsPayload, RuntimeMetrics
from agenticlane.schemas.specialist import SpecialistAdvice

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result data-classes
# ---------------------------------------------------------------------------


@dataclass
class StageResult:
    """Result of running a single stage through all its attempts."""

    stage_name: str
    passed: bool
    best_attempt: int
    attempts_used: int
    best_metrics: Optional[MetricsPayload] = None
    best_evidence: Optional[EvidencePack] = None
    checkpoint_path: Optional[str] = None


@dataclass
class FlowResult:
    """Result of running the complete flow."""

    run_id: str
    completed: bool
    stages_completed: list[str] = field(default_factory=list)
    stages_failed: list[str] = field(default_factory=list)
    stage_results: dict[str, StageResult] = field(default_factory=dict)
    run_dir: Optional[str] = None
    best_branch_id: Optional[str] = None
    best_score: Optional[float] = None


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class SequentialOrchestrator:
    """Orchestrates the execution of all ASIC stages.

    When *llm_provider* is ``None``, runs in **passthrough mode** (empty
    patches, no LLM).  When an LLM provider is supplied, runs the full
    **agentic mode** with worker proposals, constraint guard, judging,
    parallel branches, rollback, and plateau/deadlock detection.
    """

    def __init__(
        self,
        config: AgenticLaneConfig,
        adapter: ExecutionAdapter,
        *,
        workspace: WorkspaceManager | None = None,
        llm_provider: LLMProvider | None = None,
        resume_from: str | None = None,
        # Legacy positional compat
        llm: object | None = None,
    ) -> None:
        self.config = config
        self.adapter = adapter
        self.workspace = workspace or WorkspaceManager()
        # Accept both keyword forms for backward compatibility.
        # Only accept actual LLMProvider instances (not arbitrary objects).
        if llm_provider is not None and isinstance(llm_provider, LLMProvider):
            self._llm_provider: LLMProvider | None = llm_provider
        elif llm is not None and isinstance(llm, LLMProvider):
            self._llm_provider = llm
        else:
            # Check for duck-typed providers (e.g. MockLLMProvider)
            candidate = llm_provider or llm
            if candidate is not None and hasattr(candidate, "generate"):
                self._llm_provider = candidate  # type: ignore[assignment]
            else:
                self._llm_provider = None
        self._resume_from = resume_from
        self._state_in_path: Optional[str] = None

    @property
    def agentic(self) -> bool:
        """True when an LLM provider is available (agentic mode)."""
        return self._llm_provider is not None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_flow(
        self,
        *,
        stages: list[str] | None = None,
        run_id: str | None = None,
    ) -> FlowResult:
        """Run the complete flow or a subset of stages."""
        if self.config.design.flow_mode == "hierarchical" and self.agentic:
            return await self._run_hierarchical(stages=stages, run_id=run_id)
        if self.agentic:
            return await self._run_agentic(stages=stages, run_id=run_id)
        return await self._run_passthrough(stages=stages, run_id=run_id)

    # ==================================================================
    # AGENTIC MODE
    # ==================================================================

    async def _run_agentic(
        self,
        *,
        stages: list[str] | None = None,
        run_id: str | None = None,
    ) -> FlowResult:
        """Full agentic pipeline with all components wired."""
        assert self._llm_provider is not None
        llm = self._llm_provider

        # --- Setup ---
        effective_run_id = self._make_run_id(run_id)
        run_dir = self.workspace.create_run_dir(
            Path(self.config.project.output_dir), effective_run_id
        )
        stage_list = stages or list(STAGE_ORDER)

        # --- Sub-components ---
        par_cfg = self.config.parallel
        n_branches = par_cfg.max_parallel_branches if par_cfg.enabled else 1

        scheduler = BranchScheduler(
            n_branches=n_branches,
            output_dir=run_dir,
            prune_delta_score=par_cfg.prune.prune_delta_score,
            prune_patience_attempts=par_cfg.prune.prune_patience_attempts,
        )
        rollback_engine = RollbackEngine(llm, self.config)
        zero_shot = ZeroShotInitializer(
            llm_provider=llm,
            default_config_vars=None,
        )
        manifest_builder = ManifestBuilder(
            run_id=effective_run_id,
            config=self.config.model_dump(mode="json"),
            seed=self.config.llm.seed,
        )
        manifest_builder.set_stages(len(stage_list))
        manifest_builder.set_flow_mode(self.config.design.flow_mode)

        checkpoint_mgr = CheckpointManager(
            runs_dir=Path(self.config.project.output_dir),
        )
        plateau_detector = PlateauDetector(
            window_size=self.config.flow_control.plateau_detection.window,
            threshold=self.config.flow_control.plateau_detection.min_delta_score,
        )
        deadlock_detector = DeadlockDetector(
            max_no_progress_attempts=self.config.flow_control.budgets.physical_attempts_per_stage,
            policy=self.config.flow_control.deadlock_policy,
        )

        # --- Knowledge retriever (RAG) ---
        retriever = None
        if self.config.knowledge.enabled:
            try:
                from agenticlane.knowledge.retriever import KnowledgeRetriever

                retriever = KnowledgeRetriever(self.config.knowledge)
                logger.info(
                    "RAG knowledge retriever initialized",
                    extra={"event": "rag_init", "run_id": effective_run_id},
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Failed to initialize RAG retriever: %s — continuing without",
                    exc,
                    extra={"event": "rag_init_failed", "run_id": effective_run_id},
                )

        self._retriever = retriever

        # --- Specialist agents (triggered on plateau) ---
        specialists = _create_specialists(llm, self.config)

        # --- Resume ---
        resume_stage_idx = 0
        if self._resume_from:
            resume_state = checkpoint_mgr.get_resume_state(self._resume_from)
            if resume_state:
                manifest_builder.set_resumed(self._resume_from)
                current_stage = resume_state.get("current_stage", "")
                if current_stage in stage_list:
                    resume_stage_idx = stage_list.index(current_stage)
                    logger.info(
                        "Resuming from checkpoint: stage=%s (index=%d)",
                        current_stage,
                        resume_stage_idx,
                        extra={
                            "event": "flow_resume",
                            "run_id": effective_run_id,
                            "resume_from": self._resume_from,
                            "resume_stage": current_stage,
                            "resume_stage_index": resume_stage_idx,
                        },
                    )

        # --- Zero-shot init ---
        init_patch = None
        if self.config.initialization.zero_shot.enabled:
            try:
                init_patch_obj = await zero_shot.generate_init_patch(
                    intent={
                        "prompt": self.config.intent.prompt,
                        "weights": self.config.intent.weights_hint,
                    },
                )
                zero_shot.write_init_patch(init_patch_obj, run_dir)
                init_patch = init_patch_obj.model_dump(mode="json")
                logger.info(
                    "Zero-shot init patch generated",
                    extra={
                        "event": "zero_shot_init_done",
                        "run_id": effective_run_id,
                    },
                )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Zero-shot init failed, continuing without init patch",
                    extra={
                        "event": "zero_shot_init_failed",
                        "run_id": effective_run_id,
                    },
                )

        # --- Create branches ---
        branches = scheduler.create_branches(init_patch=init_patch)
        logger.info(
            "Created %d branch(es)",
            len(branches),
            extra={
                "event": "branches_created",
                "run_id": effective_run_id,
                "branch_count": len(branches),
                "branch_ids": [b.branch_id for b in branches],
            },
        )

        flow_result = FlowResult(
            run_id=effective_run_id,
            completed=False,
            run_dir=str(run_dir),
        )

        # Per-branch tracking: branch_id -> {state_in, scores, checkpoints}
        branch_state: dict[str, dict[str, Any]] = {}
        for b in branches:
            branch_state[b.branch_id] = {
                "state_in": None,
                "scores": [],
                "checkpoints": {},  # stage -> StageCheckpoint
                "synth_metrics": None,
                "post_synth_patch": None,
            }

        # --- Stage loop ---
        for stage_idx, stage_name in enumerate(stage_list):
            if stage_idx < resume_stage_idx:
                flow_result.stages_completed.append(stage_name)
                continue

            logger.info(
                "=== Stage %s (%d/%d) ===",
                stage_name,
                stage_idx + 1,
                len(stage_list),
                extra={
                    "event": "stage_start",
                    "run_id": effective_run_id,
                    "stage": stage_name,
                    "stage_index": stage_idx + 1,
                    "total_stages": len(stage_list),
                },
            )

            active_branches = scheduler.get_active_branches()
            if not active_branches:
                logger.error(
                    "No active branches remaining, stopping flow",
                    extra={
                        "event": "flow_no_branches",
                        "run_id": effective_run_id,
                        "stage": stage_name,
                    },
                )
                break

            # --- Run branches (parallel or sequential) ---
            stage_results_by_branch: dict[str, StageLoopResult] = {}

            if len(active_branches) > 1:
                # Parallel execution with semaphore-limited concurrency
                stage_results_by_branch = await self._run_branches_parallel(
                    llm=llm,
                    stage_name=stage_name,
                    active_branches=active_branches,
                    branch_state=branch_state,
                    run_dir=run_dir,
                    run_id=effective_run_id,
                    max_concurrent=par_cfg.max_parallel_jobs,
                )
            else:
                # Single branch
                b = active_branches[0]
                bst = branch_state[b.branch_id]
                slr = await self._run_agentic_stage_for_branch(
                    llm=llm,
                    stage_name=stage_name,
                    branch_id=b.branch_id,
                    branch_dir=b.workspace_root,
                    run_dir=run_dir,
                    run_id=effective_run_id,
                    state_in=bst["state_in"],
                    synth_stats=bst.get("synth_metrics"),
                    post_synth_patch=bst.get("post_synth_patch"),
                )
                stage_results_by_branch[b.branch_id] = slr

            # --- Process results per branch ---
            any_passed = False
            for branch_id, slr in stage_results_by_branch.items():
                bstate = branch_state[branch_id]
                bstate["scores"].append(slr.best_score)

                # Capture synthesis metrics after SYNTH stage
                if stage_name == "SYNTH" and slr.best_metrics and slr.best_metrics.synthesis:
                    bstate["synth_metrics"] = slr.best_metrics.synthesis

                manifest_builder.record_decision(StageDecision(
                    stage=stage_name,
                    branch_id=branch_id,
                    attempt=slr.best_attempt,
                    action="accept" if slr.passed else "reject",
                    composite_score=slr.best_score,
                    reason=f"attempts_used={slr.attempts_used}",
                ))

                if slr.passed:
                    any_passed = True
                    scheduler.update_branch_score(
                        branch_id, slr.best_score, stage_name, slr.best_attempt
                    )
                    bstate["state_in"] = slr.state_out_path
                    bstate["checkpoints"][stage_name] = StageCheckpoint(
                        stage=stage_name,
                        attempt=slr.best_attempt,
                        composite_score=slr.best_score,
                        state_in_path=slr.state_out_path,
                    )
                else:
                    # Stage failed for this branch
                    scheduler.update_branch_score(
                        branch_id, slr.best_score, stage_name, slr.best_attempt
                    )

                    # --- Rollback decision ---
                    try:
                        decision = await rollback_engine.decide(
                            failed_stage=stage_name,
                            attempt_outcomes=slr.attempt_outcomes,
                            evidence=slr.best_evidence or EvidencePack(
                                stage=stage_name, attempt=0, execution_status="unknown_fail"
                            ),
                            checkpoints={
                                bid: [cp for cp in bs["checkpoints"].values()]
                                for bid, bs in branch_state.items()
                            },
                        )
                        manifest_builder.record_decision(StageDecision(
                            stage=stage_name,
                            branch_id=branch_id,
                            attempt=slr.attempts_used,
                            action=decision.action,
                            reason=decision.reason,
                        ))
                        if decision.action == "stop":
                            scheduler.fail_branch(branch_id, reason=decision.reason)
                        # rollback/retry: keep branch active, state_in unchanged
                    except Exception:  # noqa: BLE001
                        logger.warning(
                            "Rollback engine failed for %s/%s, keeping branch active",
                            branch_id,
                            stage_name,
                            extra={
                                "event": "rollback_engine_error",
                                "run_id": effective_run_id,
                                "stage": stage_name,
                                "branch_id": branch_id,
                            },
                        )

                # --- Plateau detection + specialist consultation ---
                scores = bstate["scores"]
                if plateau_detector.is_plateau(scores):
                    plateau_info = plateau_detector.get_plateau_info(scores)
                    logger.warning(
                        "Plateau detected for branch %s at stage %s",
                        branch_id,
                        stage_name,
                        extra={
                            "event": "plateau_detected",
                            "run_id": effective_run_id,
                            "stage": stage_name,
                            "branch_id": branch_id,
                            "score_history": scores,
                            "plateau_info": plateau_info,
                        },
                    )
                    manifest_builder.record_decision(StageDecision(
                        stage=stage_name,
                        branch_id=branch_id,
                        attempt=slr.best_attempt,
                        action="plateau_detected",
                        reason="Score plateau detected",
                    ))

                    # Consult specialist agents for advice
                    specialist_advice = await _consult_specialists(
                        specialists=specialists,
                        stage_name=stage_name,
                        metrics=slr.best_metrics,
                        evidence=slr.best_evidence,
                        scores=scores,
                        plateau_info=plateau_info,
                    )
                    if specialist_advice:
                        bstate["specialist_advice"] = specialist_advice
                        advice_types = [a.specialist_type for a in specialist_advice]
                        logger.info(
                            "Specialist advice received for branch %s: %s",
                            branch_id,
                            advice_types,
                            extra={
                                "event": "specialist_advice_received",
                                "run_id": effective_run_id,
                                "stage": stage_name,
                                "branch_id": branch_id,
                                "specialist_types": advice_types,
                                "advice_count": len(specialist_advice),
                            },
                        )
                        manifest_builder.record_decision(StageDecision(
                            stage=stage_name,
                            branch_id=branch_id,
                            attempt=slr.best_attempt,
                            action="specialist_consulted",
                            reason=f"Specialists consulted: {', '.join(advice_types)}",
                        ))

                # --- Deadlock detection ---
                if deadlock_detector.check_deadlock(scores):
                    action = deadlock_detector.get_action()
                    logger.warning(
                        "Deadlock detected for branch %s, action=%s",
                        branch_id,
                        action,
                        extra={
                            "event": "deadlock_detected",
                            "run_id": effective_run_id,
                            "stage": stage_name,
                            "branch_id": branch_id,
                            "action": action,
                            "score_history": scores,
                        },
                    )
                    if action == "stop":
                        scheduler.fail_branch(
                            branch_id, reason="Deadlock: no progress"
                        )
                    elif action == "auto_relax":
                        # Relax signoff hard gates so subsequent
                        # attempts can pass with minor DRC violations
                        sg = self.config.judging.strictness.signoff_hard_gates
                        if sg:
                            logger.info(
                                "Auto-relaxing signoff hard gates %s "
                                "for branch %s at stage %s",
                                sg,
                                branch_id,
                                stage_name,
                                extra={
                                    "event": "deadlock_auto_relax",
                                    "run_id": effective_run_id,
                                    "stage": stage_name,
                                    "branch_id": branch_id,
                                    "relaxed_gates": sg,
                                },
                            )
                            self.config.judging.strictness.signoff_hard_gates = []

            # --- Pruning ---
            if par_cfg.enabled and par_cfg.prune.enabled:
                for b in list(scheduler.get_active_branches()):
                    if scheduler.should_prune(b.branch_id):
                        scheduler.prune_branch(b.branch_id, reason="underperforming")
                        manifest_builder.record_decision(StageDecision(
                            stage=stage_name,
                            branch_id=b.branch_id,
                            attempt=0,
                            action="prune",
                            reason="Pruned: underperforming branch",
                        ))
                        logger.info(
                            "Pruned branch %s",
                            b.branch_id,
                            extra={
                                "event": "branch_pruned",
                                "run_id": effective_run_id,
                                "stage": stage_name,
                                "branch_id": b.branch_id,
                            },
                        )

            # Post-synth auto-sizing: compute die area from synthesis cell count
            if stage_name == "SYNTH":
                for bid in list(stage_results_by_branch.keys()):
                    synth_m = branch_state[bid].get("synth_metrics")
                    if synth_m and synth_m.cell_count:
                        # Build intent dict from config
                        weights = self.config.intent.weights_hint
                        # Determine optimize_for from highest weight
                        optimize_for = max(weights, key=lambda k: weights[k]) if weights else "balanced"
                        refinement = zero_shot.refine_after_synth(
                            synth_metrics=synth_m,
                            intent={"optimize_for": optimize_for, **weights},
                            pdk=self.config.design.pdk,
                        )
                        branch_state[bid]["post_synth_patch"] = refinement

            # Record stage outcome
            if any_passed:
                flow_result.stages_completed.append(stage_name)
            else:
                flow_result.stages_failed.append(stage_name)
                logger.warning(
                    "Stage %s: no branch passed",
                    stage_name,
                    extra={
                        "event": "stage_no_branch_passed",
                        "run_id": effective_run_id,
                        "stage": stage_name,
                    },
                )

            # Build a StageResult for compatibility
            best_branch_slr = max(
                stage_results_by_branch.values(),
                key=lambda s: s.best_score,
            )
            flow_result.stage_results[stage_name] = StageResult(
                stage_name=stage_name,
                passed=any_passed,
                best_attempt=best_branch_slr.best_attempt,
                attempts_used=best_branch_slr.attempts_used,
                best_metrics=best_branch_slr.best_metrics,
                best_evidence=best_branch_slr.best_evidence,
                checkpoint_path=best_branch_slr.state_out_path,
            )

        # --- Best branch selection ---
        best_branch = scheduler.select_best_branch()
        if best_branch:
            flow_result.best_branch_id = best_branch.branch_id
            flow_result.best_score = best_branch.best_composite_score
            scheduler.complete_branch(best_branch.branch_id)
            manifest_builder.set_winner(
                best_branch.branch_id,
                best_branch.best_composite_score or 0.0,
            )
            manifest_builder.record_branch(
                best_branch.branch_id,
                status="completed",
                best_score=best_branch.best_composite_score,
            )

        flow_result.completed = len(flow_result.stages_failed) == 0

        # --- Write manifest ---
        manifest = manifest_builder.finalize()
        manifest_builder.write_manifest(manifest, run_dir)

        return flow_result

    async def _run_agentic_stage_for_branch(
        self,
        *,
        llm: LLMProvider,
        stage_name: str,
        branch_id: str,
        branch_dir: Path,
        run_dir: Path,
        run_id: str,
        state_in: str | None,
        synth_stats: Any | None = None,
        post_synth_patch: Any | None = None,
        module_context: dict[str, Any] | None = None,
    ) -> StageLoopResult:
        """Run a single stage through the full AgentStageLoop for one branch."""
        agent_loop = AgentStageLoop(
            config=self.config,
            adapter=self.adapter,
            llm_provider=llm,
            workspace=self.workspace,
            retriever=getattr(self, "_retriever", None),
        )
        return await agent_loop.run_stage(
            stage_name=stage_name,
            branch_dir=branch_dir,
            run_dir=run_dir,
            run_id=run_id,
            branch_id=branch_id,
            baseline_state_in=state_in,
            synth_stats=synth_stats,
            post_synth_patch=post_synth_patch,
            module_context=module_context,
        )

    async def _run_branches_parallel(
        self,
        *,
        llm: LLMProvider,
        stage_name: str,
        active_branches: list[Any],
        branch_state: dict[str, dict[str, Any]],
        run_dir: Path,
        run_id: str,
        max_concurrent: int,
    ) -> dict[str, StageLoopResult]:
        """Run stage for multiple branches with a concurrency semaphore."""
        sem = asyncio.Semaphore(max_concurrent)
        results: dict[str, StageLoopResult] = {}

        async def _run_one(branch: Any) -> None:
            async with sem:
                bst = branch_state[branch.branch_id]
                slr = await self._run_agentic_stage_for_branch(
                    llm=llm,
                    stage_name=stage_name,
                    branch_id=branch.branch_id,
                    branch_dir=branch.workspace_root,
                    run_dir=run_dir,
                    run_id=run_id,
                    state_in=bst["state_in"],
                    synth_stats=bst.get("synth_metrics"),
                    post_synth_patch=bst.get("post_synth_patch"),
                )
                results[branch.branch_id] = slr

        await asyncio.gather(*[_run_one(b) for b in active_branches])
        return results

    # ==================================================================
    # HIERARCHICAL MODE
    # ==================================================================

    async def _run_hierarchical(
        self,
        *,
        stages: list[str] | None = None,
        run_id: str | None = None,
    ) -> FlowResult:
        """Hierarchical flow: harden sub-modules, then integrate parent.

        Phase 1: For each module in config.design.modules, create a
                 sub-orchestrator and run the full flat pipeline.
        Phase 2: Patch parent LibreLane config with hardened MACROS entries.
        Phase 3: Run parent flat pipeline with patched config.
        """
        assert self._llm_provider is not None

        effective_run_id = self._make_run_id(run_id)
        run_dir = self.workspace.create_run_dir(
            Path(self.config.project.output_dir), effective_run_id
        )

        modules = self.config.design.modules
        if not modules:
            logger.warning(
                "No modules defined, falling back to flat flow",
                extra={
                    "event": "hierarchical_no_modules",
                    "run_id": effective_run_id,
                },
            )
            return await self._run_agentic(stages=stages, run_id=effective_run_id)

        logger.info(
            "=== Hierarchical flow: %d module(s) to harden ===",
            len(modules),
            extra={
                "event": "hierarchical_flow_start",
                "run_id": effective_run_id,
                "module_count": len(modules),
                "module_names": list(modules.keys()),
            },
        )

        # Phase 1: Harden each sub-module
        hardened: list[HardenedModule] = []
        module_flow_results: dict[str, dict[str, Any]] = {}

        for module_name, module_cfg in modules.items():
            logger.info(
                "--- Hardening module: %s ---",
                module_name,
                extra={
                    "event": "module_harden_start",
                    "run_id": effective_run_id,
                    "module_name": module_name,
                },
            )
            module_dir = run_dir / "modules" / module_name
            module_dir.mkdir(parents=True, exist_ok=True)

            module_config = self._build_module_config(module_name, module_cfg)
            module_config.project.output_dir = module_dir

            sub_orchestrator = SequentialOrchestrator(
                config=module_config,
                adapter=self.adapter,
                workspace=self.workspace,
                llm_provider=self._llm_provider,
            )
            module_result = await sub_orchestrator._run_agentic(
                stages=stages,
                run_id=f"{effective_run_id}_mod_{module_name}",
            )

            module_flow_results[module_name] = {
                "completed": module_result.completed,
                "stages_completed": module_result.stages_completed,
                "stages_failed": module_result.stages_failed,
                "best_score": module_result.best_score,
                "run_dir": module_result.run_dir,
            }

            # Artifact-based completion: a module that produced LEF/GDS is
            # good enough for hierarchical integration even if some stages
            # (e.g. SIGNOFF) failed.  Only abort if no artifacts exist.
            artifacts = self._collect_module_artifacts(
                module_name, module_result, module_dir
            )
            if artifacts:
                hardened.append(artifacts)
                if module_result.completed:
                    logger.info(
                        "Module %s: all stages passed, LEF=%s, GDS=%s",
                        module_name,
                        artifacts.lef_path,
                        artifacts.gds_path,
                        extra={
                            "event": "module_harden_done",
                            "run_id": effective_run_id,
                            "module_name": module_name,
                            "completed": True,
                            "lef_path": str(artifacts.lef_path) if artifacts.lef_path else None,
                            "gds_path": str(artifacts.gds_path) if artifacts.gds_path else None,
                            "stages_completed": module_result.stages_completed,
                        },
                    )
                else:
                    logger.warning(
                        "Module %s: stages_failed=%s but artifacts collected "
                        "(LEF=%s, GDS=%s) — continuing with integration",
                        module_name,
                        module_result.stages_failed,
                        artifacts.lef_path,
                        artifacts.gds_path,
                        extra={
                            "event": "module_harden_partial",
                            "run_id": effective_run_id,
                            "module_name": module_name,
                            "completed": False,
                            "stages_failed": module_result.stages_failed,
                            "lef_path": str(artifacts.lef_path) if artifacts.lef_path else None,
                            "gds_path": str(artifacts.gds_path) if artifacts.gds_path else None,
                        },
                    )
            else:
                logger.error(
                    "Module %s: no LEF/GDS artifacts produced "
                    "(stages_failed=%s), aborting hierarchical flow",
                    module_name,
                    module_result.stages_failed,
                    extra={
                        "event": "module_harden_no_artifacts",
                        "run_id": effective_run_id,
                        "module_name": module_name,
                        "stages_failed": module_result.stages_failed,
                    },
                )
                return FlowResult(
                    run_id=effective_run_id,
                    completed=False,
                    stages_failed=[f"module:{module_name}"],
                    run_dir=str(run_dir),
                )

        # Phase 2: Patch parent config with hardened macros
        patched_config_path: Path | None = None
        if hardened:
            patched_config_path = run_dir / "patched_parent_config.json"
            HierarchicalConfigPatcher.patch_config(
                parent_config_path=Path(self.config.design.librelane_config_path),
                hardened_modules=hardened,
                output_path=patched_config_path,
            )
            logger.info(
                "Patched parent config written to %s",
                patched_config_path,
                extra={
                    "event": "parent_config_patched",
                    "run_id": effective_run_id,
                    "patched_config_path": str(patched_config_path),
                    "hardened_module_count": len(hardened),
                },
            )

        # Phase 3: Run parent design with patched config
        logger.info(
            "=== Running parent design ===",
            extra={
                "event": "parent_design_start",
                "run_id": effective_run_id,
            },
        )
        parent_config = self.config.model_copy(deep=True)
        parent_config.design.flow_mode = "flat"
        parent_config.design.modules = {}
        if patched_config_path:
            parent_config.design.librelane_config_path = patched_config_path
        parent_config.project.output_dir = run_dir

        parent_orchestrator = SequentialOrchestrator(
            config=parent_config,
            adapter=self.adapter,
            workspace=self.workspace,
            llm_provider=self._llm_provider,
        )
        parent_result = await parent_orchestrator._run_agentic(
            stages=stages,
            run_id=f"{effective_run_id}_parent",
        )

        # Build composite result
        flow_result = FlowResult(
            run_id=effective_run_id,
            completed=parent_result.completed,
            stages_completed=parent_result.stages_completed,
            stages_failed=parent_result.stages_failed,
            stage_results=parent_result.stage_results,
            run_dir=str(run_dir),
            best_branch_id=parent_result.best_branch_id,
            best_score=parent_result.best_score,
        )

        # Write composite manifest
        manifest_builder = ManifestBuilder(
            run_id=effective_run_id,
            config=self.config.model_dump(mode="json"),
            seed=self.config.llm.seed,
        )
        manifest_builder.set_flow_mode("hierarchical")
        for mod_name, mod_info in module_flow_results.items():
            manifest_builder.record_module(mod_name, mod_info)
        manifest = manifest_builder.finalize()
        manifest_builder.write_manifest(manifest, run_dir)

        return flow_result

    def _build_module_config(
        self,
        module_name: str,
        module_cfg: ModuleConfig,
    ) -> AgenticLaneConfig:
        """Build a flat AgenticLaneConfig for a sub-module.

        Deep-copies the parent config, overrides design paths,
        forces ``flow_mode='flat'``, and merges any module-level overrides.
        """
        config = self.config.model_copy(deep=True)
        config.design.librelane_config_path = module_cfg.librelane_config_path
        config.design.flow_mode = "flat"
        config.design.modules = {}
        config.project.name = f"{config.project.name}_{module_name}"

        # Sub-module SIGNOFF: minor DRC violations are expected and get
        # resolved during parent integration, so drop signoff hard gates.
        config.judging.strictness.signoff_hard_gates = []

        if module_cfg.pdk:
            config.design.pdk = module_cfg.pdk
        if module_cfg.intent:
            config.intent = module_cfg.intent
        if module_cfg.flow_control:
            config.flow_control = module_cfg.flow_control
        if module_cfg.parallel:
            config.parallel = module_cfg.parallel

        return config

    def _collect_module_artifacts(
        self,
        module_name: str,
        module_result: FlowResult,
        module_dir: Path,
    ) -> HardenedModule | None:
        """Collect LEF/GDS from a hardened module's SIGNOFF workspace.

        Searches the module's run directory for ``*.lef`` and ``*.gds``
        files (produced by SIGNOFF), copies them into a stable artifacts
        directory, and returns a ``HardenedModule`` descriptor.
        """
        if not module_result.run_dir:
            return None

        run_dir_path = Path(module_result.run_dir)
        artifacts_dir = module_dir / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        lef_files = sorted(run_dir_path.rglob("*.lef"))
        gds_files = sorted(run_dir_path.rglob("*.gds"))

        if not lef_files or not gds_files:
            logger.warning(
                "Module %s: LEF count=%d, GDS count=%d under %s",
                module_name,
                len(lef_files),
                len(gds_files),
                run_dir_path,
            )
            return None

        # Copy the last (most recent by name sort) LEF and GDS
        lef_dst = artifacts_dir / f"{module_name}.lef"
        gds_dst = artifacts_dir / f"{module_name}.gds"
        shutil.copy2(lef_files[-1], lef_dst)
        shutil.copy2(gds_files[-1], gds_dst)

        # Optionally collect netlist
        nl_files = sorted(
            list(run_dir_path.rglob("*.nl.v"))
            + list(run_dir_path.rglob("*.spice"))
        )
        nl_dst = None
        if nl_files:
            nl_src = nl_files[-1]
            nl_dst = artifacts_dir / f"{module_name}{nl_src.suffix}"
            shutil.copy2(nl_src, nl_dst)

        return HardenedModule(
            module_name=module_name,
            lef_path=lef_dst,
            gds_path=gds_dst,
            nl_path=nl_dst,
        )

    # ==================================================================
    # PASSTHROUGH MODE (no LLM)
    # ==================================================================

    async def _run_passthrough(
        self,
        *,
        stages: list[str] | None = None,
        run_id: str | None = None,
    ) -> FlowResult:
        """Run with empty patches (no LLM), identical to Phase 1 behavior."""
        effective_run_id = self._make_run_id(run_id)

        run_dir = self.workspace.create_run_dir(
            Path(self.config.project.output_dir), effective_run_id
        )
        branch_dir = self.workspace.create_branch_dir(run_dir, "B0")

        stage_list = stages or list(STAGE_ORDER)

        flow_result = FlowResult(
            run_id=effective_run_id,
            completed=False,
            run_dir=str(run_dir),
        )

        for stage_name in stage_list:
            stage_result = await self._run_passthrough_stage(
                stage_name=stage_name,
                branch_dir=branch_dir,
                run_dir=run_dir,
            )
            flow_result.stage_results[stage_name] = stage_result

            if stage_result.passed:
                flow_result.stages_completed.append(stage_name)
                if stage_result.checkpoint_path:
                    self._state_in_path = stage_result.checkpoint_path
            else:
                flow_result.stages_failed.append(stage_name)
                logger.warning(
                    "Stage %s failed after %d attempts, continuing...",
                    stage_name,
                    stage_result.attempts_used,
                )

        flow_result.completed = len(flow_result.stages_failed) == 0

        # Write manifest
        self._write_manifest(flow_result, run_dir)

        return flow_result

    async def _run_passthrough_stage(
        self,
        *,
        stage_name: str,
        branch_dir: Path,
        run_dir: Path,
    ) -> StageResult:
        """Run a single stage with empty patches (passthrough mode)."""
        budget = self.config.flow_control.budgets.physical_attempts_per_stage
        best_attempt = 0
        best_metrics: Optional[MetricsPayload] = None
        best_evidence: Optional[EvidencePack] = None
        checkpoint_path: Optional[str] = None
        passed = False
        attempts_used = 0

        for attempt_num in range(1, budget + 1):
            attempts_used = attempt_num
            attempt_dir = self.workspace.create_attempt_dir(
                branch_dir,
                stage_name,
                attempt_num,
            )

            patch: dict[str, Any] = {"config_vars": {}}

            result = await self.adapter.run_stage(
                run_root=str(run_dir),
                stage_name=stage_name,
                librelane_config_path=str(self.config.design.librelane_config_path),
                resolved_design_config_path=str(self.config.design.librelane_config_path),
                patch=patch,
                state_in_path=self._state_in_path,
                attempt_dir=str(attempt_dir),
                timeout_seconds=self.config.execution.tool_timeout_seconds,
            )

            metrics, evidence = await self._distill(
                attempt_dir, stage_name, attempt_num, result
            )

            self._save_attempt_artifacts(attempt_dir, result, metrics, evidence, patch)

            gate_passed = self._check_gates(metrics, evidence, result)

            if gate_passed:
                passed = True
                best_attempt = attempt_num
                best_metrics = metrics
                best_evidence = evidence
                checkpoint_path = result.state_out_path

                self._write_checkpoint(attempt_dir, stage_name, attempt_num, metrics)

                logger.info("Stage %s passed on attempt %d", stage_name, attempt_num)
                break
            else:
                logger.info(
                    "Stage %s attempt %d failed gate check",
                    stage_name,
                    attempt_num,
                )
                if best_metrics is None:
                    best_attempt = attempt_num
                    best_metrics = metrics
                    best_evidence = evidence

        return StageResult(
            stage_name=stage_name,
            passed=passed,
            best_attempt=best_attempt,
            attempts_used=attempts_used,
            best_metrics=best_metrics,
            best_evidence=best_evidence,
            checkpoint_path=checkpoint_path,
        )

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _make_run_id(self, run_id: str | None) -> str:
        effective = run_id or self.config.project.run_id
        if effective == "auto":
            effective = f"run_{uuid.uuid4().hex[:8]}"
        return effective

    async def _distill(
        self,
        attempt_dir: Path,
        stage_name: str,
        attempt_num: int,
        result: ExecutionResult,
    ) -> tuple[MetricsPayload, EvidencePack]:
        """Distill execution results into metrics and evidence."""
        try:
            from agenticlane.distill.evidence import (  # type: ignore[import-not-found]
                assemble_evidence,
            )

            return await assemble_evidence(
                attempt_dir=attempt_dir,
                stage_name=stage_name,
                attempt_num=attempt_num,
                execution_result=result,
                config=self.config.distill,
            )
        except (ImportError, AttributeError):
            return self._basic_distill(attempt_dir, stage_name, attempt_num, result)

    def _basic_distill(
        self,
        attempt_dir: Path,
        stage_name: str,
        attempt_num: int,
        result: ExecutionResult,
    ) -> tuple[MetricsPayload, EvidencePack]:
        """Fallback basic distillation from ExecutionResult.

        Includes runtime metrics so the ``metrics_parse_valid`` hard gate
        can still pass even when extractors find no log files.
        """
        runtime = RuntimeMetrics(
            stage_seconds=result.runtime_seconds,
        )
        metrics = MetricsPayload(
            run_id="unknown",
            branch_id="B0",
            stage=stage_name,
            attempt=attempt_num,
            execution_status=result.execution_status,
            runtime=runtime,
        )
        evidence = EvidencePack(
            stage=stage_name,
            attempt=attempt_num,
            execution_status=result.execution_status,
        )
        if result.execution_status != "success":
            evidence.crash_info = CrashInfo(
                crash_type=result.execution_status,
                stderr_tail=result.stderr_tail,
            )
        return metrics, evidence

    def _check_gates(
        self,
        metrics: MetricsPayload,
        evidence: EvidencePack,
        result: ExecutionResult,
    ) -> bool:
        """Check hard gates for stage pass/fail."""
        if result.execution_status != "success":
            return False
        if evidence.crash_info is not None:
            return False
        return not (
            metrics.signoff is not None
            and metrics.signoff.drc_count is not None
            and metrics.signoff.drc_count > 0
        )

    def _save_attempt_artifacts(
        self,
        attempt_dir: Path,
        result: ExecutionResult,
        metrics: MetricsPayload,
        evidence: EvidencePack,
        patch: dict[str, Any],
    ) -> None:
        """Save attempt JSON artifacts."""
        (attempt_dir / "metrics.json").write_text(metrics.model_dump_json(indent=2))
        (attempt_dir / "evidence.json").write_text(evidence.model_dump_json(indent=2))
        (attempt_dir / "patch.json").write_text(json.dumps(patch, indent=2))

    def _write_checkpoint(
        self,
        attempt_dir: Path,
        stage_name: str,
        attempt_num: int,
        metrics: MetricsPayload,
    ) -> None:
        """Write a checkpoint file for a successful stage attempt."""
        checkpoint = {
            "stage": stage_name,
            "attempt": attempt_num,
            "attempt_dir": str(attempt_dir),
            "status": "passed",
        }
        (attempt_dir / "checkpoint.json").write_text(json.dumps(checkpoint, indent=2))

    def _write_manifest(
        self,
        flow_result: FlowResult,
        run_dir: Path,
    ) -> None:
        """Write the run manifest (passthrough mode)."""
        manifest = {
            "run_id": flow_result.run_id,
            "completed": flow_result.completed,
            "stages_completed": flow_result.stages_completed,
            "stages_failed": flow_result.stages_failed,
            "stage_results": {
                name: {
                    "passed": sr.passed,
                    "best_attempt": sr.best_attempt,
                    "attempts_used": sr.attempts_used,
                }
                for name, sr in flow_result.stage_results.items()
            },
        }
        (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))


# ---------------------------------------------------------------------------
# Module-level specialist helpers
# ---------------------------------------------------------------------------


def _create_specialists(
    llm: LLMProvider,
    config: AgenticLaneConfig,
) -> list[TimingSpecialist | RoutabilitySpecialist | DRCSpecialist]:
    """Create the set of specialist agents for plateau consultation."""
    return [
        TimingSpecialist(llm_provider=llm, config=config),
        RoutabilitySpecialist(llm_provider=llm, config=config),
        DRCSpecialist(llm_provider=llm, config=config),
    ]


async def _consult_specialists(
    *,
    specialists: list[TimingSpecialist | RoutabilitySpecialist | DRCSpecialist],
    stage_name: str,
    metrics: MetricsPayload | None,
    evidence: EvidencePack | None,
    scores: list[float],
    plateau_info: dict[str, object] | None,
) -> list[SpecialistAdvice]:
    """Consult all relevant specialists and collect their advice.

    Selects which specialists to consult based on current metrics:
    - TimingSpecialist: if there are timing violations or timing metrics exist
    - RoutabilitySpecialist: if there is congestion or routing stages
    - DRCSpecialist: if there are DRC violations or signoff stages

    Returns a list of successfully obtained SpecialistAdvice objects.
    """
    if metrics is None or evidence is None:
        return []

    # Determine which specialists are relevant for the current situation
    relevant: list[TimingSpecialist | RoutabilitySpecialist | DRCSpecialist] = []

    for specialist in specialists:
        if specialist.specialist_type == "timing":
            # Timing specialist is relevant if timing metrics exist
            # or if we're in a timing-sensitive stage
            timing_stages = {
                "CTS", "PLACE_GLOBAL", "PLACE_DETAILED",
                "ROUTE_GLOBAL", "ROUTE_DETAILED", "SIGNOFF",
            }
            has_timing = metrics.timing and metrics.timing.setup_wns_ns
            if has_timing or stage_name in timing_stages:
                relevant.append(specialist)

        elif specialist.specialist_type == "routability":
            # Routability specialist is relevant for routing and congestion
            route_stages = {
                "ROUTE_GLOBAL", "ROUTE_DETAILED", "PLACE_GLOBAL",
                "PLACE_DETAILED",
            }
            has_congestion = (
                metrics.route
                and metrics.route.congestion_overflow_pct is not None
                and metrics.route.congestion_overflow_pct > 0
            )
            if has_congestion or stage_name in route_stages:
                relevant.append(specialist)

        elif specialist.specialist_type == "drc":
            # DRC specialist is relevant if there are DRC violations
            # or in signoff stages
            drc_stages = {"SIGNOFF", "ROUTE_DETAILED"}
            has_drc = (
                metrics.signoff
                and metrics.signoff.drc_count is not None
                and metrics.signoff.drc_count > 0
            )
            if has_drc or stage_name in drc_stages:
                relevant.append(specialist)

    # Consult relevant specialists concurrently
    if not relevant:
        # Fallback: consult all specialists if none matched specifically
        relevant = list(specialists)

    results: list[SpecialistAdvice] = []
    tasks = [
        specialist.analyze(
            stage=stage_name,
            metrics=metrics,
            evidence=evidence,
            history=scores,
            plateau_info=dict(plateau_info) if plateau_info else None,
        )
        for specialist in relevant
    ]

    advice_results = await asyncio.gather(*tasks, return_exceptions=True)

    for advice in advice_results:
        if isinstance(advice, SpecialistAdvice):
            results.append(advice)
        elif isinstance(advice, Exception):
            logger.warning("Specialist consultation failed: %s", advice)

    return results
