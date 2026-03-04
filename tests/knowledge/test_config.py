"""Tests for KnowledgeConfig model and integration with AgenticLaneConfig."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from agenticlane.config.models import AgenticLaneConfig, KnowledgeConfig


class TestKnowledgeConfigDefaults:
    """KnowledgeConfig default values."""

    def test_defaults(self) -> None:
        cfg = KnowledgeConfig()
        assert cfg.enabled is False
        assert cfg.db_path is None
        assert cfg.embedding_model == "all-MiniLM-L6-v2"
        assert cfg.collection_name == "chip_design_knowledge"
        assert cfg.top_k == 5
        assert cfg.score_threshold == 0.35

    def test_enabled_override(self) -> None:
        cfg = KnowledgeConfig(enabled=True)
        assert cfg.enabled is True

    def test_custom_db_path(self) -> None:
        cfg = KnowledgeConfig(db_path=Path("/tmp/my_db"))
        assert cfg.db_path == Path("/tmp/my_db")

    def test_custom_top_k(self) -> None:
        cfg = KnowledgeConfig(top_k=10)
        assert cfg.top_k == 10


class TestKnowledgeConfigValidation:
    """Boundary validation on KnowledgeConfig fields."""

    def test_top_k_min(self) -> None:
        with pytest.raises(ValidationError):
            KnowledgeConfig(top_k=0)

    def test_top_k_max(self) -> None:
        with pytest.raises(ValidationError):
            KnowledgeConfig(top_k=21)

    def test_score_threshold_min(self) -> None:
        cfg = KnowledgeConfig(score_threshold=0.0)
        assert cfg.score_threshold == 0.0

    def test_score_threshold_max(self) -> None:
        cfg = KnowledgeConfig(score_threshold=1.0)
        assert cfg.score_threshold == 1.0

    def test_score_threshold_below_min(self) -> None:
        with pytest.raises(ValidationError):
            KnowledgeConfig(score_threshold=-0.1)

    def test_score_threshold_above_max(self) -> None:
        with pytest.raises(ValidationError):
            KnowledgeConfig(score_threshold=1.1)


class TestAgenticLaneConfigWithKnowledge:
    """KnowledgeConfig wired into root config."""

    def test_default_has_knowledge(self) -> None:
        cfg = AgenticLaneConfig()
        assert hasattr(cfg, "knowledge")
        assert cfg.knowledge.enabled is False

    def test_json_roundtrip(self) -> None:
        cfg = AgenticLaneConfig(
            knowledge=KnowledgeConfig(enabled=True, top_k=8)
        )
        data = cfg.model_dump(mode="json")
        restored = AgenticLaneConfig.model_validate(data)
        assert restored.knowledge.enabled is True
        assert restored.knowledge.top_k == 8

    def test_yaml_roundtrip(self) -> None:
        cfg = AgenticLaneConfig(
            knowledge=KnowledgeConfig(
                enabled=True,
                db_path=Path("./my_db"),
                top_k=3,
                score_threshold=0.5,
            )
        )
        yaml_str = yaml.dump(cfg.model_dump(mode="json"))
        data = yaml.safe_load(yaml_str)
        restored = AgenticLaneConfig.model_validate(data)
        assert restored.knowledge.enabled is True
        assert restored.knowledge.top_k == 3
        assert restored.knowledge.score_threshold == 0.5
