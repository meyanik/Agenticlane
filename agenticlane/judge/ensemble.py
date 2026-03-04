"""Judge ensemble for AgenticLane.

Multiple independent judges vote PASS/FAIL on design iterations using
majority voting with deterministic gates and tie-breaking.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from agenticlane.agents.llm_provider import LLMProvider
from agenticlane.config.models import JudgingConfig
from agenticlane.schemas.constraints import ConstraintDigest
from agenticlane.schemas.evidence import EvidencePack
from agenticlane.schemas.judge import BlockingIssue, JudgeAggregate, JudgeVote
from agenticlane.schemas.metrics import MetricsPayload

logger = logging.getLogger(__name__)


class JudgeEnsemble:
    """Majority-voting judge ensemble with deterministic hard gates."""

    def __init__(
        self,
        llm_provider: LLMProvider,
        config: JudgingConfig,
    ) -> None:
        self.llm_provider = llm_provider
        self.config = config

    async def judge(
        self,
        stage_name: str,
        attempt_number: int,
        baseline_metrics: MetricsPayload,
        current_metrics: MetricsPayload,
        evidence_pack: EvidencePack,
        constraint_digest: Optional[ConstraintDigest] = None,
    ) -> JudgeAggregate:
        """Run ensemble judgment on current design iteration.

        1. Check deterministic hard gates first
        2. Get individual judge votes via LLM
        3. Aggregate via majority voting
        """
        num_judges = len(self.config.ensemble.models)
        logger.info(
            "JudgeEnsemble starting evaluation stage=%s attempt=%d num_judges=%d",
            stage_name,
            attempt_number,
            num_judges,
            extra={
                "agent": "judge",
                "event": "judge_start",
                "stage": stage_name,
                "attempt": attempt_number,
                "num_judges": num_judges,
                "judge_models": self.config.ensemble.models,
                "vote_rule": self.config.ensemble.vote,
            },
        )

        t0 = time.monotonic()

        # Step 1: Deterministic gates
        gate_failure = self._check_deterministic_gates(
            stage_name, current_metrics, evidence_pack
        )
        if gate_failure is not None:
            issues = [i.metric_key for i in gate_failure.blocking_issues]
            logger.warning(
                "JudgeEnsemble hard gate FAIL stage=%s attempt=%d blocking=%s",
                stage_name,
                attempt_number,
                issues,
                extra={
                    "agent": "judge",
                    "event": "hard_gate_fail",
                    "stage": stage_name,
                    "attempt": attempt_number,
                    "result": "FAIL",
                    "blocking_issues": issues,
                    "gate_triggered": True,
                },
            )
            return gate_failure

        # Step 2: Get individual votes
        votes = await self._get_individual_votes(
            stage_name=stage_name,
            attempt_number=attempt_number,
            baseline_metrics=baseline_metrics,
            current_metrics=current_metrics,
            evidence_pack=evidence_pack,
            constraint_digest=constraint_digest,
        )

        # Step 3: Aggregate
        aggregate = self._aggregate_votes(votes)
        latency_ms = (time.monotonic() - t0) * 1000

        pass_count = sum(1 for v in votes if v.vote == "PASS")
        fail_count = len(votes) - pass_count
        logger.info(
            "JudgeEnsemble result stage=%s attempt=%d result=%s "
            "confidence=%.2f pass=%d fail=%d latency_ms=%.1f",
            stage_name,
            attempt_number,
            aggregate.result,
            aggregate.confidence,
            pass_count,
            fail_count,
            latency_ms,
            extra={
                "agent": "judge",
                "event": "judge_done",
                "stage": stage_name,
                "attempt": attempt_number,
                "result": aggregate.result,
                "confidence": round(aggregate.confidence, 4),
                "pass_votes": pass_count,
                "fail_votes": fail_count,
                "total_votes": len(votes),
                "blocking_issues": [i.metric_key for i in aggregate.blocking_issues],
                "latency_ms": round(latency_ms, 1),
            },
        )
        return aggregate

    def _check_deterministic_gates(
        self,
        stage_name: str,
        metrics: MetricsPayload,
        evidence: EvidencePack,
    ) -> Optional[JudgeAggregate]:
        """Check hard gates that auto-fail regardless of votes.

        Returns JudgeAggregate (failure) or None (gates pass).
        """
        issues: list[BlockingIssue] = []

        # Gate: execution_success
        if (
            "execution_success" in self.config.strictness.hard_gates
            and metrics.execution_status != "success"
        ):
            issues.append(
                BlockingIssue(
                    metric_key="execution_status",
                    description=f"Execution failed: {metrics.execution_status}",
                    severity="critical",
                )
            )

        # Gate: metrics_parse_valid - check if any metrics were extracted
        if "metrics_parse_valid" in self.config.strictness.hard_gates:
            has_any = (
                metrics.timing is not None
                or metrics.physical is not None
                or metrics.route is not None
                or metrics.signoff is not None
                or metrics.synthesis is not None
                or metrics.runtime is not None
            )
            if not has_any:
                issues.append(
                    BlockingIssue(
                        metric_key="metrics_parse",
                        description="No metrics could be extracted",
                        severity="critical",
                    )
                )

        # Signoff-specific gates
        if stage_name == "SIGNOFF":
            if (
                "drc_clean" in self.config.strictness.signoff_hard_gates
                and metrics.signoff is not None
                and metrics.signoff.drc_count is not None
                and metrics.signoff.drc_count > 0
            ):
                issues.append(
                    BlockingIssue(
                        metric_key="drc_count",
                        description=f"DRC violations: {metrics.signoff.drc_count}",
                        severity="critical",
                    )
                )
            if (
                "lvs_pass" in self.config.strictness.signoff_hard_gates
                and metrics.signoff is not None
                and metrics.signoff.lvs_pass is not None
                and not metrics.signoff.lvs_pass
            ):
                issues.append(
                    BlockingIssue(
                        metric_key="lvs_pass",
                        description="LVS check failed",
                        severity="critical",
                    )
                )

        # Check crash_info
        if evidence.crash_info is not None:
            issues.append(
                BlockingIssue(
                    metric_key="crash",
                    description=f"Crash detected: {evidence.crash_info.crash_type}",
                    severity="critical",
                )
            )

        if issues:
            logger.debug(
                "JudgeEnsemble deterministic gates triggered stage=%s issues=%s",
                stage_name,
                [i.metric_key for i in issues],
                extra={
                    "agent": "judge",
                    "event": "deterministic_gate_check",
                    "stage": stage_name,
                    "gate_passed": False,
                    "blocking_issue_keys": [i.metric_key for i in issues],
                    "execution_status": metrics.execution_status,
                    "has_crash": evidence.crash_info is not None,
                },
            )
            return JudgeAggregate(
                votes=[],
                result="FAIL",
                confidence=1.0,
                blocking_issues=issues,
            )

        logger.debug(
            "JudgeEnsemble deterministic gates passed stage=%s",
            stage_name,
            extra={
                "agent": "judge",
                "event": "deterministic_gate_check",
                "stage": stage_name,
                "gate_passed": True,
                "blocking_issue_keys": [],
                "execution_status": metrics.execution_status,
                "has_crash": False,
            },
        )
        return None

    async def _get_individual_votes(
        self,
        stage_name: str,
        attempt_number: int,
        baseline_metrics: MetricsPayload,
        current_metrics: MetricsPayload,
        evidence_pack: EvidencePack,
        constraint_digest: Optional[ConstraintDigest],
    ) -> list[JudgeVote]:
        """Get individual judge votes via LLM batch_generate."""
        # Use per-stage model override if configured, else default ensemble models
        judge_models = self.llm_provider.resolve_judge_models_for_stage(stage_name)
        num_judges = len(judge_models)

        logger.debug(
            "JudgeEnsemble dispatching %d LLM judge calls stage=%s attempt=%d",
            num_judges,
            stage_name,
            attempt_number,
            extra={
                "agent": "judge",
                "event": "llm_batch_start",
                "stage": stage_name,
                "attempt": attempt_number,
                "num_judges": num_judges,
                "judge_models": judge_models,
            },
        )

        # Build judge prompts
        prompts = []
        for i in range(num_judges):
            prompt = self._build_judge_prompt(
                judge_index=i,
                model_name=judge_models[i],
                stage_name=stage_name,
                attempt_number=attempt_number,
                baseline_metrics=baseline_metrics,
                current_metrics=current_metrics,
                evidence_pack=evidence_pack,
                constraint_digest=constraint_digest,
            )
            prompts.append(prompt)

        t0 = time.monotonic()
        # Batch generate
        results = await self.llm_provider.batch_generate(
            prompts=prompts,
            response_model=JudgeVote,
            models=judge_models,
            stage=stage_name,
            attempt=attempt_number,
            role="judge",
            max_concurrent=min(3, num_judges),
        )
        latency_ms = (time.monotonic() - t0) * 1000

        # Filter out None (failed) votes and backfill metadata
        votes: list[JudgeVote] = []
        failed_count = 0
        for i, v in enumerate(results):
            if v is not None:
                v.judge_id = f"judge_{i}"
                v.model = judge_models[i] if i < len(judge_models) else "unknown"
                votes.append(v)
                logger.debug(
                    "JudgeEnsemble vote received judge_id=judge_%d model=%s "
                    "vote=%s confidence=%.2f stage=%s attempt=%d",
                    i,
                    v.model,
                    v.vote,
                    v.confidence or 0.0,
                    stage_name,
                    attempt_number,
                    extra={
                        "agent": "judge",
                        "event": "vote_received",
                        "stage": stage_name,
                        "attempt": attempt_number,
                        "judge_id": f"judge_{i}",
                        "judge_model": v.model,
                        "vote": v.vote,
                        "confidence": v.confidence,
                        "blocking_issue_count": len(v.blocking_issues),
                    },
                )
            else:
                failed_count += 1
                logger.warning(
                    "JudgeEnsemble judge_%d returned None (LLM failure) stage=%s attempt=%d",
                    i,
                    stage_name,
                    attempt_number,
                    extra={
                        "agent": "judge",
                        "event": "vote_failure",
                        "stage": stage_name,
                        "attempt": attempt_number,
                        "judge_id": f"judge_{i}",
                        "judge_model": judge_models[i] if i < len(judge_models) else "unknown",
                    },
                )

        logger.debug(
            "JudgeEnsemble batch done stage=%s attempt=%d "
            "votes_received=%d votes_failed=%d latency_ms=%.1f",
            stage_name,
            attempt_number,
            len(votes),
            failed_count,
            latency_ms,
            extra={
                "agent": "judge",
                "event": "llm_batch_done",
                "stage": stage_name,
                "attempt": attempt_number,
                "votes_received": len(votes),
                "votes_failed": failed_count,
                "latency_ms": round(latency_ms, 1),
            },
        )
        return votes

    def _build_judge_prompt(
        self,
        judge_index: int,
        model_name: str,
        stage_name: str,
        attempt_number: int,
        baseline_metrics: MetricsPayload,
        current_metrics: MetricsPayload,
        evidence_pack: EvidencePack,
        constraint_digest: Optional[ConstraintDigest],
    ) -> str:
        """Build judge evaluation prompt."""
        # Stage-appropriate evaluation context
        stage_context = {
            "SYNTH": (
                "This is a SYNTHESIS stage. Only logic synthesis metrics are expected. "
                "Timing data may be minimal (no STA yet). Physical, routing, and signoff "
                "metrics are NOT expected at this stage — do NOT penalize for their absence. "
                "Focus on: execution success, cell count, and basic gate-level metrics."
            ),
            "FLOORPLAN": (
                "This is a FLOORPLAN stage. Core utilization and die area are the key metrics. "
                "Detailed timing is not yet available. Route metrics are NOT expected."
            ),
            "PDN": (
                "This is the PDN (Power Distribution Network) stage. "
                "Focus on execution success. Detailed metrics may be limited. "
                "Route and signoff metrics are NOT expected."
            ),
            "PLACE_GLOBAL": (
                "This is GLOBAL PLACEMENT. Focus on execution success and any "
                "congestion or area metrics. Timing is preliminary. "
                "Route and signoff metrics are NOT expected."
            ),
            "PLACE_DETAILED": (
                "This is DETAILED PLACEMENT. Focus on execution success, "
                "area utilization, and preliminary timing if available."
            ),
            "CTS": (
                "This is CLOCK TREE SYNTHESIS. Focus on execution success "
                "and timing metrics (setup/hold slack). Route metrics may not be final."
            ),
            "ROUTE_GLOBAL": (
                "This is GLOBAL ROUTING. Focus on execution success and "
                "congestion/overflow metrics. Signoff metrics are NOT expected."
            ),
            "ROUTE_DETAILED": (
                "This is DETAILED ROUTING. Focus on execution success, "
                "DRC violations, and routing overflow. LVS is not yet run."
            ),
            "FINISH": (
                "This is the FINISH stage (metal fill, etc.). "
                "Focus on execution success. Metrics may be similar to routing."
            ),
            "SIGNOFF": (
                "This is SIGNOFF — ALL metrics must be present. DRC must be 0, LVS must pass, "
                "timing must meet targets."
            ),
        }
        stage_hint = stage_context.get(
            stage_name,
            f"This is the {stage_name} stage. Evaluate metrics appropriate to this stage.",
        )

        parts: list[str] = []
        parts.append(
            f"You are judge_{judge_index}, evaluating {stage_name} "
            f"attempt {attempt_number}."
        )
        parts.append("")
        parts.append(f"## Stage Context\n{stage_hint}")
        parts.append("")
        parts.append("## Baseline Metrics")
        parts.append(baseline_metrics.model_dump_json(indent=2))
        parts.append("")
        parts.append("## Current Metrics")
        parts.append(current_metrics.model_dump_json(indent=2))
        parts.append("")
        parts.append("## Evidence")
        parts.append(evidence_pack.model_dump_json(indent=2))
        if constraint_digest:
            parts.append("")
            parts.append("## Constraints")
            parts.append(constraint_digest.model_dump_json(indent=2))
        parts.append("")
        parts.append(
            "## Decision Rules\n"
            "- If execution_status is 'success' and no crash occurred, lean toward PASS "
            "unless there is a clear metric REGRESSION vs baseline.\n"
            "- Missing metrics that are not expected for this stage are NOT blocking issues.\n"
            "- If current metrics match or improve on baseline, vote PASS.\n"
            "- Only vote FAIL for genuine regressions or execution failures.\n"
        )
        parts.append(
            "Vote PASS or FAIL. Respond with ONLY valid JSON in this exact format:\n"
            "{\n"
            f'  "judge_id": "judge_{judge_index}",\n'
            f'  "model": "{model_name}",\n'
            '  "vote": "PASS or FAIL",\n'
            '  "confidence": 0.85,\n'
            '  "blocking_issues": [\n'
            '    {"metric_key": "setup_wns_ns", "description": "...", "severity": "high"}\n'
            "  ],\n"
            '  "rationale": "Your reasoning here"\n'
            "}"
        )
        return "\n".join(parts)

    def _aggregate_votes(self, votes: list[JudgeVote]) -> JudgeAggregate:
        """Aggregate individual votes via majority voting."""
        if not votes:
            logger.warning(
                "JudgeEnsemble aggregation received zero valid votes",
                extra={
                    "agent": "judge",
                    "event": "aggregate_votes",
                    "result": "FAIL",
                    "reason": "no_valid_votes",
                    "pass_votes": 0,
                    "fail_votes": 0,
                    "total_votes": 0,
                },
            )
            return JudgeAggregate(
                votes=[],
                result="FAIL",
                confidence=0.0,
                blocking_issues=[
                    BlockingIssue(
                        metric_key="judge_votes",
                        description="No valid judge responses received",
                    )
                ],
            )

        pass_count = sum(1 for v in votes if v.vote == "PASS")
        fail_count = len(votes) - pass_count

        if self.config.ensemble.vote == "unanimous":
            result = "PASS" if fail_count == 0 else "FAIL"
        else:  # majority
            if pass_count > fail_count:
                result = "PASS"
            elif fail_count > pass_count:
                result = "FAIL"
            else:
                # Tie: use tie_breaker
                result = self.config.ensemble.tie_breaker.upper()  # type: ignore[assignment]

        # Confidence = fraction of majority
        total = len(votes)
        majority_count = max(pass_count, fail_count)
        confidence = majority_count / total if total > 0 else 0.0

        # Collect blocking issues from FAIL votes
        all_issues: list[BlockingIssue] = []
        for v in votes:
            if v.vote == "FAIL":
                all_issues.extend(v.blocking_issues)

        logger.debug(
            "JudgeEnsemble aggregate result=%s confidence=%.2f "
            "pass=%d fail=%d rule=%s",
            result,
            confidence,
            pass_count,
            fail_count,
            self.config.ensemble.vote,
            extra={
                "agent": "judge",
                "event": "aggregate_votes",
                "result": result,
                "confidence": round(confidence, 4),
                "pass_votes": pass_count,
                "fail_votes": fail_count,
                "total_votes": total,
                "vote_rule": self.config.ensemble.vote,
                "blocking_issue_count": len(all_issues),
            },
        )

        return JudgeAggregate(
            votes=votes,
            result=result,
            confidence=confidence,
            blocking_issues=all_issues,
        )
