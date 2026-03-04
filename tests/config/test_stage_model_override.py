"""Tests for per-stage LLM model override configuration and resolution."""

from __future__ import annotations

from agenticlane.config.models import (
    LLMModelsConfig,
    StageModelOverride,
)


class TestStageModelOverride:
    def test_default_empty(self) -> None:
        """StageModelOverride defaults to None/None."""
        override = StageModelOverride()
        assert override.worker is None
        assert override.judge is None

    def test_worker_only(self) -> None:
        """Can set worker override without judge."""
        override = StageModelOverride(worker="gemini/gemini-2.5-pro")
        assert override.worker == "gemini/gemini-2.5-pro"
        assert override.judge is None

    def test_judge_only(self) -> None:
        """Can set judge override without worker."""
        override = StageModelOverride(judge=["model_a", "model_b"])
        assert override.worker is None
        assert override.judge == ["model_a", "model_b"]

    def test_both(self) -> None:
        """Can set both worker and judge overrides."""
        override = StageModelOverride(
            worker="local_model",
            judge=["judge_a", "judge_b"],
        )
        assert override.worker == "local_model"
        assert override.judge == ["judge_a", "judge_b"]


class TestLLMModelsConfigOverrides:
    def test_default_no_overrides(self) -> None:
        """LLMModelsConfig should have empty stage_overrides by default."""
        config = LLMModelsConfig()
        assert config.stage_overrides == {}

    def test_with_overrides(self) -> None:
        """LLMModelsConfig should accept stage_overrides dict."""
        config = LLMModelsConfig(
            worker="default_worker",
            judge=["default_judge"],
            stage_overrides={
                "ROUTE_DETAILED": StageModelOverride(worker="gemini/gemini-2.5-pro"),
                "SIGNOFF": StageModelOverride(
                    worker="gemini/gemini-2.5-pro",
                    judge=["gemini/gemini-2.5-pro", "qwen3-32b"],
                ),
            },
        )
        assert "ROUTE_DETAILED" in config.stage_overrides
        assert config.stage_overrides["ROUTE_DETAILED"].worker == "gemini/gemini-2.5-pro"
        assert config.stage_overrides["SIGNOFF"].judge is not None
        assert len(config.stage_overrides["SIGNOFF"].judge) == 2

    def test_serialization_round_trip(self) -> None:
        """Config with overrides should survive JSON round-trip."""
        config = LLMModelsConfig(
            stage_overrides={
                "SYNTH": StageModelOverride(worker="local_model"),
            },
        )
        dumped = config.model_dump()
        restored = LLMModelsConfig(**dumped)
        assert restored.stage_overrides["SYNTH"].worker == "local_model"


class TestModelResolution:
    """Test resolve_model_for_stage and resolve_judge_models_for_stage on LLMProvider."""

    def _make_provider(self, overrides: dict[str, StageModelOverride] | None = None):
        """Create a MockLLMProvider with given overrides."""
        from agenticlane.agents.mock_llm import MockLLMProvider
        from agenticlane.config.models import LLMConfig, LLMModelsConfig

        models_config = LLMModelsConfig(
            worker="default_worker",
            judge=["judge_a", "judge_b", "judge_c"],
            stage_overrides=overrides or {},
        )
        llm_config = LLMConfig(models=models_config)
        return MockLLMProvider(llm_config)

    def test_resolve_worker_no_override(self) -> None:
        """Without overrides, should return global default worker."""
        provider = self._make_provider()
        assert provider.resolve_model_for_stage("worker", "SYNTH") == "default_worker"

    def test_resolve_worker_with_override(self) -> None:
        """With worker override, should return stage-specific model."""
        provider = self._make_provider({
            "SIGNOFF": StageModelOverride(worker="gemini/gemini-2.5-pro"),
        })
        assert provider.resolve_model_for_stage("worker", "SIGNOFF") == "gemini/gemini-2.5-pro"
        # Other stages still use default
        assert provider.resolve_model_for_stage("worker", "SYNTH") == "default_worker"

    def test_resolve_judge_no_override(self) -> None:
        """Without overrides, resolve_judge returns first global judge."""
        provider = self._make_provider()
        assert provider.resolve_model_for_stage("judge", "SYNTH") == "judge_a"

    def test_resolve_judge_with_override(self) -> None:
        """With judge override, should return first override judge."""
        provider = self._make_provider({
            "CTS": StageModelOverride(judge=["special_judge"]),
        })
        assert provider.resolve_model_for_stage("judge", "CTS") == "special_judge"

    def test_resolve_judge_models_no_override(self) -> None:
        """resolve_judge_models_for_stage returns global list without override."""
        provider = self._make_provider()
        judges = provider.resolve_judge_models_for_stage("SYNTH")
        assert judges == ["judge_a", "judge_b", "judge_c"]

    def test_resolve_judge_models_with_override(self) -> None:
        """resolve_judge_models_for_stage returns override list when present."""
        provider = self._make_provider({
            "SIGNOFF": StageModelOverride(judge=["g_pro", "qwen3"]),
        })
        judges = provider.resolve_judge_models_for_stage("SIGNOFF")
        assert judges == ["g_pro", "qwen3"]
        # Other stages still use default
        assert provider.resolve_judge_models_for_stage("SYNTH") == ["judge_a", "judge_b", "judge_c"]

    def test_worker_override_doesnt_affect_judge(self) -> None:
        """Worker-only override should not change judge resolution."""
        provider = self._make_provider({
            "PDN": StageModelOverride(worker="special_worker"),
        })
        assert provider.resolve_model_for_stage("worker", "PDN") == "special_worker"
        assert provider.resolve_model_for_stage("judge", "PDN") == "judge_a"  # global default
        assert provider.resolve_judge_models_for_stage("PDN") == ["judge_a", "judge_b", "judge_c"]

    def test_judge_override_doesnt_affect_worker(self) -> None:
        """Judge-only override should not change worker resolution."""
        provider = self._make_provider({
            "PDN": StageModelOverride(judge=["special_judge"]),
        })
        assert provider.resolve_model_for_stage("worker", "PDN") == "default_worker"
