"""P3.3 Worker Agent tests."""
from pathlib import Path

import pytest

from agenticlane.agents.mock_llm import MockLLMProvider
from agenticlane.agents.workers.base import WorkerAgent
from agenticlane.agents.workers.placement import PlacementWorker
from agenticlane.agents.workers.synth import SynthWorker
from agenticlane.config.models import AgenticLaneConfig
from agenticlane.schemas.constraints import ClockDefinition, ConstraintDigest
from agenticlane.schemas.evidence import EvidencePack
from agenticlane.schemas.metrics import MetricsPayload, PhysicalMetrics, TimingMetrics
from agenticlane.schemas.patch import Patch


def _make_metrics(**kwargs):  # type: ignore[no-untyped-def]
    defaults = dict(
        run_id="test", branch_id="B0", stage="SYNTH", attempt=1, execution_status="success"
    )
    defaults.update(kwargs)
    return MetricsPayload(**defaults)


def _make_evidence(**kwargs):  # type: ignore[no-untyped-def]
    defaults = dict(stage="SYNTH", attempt=1, execution_status="success")
    defaults.update(kwargs)
    return EvidencePack(**defaults)


def _make_patch(stage: str = "SYNTH") -> Patch:
    return Patch(
        patch_id="test_patch",
        stage=stage,
        types=["config_vars"],
        config_vars={"PL_TARGET_DENSITY_PCT": 65},
        rationale="Test patch",
    )


class TestWorkerAgent:
    @pytest.fixture
    def mock_provider(self, tmp_path: Path) -> MockLLMProvider:
        return MockLLMProvider(log_dir=tmp_path)

    @pytest.fixture
    def config(self) -> AgenticLaneConfig:
        return AgenticLaneConfig()

    @pytest.mark.asyncio
    async def test_propose_patch_returns_patch(
        self, mock_provider: MockLLMProvider, config: AgenticLaneConfig
    ) -> None:
        patch = _make_patch("SYNTH")
        mock_provider.set_response(patch)
        worker = WorkerAgent(mock_provider, "SYNTH", config)
        result = await worker.propose_patch(_make_metrics(), _make_evidence())
        assert result is not None
        assert isinstance(result, Patch)

    @pytest.mark.asyncio
    async def test_propose_patch_returns_none_on_failure(
        self, mock_provider: MockLLMProvider, config: AgenticLaneConfig
    ) -> None:
        mock_provider.set_failure(count=100)
        worker = WorkerAgent(mock_provider, "SYNTH", config)
        result = await worker.propose_patch(_make_metrics(), _make_evidence())
        assert result is None

    @pytest.mark.asyncio
    async def test_worker_uses_correct_stage(
        self, mock_provider: MockLLMProvider, config: AgenticLaneConfig
    ) -> None:
        patch = _make_patch("PLACE_GLOBAL")
        mock_provider.set_response(patch)
        worker = WorkerAgent(mock_provider, "PLACE_GLOBAL", config)
        await worker.propose_patch(
            _make_metrics(stage="PLACE_GLOBAL"),
            _make_evidence(stage="PLACE_GLOBAL"),
        )
        # Check LLM was called with stage="PLACE_GLOBAL"
        records = mock_provider.call_records
        assert len(records) >= 1
        assert records[0].stage == "PLACE_GLOBAL"

    def test_context_includes_metrics(
        self, mock_provider: MockLLMProvider, config: AgenticLaneConfig
    ) -> None:
        worker = WorkerAgent(mock_provider, "SYNTH", config)
        metrics = _make_metrics(
            timing=TimingMetrics(setup_wns_ns={"tt": -0.5}),
            physical=PhysicalMetrics(core_area_um2=1000.0),
        )
        ctx = worker._build_context(
            current_metrics=metrics,
            evidence_pack=_make_evidence(),
            constraint_digest=None,
            attempt_number=1,
            last_rejection=None,
            lessons_markdown=None,
        )
        assert "Setup WNS" in ctx["metrics_summary"]
        assert "Core area" in ctx["metrics_summary"]

    def test_context_includes_locked_vars(
        self, mock_provider: MockLLMProvider, config: AgenticLaneConfig
    ) -> None:
        worker = WorkerAgent(mock_provider, "SYNTH", config)
        ctx = worker._build_context(
            current_metrics=_make_metrics(),
            evidence_pack=_make_evidence(),
            constraint_digest=None,
            attempt_number=1,
            last_rejection=None,
            lessons_markdown=None,
        )
        assert "CLOCK_PERIOD" in ctx["locked_constraints"]

    def test_context_includes_rejection_feedback(
        self, mock_provider: MockLLMProvider, config: AgenticLaneConfig
    ) -> None:
        from agenticlane.schemas.patch import PatchRejected

        rejection = PatchRejected(
            patch_id="test",
            stage="SYNTH",
            reason_code="locked_constraint",
            offending_channel="config_vars",
            remediation_hint="Remove CLOCK_PERIOD from your patch",
        )
        worker = WorkerAgent(mock_provider, "SYNTH", config)
        ctx = worker._build_context(
            current_metrics=_make_metrics(),
            evidence_pack=_make_evidence(),
            constraint_digest=None,
            attempt_number=2,
            last_rejection=rejection,
            lessons_markdown=None,
        )
        assert ctx["last_rejection_feedback"] == "Remove CLOCK_PERIOD from your patch"

    def test_allowed_knobs_exclude_locked(
        self, mock_provider: MockLLMProvider, config: AgenticLaneConfig
    ) -> None:
        worker = WorkerAgent(mock_provider, "PLACE_GLOBAL", config)
        knobs = worker._get_allowed_knobs()
        assert "CLOCK_PERIOD" not in knobs

    def test_intent_formatted(
        self, mock_provider: MockLLMProvider, config: AgenticLaneConfig
    ) -> None:
        worker = WorkerAgent(mock_provider, "SYNTH", config)
        intent = worker._format_intent()
        assert "timing" in intent.lower() or "70%" in intent

    def test_format_metrics_empty(self) -> None:
        metrics = _make_metrics()
        result = WorkerAgent._format_metrics(metrics)
        assert result == "No metrics available."

    def test_format_evidence_empty(self) -> None:
        evidence = _make_evidence()
        result = WorkerAgent._format_evidence(evidence)
        assert result == "No issues found."

    def test_format_knobs_table_empty(self) -> None:
        result = WorkerAgent._format_knobs_table({})
        assert result == "No knobs available."

    def test_format_knobs_table_with_knobs(
        self, mock_provider: MockLLMProvider, config: AgenticLaneConfig
    ) -> None:
        worker = WorkerAgent(mock_provider, "SYNTH", config)
        knobs = worker._get_allowed_knobs()
        table = WorkerAgent._format_knobs_table(knobs)
        assert "Knob" in table
        assert "SYNTH_STRATEGY" in table

    @pytest.mark.asyncio
    async def test_propose_patch_with_constraint_digest(
        self, mock_provider: MockLLMProvider, config: AgenticLaneConfig
    ) -> None:
        patch = _make_patch("SYNTH")
        mock_provider.set_response(patch)
        digest = ConstraintDigest(
            clocks=[ClockDefinition(name="core_clk", period_ns=10.0)],
        )
        worker = WorkerAgent(mock_provider, "SYNTH", config)
        result = await worker.propose_patch(
            _make_metrics(),
            _make_evidence(),
            constraint_digest=digest,
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_propose_patch_with_lessons_markdown(
        self, mock_provider: MockLLMProvider, config: AgenticLaneConfig
    ) -> None:
        patch = _make_patch("SYNTH")
        mock_provider.set_response(patch)
        worker = WorkerAgent(mock_provider, "SYNTH", config)
        result = await worker.propose_patch(
            _make_metrics(),
            _make_evidence(),
            lessons_markdown="Previous attempts failed due to high congestion.",
        )
        assert result is not None


class TestSynthWorker:
    def test_synth_worker_is_worker(self) -> None:
        assert issubclass(SynthWorker, WorkerAgent)


class TestPlacementWorker:
    def test_placement_worker_is_worker(self) -> None:
        assert issubclass(PlacementWorker, WorkerAgent)

    def test_placement_knobs_include_density(self, tmp_path: Path) -> None:
        provider = MockLLMProvider(log_dir=tmp_path)
        config = AgenticLaneConfig()
        worker = PlacementWorker(provider, "PLACE_GLOBAL", config)
        knobs = worker._get_allowed_knobs()
        assert "PL_TARGET_DENSITY_PCT" in knobs
