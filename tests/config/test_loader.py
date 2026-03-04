"""Tests for agenticlane.config.loader -- Config Loader (P1.2).

Covers profile loading, merge chain ordering, deep merge logic,
and error handling for missing profiles and user configs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from agenticlane.config.loader import deep_merge, load_config, load_profile

# ---------------------------------------------------------------------------
# Profile loading
# ---------------------------------------------------------------------------


class TestLoadProfile:
    """Test that each built-in profile loads and contains expected keys."""

    def test_load_safe_profile(self) -> None:
        """safe.yaml loads with conservative values."""
        config = load_profile("safe")

        assert config["parallel"]["enabled"] is False
        assert config["parallel"]["max_parallel_branches"] == 1
        assert config["action_space"]["sdc"]["mode"] == "templated"
        assert config["action_space"]["permissions"]["tcl"] is False
        assert config["constraints"]["allow_relaxation"] is False
        assert config["constraints"]["locked_vars"] == ["CLOCK_PERIOD"]
        assert config["artifact_gc"]["enabled"] is True
        assert config["artifact_gc"]["policy"] == "keep_pass_and_tips"

    def test_load_balanced_profile(self) -> None:
        """balanced.yaml loads with moderate values -- parallel on, SDC restricted."""
        config = load_profile("balanced")

        assert config["parallel"]["enabled"] is True
        assert config["parallel"]["max_parallel_branches"] == 2
        assert config["action_space"]["sdc"]["mode"] == "restricted_freeform"
        assert config["action_space"]["permissions"]["tcl"] is False
        assert config["constraints"]["locked_vars"] == ["CLOCK_PERIOD"]

    def test_load_aggressive_profile(self) -> None:
        """aggressive.yaml loads with aggressive values -- parallel 3, Tcl enabled."""
        config = load_profile("aggressive")

        assert config["parallel"]["enabled"] is True
        assert config["parallel"]["max_parallel_branches"] == 3
        assert config["action_space"]["sdc"]["mode"] == "restricted_freeform"
        assert config["action_space"]["permissions"]["tcl"] is True
        assert config["action_space"]["tcl"]["enabled"] is True
        assert config["action_space"]["tcl"]["mode"] == "restricted_freeform"


class TestMissingProfile:
    """Test error handling for unknown / missing profiles."""

    def test_missing_profile_errors(self) -> None:
        """Unknown profile name raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="Profile not found"):
            load_profile("nonexistent_profile_xyz")

    def test_missing_profile_lists_available(self) -> None:
        """Error message includes available profile names."""
        with pytest.raises(FileNotFoundError, match="safe"):
            load_profile("nonexistent_profile_xyz")


# ---------------------------------------------------------------------------
# Deep merge
# ---------------------------------------------------------------------------


class TestDeepMerge:
    """Test the deep_merge utility."""

    def test_flat_override(self) -> None:
        """Flat keys in override replace base."""
        base = {"a": 1, "b": 2}
        override = {"b": 99}
        result = deep_merge(base, override)
        assert result == {"a": 1, "b": 99}

    def test_nested_merge(self) -> None:
        """Nested dicts are merged recursively."""
        base: dict[str, Any] = {"x": {"a": 1, "b": 2}}
        override: dict[str, Any] = {"x": {"b": 99, "c": 3}}
        result = deep_merge(base, override)
        assert result == {"x": {"a": 1, "b": 99, "c": 3}}

    def test_override_adds_new_keys(self) -> None:
        """Keys present only in override are added."""
        base: dict[str, Any] = {"a": 1}
        override: dict[str, Any] = {"b": 2}
        result = deep_merge(base, override)
        assert result == {"a": 1, "b": 2}

    def test_does_not_mutate_inputs(self) -> None:
        """Neither input dict is modified."""
        base: dict[str, Any] = {"x": {"a": 1}}
        override: dict[str, Any] = {"x": {"b": 2}}
        base_copy = {"x": {"a": 1}}
        override_copy = {"x": {"b": 2}}
        deep_merge(base, override)
        assert base == base_copy
        assert override == override_copy

    def test_override_replaces_non_dict_with_dict(self) -> None:
        """A non-dict value in base can be replaced by a dict in override."""
        base: dict[str, Any] = {"x": 42}
        override: dict[str, Any] = {"x": {"nested": True}}
        result = deep_merge(base, override)
        assert result == {"x": {"nested": True}}

    def test_override_replaces_dict_with_non_dict(self) -> None:
        """A dict value in base can be replaced by a scalar in override."""
        base: dict[str, Any] = {"x": {"nested": True}}
        override: dict[str, Any] = {"x": "flat_value"}
        result = deep_merge(base, override)
        assert result == {"x": "flat_value"}

    def test_empty_base(self) -> None:
        """Merging into an empty base returns the override."""
        result = deep_merge({}, {"a": 1})
        assert result == {"a": 1}

    def test_empty_override(self) -> None:
        """Merging with an empty override returns the base."""
        result = deep_merge({"a": 1}, {})
        assert result == {"a": 1}


# ---------------------------------------------------------------------------
# Full merge chain: load_config
# ---------------------------------------------------------------------------


class TestLoadConfig:
    """Test the full merge chain: profile -> user -> CLI."""

    def test_profile_only(self) -> None:
        """Loading with just a profile returns profile values."""
        config = load_config(profile="safe")
        assert config["parallel"]["enabled"] is False

    def test_user_config_overrides_profile(self, tmp_path: Path) -> None:
        """User config values override profile defaults."""
        user_yaml = tmp_path / "user.yaml"
        user_yaml.write_text(
            yaml.dump({"parallel": {"enabled": True, "max_parallel_branches": 5}})
        )
        config = load_config(profile="safe", user_config_path=user_yaml)
        assert config["parallel"]["enabled"] is True
        assert config["parallel"]["max_parallel_branches"] == 5
        # Non-overridden profile values preserved
        assert config["parallel"]["max_parallel_jobs"] == 1

    def test_cli_overrides_user(self, tmp_path: Path) -> None:
        """CLI overrides take precedence over user config."""
        user_yaml = tmp_path / "user.yaml"
        user_yaml.write_text(
            yaml.dump({"parallel": {"max_parallel_branches": 5}})
        )
        cli = {"parallel": {"max_parallel_branches": 10}}
        config = load_config(
            profile="safe", user_config_path=user_yaml, cli_overrides=cli
        )
        assert config["parallel"]["max_parallel_branches"] == 10

    def test_merge_chain_order(self, tmp_path: Path) -> None:
        """CLI overrides > user config > profile -- full chain verified."""
        user_yaml = tmp_path / "user.yaml"
        user_yaml.write_text(
            yaml.dump({
                "project": {"name": "user_project"},
                "llm": {"temperature": 0.5},
            })
        )
        cli = {"project": {"name": "cli_project"}}

        config = load_config(
            profile="safe", user_config_path=user_yaml, cli_overrides=cli
        )

        # CLI wins over user
        assert config["project"]["name"] == "cli_project"
        # User wins over profile
        assert config["llm"]["temperature"] == 0.5
        # Profile default preserved where not overridden
        assert config["llm"]["seed"] == 42

    def test_missing_user_config_uses_profile(self) -> None:
        """When user_config_path is None, profile values are used."""
        config = load_config(profile="safe", user_config_path=None)
        assert config["project"]["name"] == "unnamed"

    def test_nonexistent_user_config_path_uses_profile(self, tmp_path: Path) -> None:
        """A user_config_path pointing to a non-existent file is ignored."""
        missing = tmp_path / "does_not_exist.yaml"
        config = load_config(profile="safe", user_config_path=missing)
        assert config["project"]["name"] == "unnamed"

    def test_empty_user_config(self, tmp_path: Path) -> None:
        """An empty user config file does not corrupt the profile."""
        empty_yaml = tmp_path / "empty.yaml"
        empty_yaml.write_text("")
        config = load_config(profile="safe", user_config_path=empty_yaml)
        assert config["parallel"]["enabled"] is False

    def test_cli_overrides_only(self) -> None:
        """CLI overrides work without a user config."""
        cli = {"project": {"name": "from_cli"}}
        config = load_config(profile="safe", cli_overrides=cli)
        assert config["project"]["name"] == "from_cli"
