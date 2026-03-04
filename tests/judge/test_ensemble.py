"""P3.4 Judge Ensemble tests."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agenticlane.agents.mock_llm import MockLLMProvider
from agenticlane.config.models import (
    JudgeEnsembleConfig,
    JudgingConfig,
)
from agenticlane.judge.ensemble import JudgeEnsemble
from agenticlane.schemas.evidence import CrashInfo, EvidencePack
from agenticlane.schemas.judge import BlockingIssue, JudgeVote
from agenticlane.schemas.metrics import MetricsPayload, SignoffMetrics, TimingMetrics


def _make_metrics(
    status: str = "success",
    wns: dict[str, float] | None = None,
    drc: int | None = None,
    lvs: bool | None = None,
) -> MetricsPayload:
    return MetricsPayload(
        run_id="test",
        branch_id="B0",
        stage="PLACE_GLOBAL",
        attempt=1,
        execution_status=status,
        timing=TimingMetrics(setup_wns_ns=wns) if wns else None,
        signoff=(
            SignoffMetrics(drc_count=drc, lvs_pass=lvs)
            if (drc is not None or lvs is not None)
            else None
        ),
    )


def _make_evidence(crash: bool = False) -> EvidencePack:
    return EvidencePack(
        stage="PLACE_GLOBAL",
        attempt=1,
        execution_status="success",
        crash_info=CrashInfo(crash_type="tool_crash") if crash else None,
    )


def _make_vote(
    judge_id: str,
    vote: str,
    confidence: float = 0.8,
    issues: list[BlockingIssue] | None = None,
) -> JudgeVote:
    return JudgeVote(
        judge_id=judge_id,
        model="test_model",
        vote=vote,
        confidence=confidence,
        blocking_issues=issues or [],
        rationale=f"Vote {vote}",
    )


class TestDeterministicGates:
    @pytest.fixture()
    def ensemble(self, tmp_path: Path) -> JudgeEnsemble:
        provider = MockLLMProvider(log_dir=tmp_path)
        config = JudgingConfig()
        return JudgeEnsemble(provider, config)

    def test_execution_failure_auto_fails(self, ensemble: JudgeEnsemble) -> None:
        metrics = _make_metrics(status="tool_crash")
        evidence = _make_evidence()
        result = asyncio.run(
            ensemble.judge("PLACE_GLOBAL", 1, _make_metrics(), metrics, evidence)
        )
        assert result.result == "FAIL"
        assert result.confidence == 1.0
        assert any(
            i.metric_key == "execution_status" for i in result.blocking_issues
        )

    def test_no_metrics_auto_fails(self, ensemble: JudgeEnsemble) -> None:
        """When no sub-metrics are present, metrics_parse_valid gate fires."""
        metrics = _make_metrics()  # No timing, physical, route, signoff
        evidence = _make_evidence()
        result = asyncio.run(
            ensemble.judge("PLACE_GLOBAL", 1, _make_metrics(), metrics, evidence)
        )
        assert result.result == "FAIL"
        assert any(i.metric_key == "metrics_parse" for i in result.blocking_issues)

    def test_crash_auto_fails(self, ensemble: JudgeEnsemble) -> None:
        metrics = _make_metrics(wns={"tt": -0.1})
        evidence = _make_evidence(crash=True)
        result = asyncio.run(
            ensemble.judge("PLACE_GLOBAL", 1, _make_metrics(), metrics, evidence)
        )
        assert result.result == "FAIL"
        assert any(i.metric_key == "crash" for i in result.blocking_issues)

    def test_signoff_drc_gate(self, ensemble: JudgeEnsemble) -> None:
        metrics = _make_metrics(wns={"tt": 0.1}, drc=5)
        evidence = _make_evidence()
        result = asyncio.run(
            ensemble.judge("SIGNOFF", 1, _make_metrics(), metrics, evidence)
        )
        assert result.result == "FAIL"
        assert any(i.metric_key == "drc_count" for i in result.blocking_issues)

    def test_signoff_lvs_gate(self, ensemble: JudgeEnsemble) -> None:
        metrics = _make_metrics(wns={"tt": 0.1}, lvs=False)
        evidence = _make_evidence()
        result = asyncio.run(
            ensemble.judge("SIGNOFF", 1, _make_metrics(), metrics, evidence)
        )
        assert result.result == "FAIL"
        assert any(i.metric_key == "lvs_pass" for i in result.blocking_issues)

    def test_signoff_gates_not_triggered_on_non_signoff_stage(
        self, ensemble: JudgeEnsemble
    ) -> None:
        """DRC/LVS gates should only fire for SIGNOFF stage."""
        metrics = _make_metrics(wns={"tt": 0.1}, drc=5, lvs=False)
        evidence = _make_evidence()
        result = asyncio.run(
            ensemble.judge("PLACE_GLOBAL", 1, _make_metrics(), metrics, evidence)
        )
        # Should not have drc or lvs blocking issues
        drc_lvs_issues = [
            i
            for i in result.blocking_issues
            if i.metric_key in ("drc_count", "lvs_pass")
        ]
        assert len(drc_lvs_issues) == 0

    def test_gates_pass_for_good_metrics(self, ensemble: JudgeEnsemble) -> None:
        """Good metrics should not trigger gate failure."""
        metrics = _make_metrics(wns={"tt": 0.1})
        evidence = _make_evidence()
        # MockLLM returns {} which won't parse as JudgeVote -> None votes -> FAIL
        # But that's because of empty LLM, not gates
        result = asyncio.run(
            ensemble.judge("PLACE_GLOBAL", 1, _make_metrics(), metrics, evidence)
        )
        # Should NOT have execution_status or crash in blocking issues
        gate_issues = [
            i
            for i in result.blocking_issues
            if i.metric_key in ("execution_status", "crash")
        ]
        assert len(gate_issues) == 0

    def test_multiple_gate_failures_collected(
        self, ensemble: JudgeEnsemble
    ) -> None:
        """Multiple gate failures should all be reported."""
        metrics = _make_metrics(status="tool_crash")  # No sub-metrics either
        evidence = _make_evidence(crash=True)
        result = asyncio.run(
            ensemble.judge("PLACE_GLOBAL", 1, _make_metrics(), metrics, evidence)
        )
        assert result.result == "FAIL"
        assert result.confidence == 1.0
        issue_keys = [i.metric_key for i in result.blocking_issues]
        assert "execution_status" in issue_keys
        assert "metrics_parse" in issue_keys
        assert "crash" in issue_keys


class TestMajorityVoting:
    def _make_ensemble(
        self, tmp_path: Path, tie_breaker: str = "fail"
    ) -> tuple[JudgeEnsemble, MockLLMProvider]:
        provider = MockLLMProvider(log_dir=tmp_path)
        config = JudgingConfig(
            ensemble=JudgeEnsembleConfig(
                models=["m1", "m2", "m3"],
                vote="majority",
                tie_breaker=tie_breaker,
            ),
        )
        return JudgeEnsemble(provider, config), provider

    def test_majority_pass(self, tmp_path: Path) -> None:
        ensemble, provider = self._make_ensemble(tmp_path)
        v1 = _make_vote("j0", "PASS")
        v2 = _make_vote("j1", "PASS")
        v3 = _make_vote("j2", "FAIL")
        provider.queue_responses(v1, v2, v3)

        metrics = _make_metrics(wns={"tt": 0.1})
        result = asyncio.run(
            ensemble.judge(
                "PLACE_GLOBAL", 1, _make_metrics(), metrics, _make_evidence()
            )
        )
        assert result.result == "PASS"
        assert len(result.votes) == 3

    def test_majority_fail(self, tmp_path: Path) -> None:
        ensemble, provider = self._make_ensemble(tmp_path)
        v1 = _make_vote(
            "j0",
            "FAIL",
            issues=[BlockingIssue(metric_key="wns", description="bad")],
        )
        v2 = _make_vote(
            "j1",
            "FAIL",
            issues=[BlockingIssue(metric_key="area", description="big")],
        )
        v3 = _make_vote("j2", "PASS")
        provider.queue_responses(v1, v2, v3)

        metrics = _make_metrics(wns={"tt": 0.1})
        result = asyncio.run(
            ensemble.judge(
                "PLACE_GLOBAL", 1, _make_metrics(), metrics, _make_evidence()
            )
        )
        assert result.result == "FAIL"
        assert len(result.blocking_issues) == 2

    def test_majority_confidence_calculation(self, tmp_path: Path) -> None:
        """Confidence should be majority_count / total."""
        ensemble, provider = self._make_ensemble(tmp_path)
        v1 = _make_vote("j0", "PASS")
        v2 = _make_vote("j1", "PASS")
        v3 = _make_vote("j2", "FAIL")
        provider.queue_responses(v1, v2, v3)

        metrics = _make_metrics(wns={"tt": 0.1})
        result = asyncio.run(
            ensemble.judge(
                "PLACE_GLOBAL", 1, _make_metrics(), metrics, _make_evidence()
            )
        )
        # 2 out of 3 passed
        assert result.confidence == pytest.approx(2.0 / 3.0)

    def test_unanimous_pass(self, tmp_path: Path) -> None:
        ensemble, provider = self._make_ensemble(tmp_path)
        votes = [_make_vote(f"j{i}", "PASS") for i in range(3)]
        provider.queue_responses(*votes)

        metrics = _make_metrics(wns={"tt": 0.1})
        result = asyncio.run(
            ensemble.judge(
                "PLACE_GLOBAL", 1, _make_metrics(), metrics, _make_evidence()
            )
        )
        assert result.result == "PASS"
        assert result.confidence == 1.0

    def test_tie_breaker_fail(self, tmp_path: Path) -> None:
        provider = MockLLMProvider(log_dir=tmp_path)
        config = JudgingConfig(
            ensemble=JudgeEnsembleConfig(
                models=["m1", "m2"],
                vote="majority",
                tie_breaker="fail",
            ),
        )
        ensemble = JudgeEnsemble(provider, config)
        v1 = _make_vote("j0", "PASS")
        v2 = _make_vote("j1", "FAIL")
        provider.queue_responses(v1, v2)

        metrics = _make_metrics(wns={"tt": 0.1})
        result = asyncio.run(
            ensemble.judge(
                "PLACE_GLOBAL", 1, _make_metrics(), metrics, _make_evidence()
            )
        )
        assert result.result == "FAIL"

    def test_tie_breaker_pass(self, tmp_path: Path) -> None:
        provider = MockLLMProvider(log_dir=tmp_path)
        config = JudgingConfig(
            ensemble=JudgeEnsembleConfig(
                models=["m1", "m2"],
                vote="majority",
                tie_breaker="pass",
            ),
        )
        ensemble = JudgeEnsemble(provider, config)
        v1 = _make_vote("j0", "PASS")
        v2 = _make_vote("j1", "FAIL")
        provider.queue_responses(v1, v2)

        metrics = _make_metrics(wns={"tt": 0.1})
        result = asyncio.run(
            ensemble.judge(
                "PLACE_GLOBAL", 1, _make_metrics(), metrics, _make_evidence()
            )
        )
        assert result.result == "PASS"

    def test_no_valid_votes_fails(self, tmp_path: Path) -> None:
        ensemble, _provider = self._make_ensemble(tmp_path)
        # MockLLM returns {} which won't parse -> all None
        metrics = _make_metrics(wns={"tt": 0.1})
        result = asyncio.run(
            ensemble.judge(
                "PLACE_GLOBAL", 1, _make_metrics(), metrics, _make_evidence()
            )
        )
        assert result.result == "FAIL"
        assert result.confidence == 0.0

    def test_individual_votes_recorded(self, tmp_path: Path) -> None:
        ensemble, provider = self._make_ensemble(tmp_path)
        votes = [_make_vote(f"j{i}", "PASS", confidence=0.9) for i in range(3)]
        provider.queue_responses(*votes)

        metrics = _make_metrics(wns={"tt": 0.1})
        result = asyncio.run(
            ensemble.judge(
                "PLACE_GLOBAL", 1, _make_metrics(), metrics, _make_evidence()
            )
        )
        assert len(result.votes) == 3
        for v in result.votes:
            assert v.vote == "PASS"
            assert v.confidence == 0.9

    def test_fail_votes_blocking_issues_collected(self, tmp_path: Path) -> None:
        """Blocking issues from all FAIL votes should be aggregated."""
        ensemble, provider = self._make_ensemble(tmp_path)
        v1 = _make_vote(
            "j0",
            "FAIL",
            issues=[
                BlockingIssue(metric_key="wns", description="timing bad"),
                BlockingIssue(metric_key="area", description="area big"),
            ],
        )
        v2 = _make_vote(
            "j1",
            "FAIL",
            issues=[BlockingIssue(metric_key="congestion", description="hot")],
        )
        v3 = _make_vote("j2", "PASS")
        provider.queue_responses(v1, v2, v3)

        metrics = _make_metrics(wns={"tt": 0.1})
        result = asyncio.run(
            ensemble.judge(
                "PLACE_GLOBAL", 1, _make_metrics(), metrics, _make_evidence()
            )
        )
        assert result.result == "FAIL"
        assert len(result.blocking_issues) == 3
        issue_keys = {i.metric_key for i in result.blocking_issues}
        assert issue_keys == {"wns", "area", "congestion"}


class TestUnanimousVoting:
    def test_unanimous_required_all_pass(self, tmp_path: Path) -> None:
        provider = MockLLMProvider(log_dir=tmp_path)
        config = JudgingConfig(
            ensemble=JudgeEnsembleConfig(
                models=["m1", "m2", "m3"],
                vote="unanimous",
            ),
        )
        ensemble = JudgeEnsemble(provider, config)
        votes = [_make_vote(f"j{i}", "PASS") for i in range(3)]
        provider.queue_responses(*votes)

        metrics = _make_metrics(wns={"tt": 0.1})
        result = asyncio.run(
            ensemble.judge(
                "PLACE_GLOBAL", 1, _make_metrics(), metrics, _make_evidence()
            )
        )
        assert result.result == "PASS"
        assert result.confidence == 1.0

    def test_unanimous_fails_with_one_dissent(self, tmp_path: Path) -> None:
        provider = MockLLMProvider(log_dir=tmp_path)
        config = JudgingConfig(
            ensemble=JudgeEnsembleConfig(
                models=["m1", "m2", "m3"],
                vote="unanimous",
            ),
        )
        ensemble = JudgeEnsemble(provider, config)
        v1 = _make_vote("j0", "PASS")
        v2 = _make_vote("j1", "PASS")
        v3 = _make_vote("j2", "FAIL")
        provider.queue_responses(v1, v2, v3)

        metrics = _make_metrics(wns={"tt": 0.1})
        result = asyncio.run(
            ensemble.judge(
                "PLACE_GLOBAL", 1, _make_metrics(), metrics, _make_evidence()
            )
        )
        assert result.result == "FAIL"  # Not unanimous


class TestPromptBuilding:
    """Test that judge prompts are built correctly."""

    def test_prompt_contains_stage_info(self, tmp_path: Path) -> None:
        provider = MockLLMProvider(log_dir=tmp_path)
        config = JudgingConfig(
            ensemble=JudgeEnsembleConfig(models=["m1"]),
        )
        ensemble = JudgeEnsemble(provider, config)

        baseline = _make_metrics(wns={"tt": 0.0})
        current = _make_metrics(wns={"tt": 0.1})
        evidence = _make_evidence()

        prompt = ensemble._build_judge_prompt(
            judge_index=0,
            model_name="m1",
            stage_name="PLACE_GLOBAL",
            attempt_number=3,
            baseline_metrics=baseline,
            current_metrics=current,
            evidence_pack=evidence,
            constraint_digest=None,
        )

        assert "judge_0" in prompt
        assert "PLACE_GLOBAL" in prompt
        assert "attempt 3" in prompt
        assert "Baseline Metrics" in prompt
        assert "Current Metrics" in prompt
        assert "Evidence" in prompt
        assert "Constraints" not in prompt  # No constraint digest

    def test_prompt_includes_constraints_when_provided(
        self, tmp_path: Path
    ) -> None:
        from agenticlane.schemas.constraints import ConstraintDigest

        provider = MockLLMProvider(log_dir=tmp_path)
        config = JudgingConfig(
            ensemble=JudgeEnsembleConfig(models=["m1"]),
        )
        ensemble = JudgeEnsemble(provider, config)

        baseline = _make_metrics(wns={"tt": 0.0})
        current = _make_metrics(wns={"tt": 0.1})
        evidence = _make_evidence()
        constraints = ConstraintDigest()

        prompt = ensemble._build_judge_prompt(
            judge_index=0,
            model_name="m1",
            stage_name="PLACE_GLOBAL",
            attempt_number=1,
            baseline_metrics=baseline,
            current_metrics=current,
            evidence_pack=evidence,
            constraint_digest=constraints,
        )

        assert "Constraints" in prompt
