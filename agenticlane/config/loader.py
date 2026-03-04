"""Configuration loader with merge chain: profile -> user -> CLI -> env.

This module provides the primary entry point for loading AgenticLane
configuration.  It implements a four-level merge chain where each
successive layer overrides the previous one:

1. **Profile defaults** -- conservative YAML shipped with the package
   (``safe``, ``balanced``, ``aggressive``).
2. **User config** -- a project-local YAML file provided by the user.
3. **CLI overrides** -- key/value overrides passed from the command line.
4. *(Future)* **Environment variables** -- ``AGENTICLANE_*`` env vars.

The loader returns a plain ``dict[str, Any]`` that can be passed to
``AgenticLaneConfig(**config_dict)`` for Pydantic validation once the
models module is integrated.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge two dicts. *override* takes precedence on conflicts.

    - If both values for a key are dicts, merge recursively.
    - Otherwise the *override* value wins.

    Args:
        base: The base dictionary.
        override: The dictionary whose values take precedence.

    Returns:
        A new merged dictionary (neither input is mutated).
    """
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


# ---------------------------------------------------------------------------
# Profile loading
# ---------------------------------------------------------------------------

_PROFILES_DIR = Path(__file__).parent / "defaults"


def load_profile(profile_name: str) -> dict[str, Any]:
    """Load a built-in default profile YAML.

    Args:
        profile_name: One of ``"safe"``, ``"balanced"``, ``"aggressive"``.

    Returns:
        The profile configuration as a plain dict.

    Raises:
        FileNotFoundError: If the named profile does not exist.
    """
    profile_path = _PROFILES_DIR / f"{profile_name}.yaml"
    if not profile_path.exists():
        available = sorted(
            p.stem for p in _PROFILES_DIR.glob("*.yaml")
        )
        raise FileNotFoundError(
            f"Profile not found: '{profile_name}'. "
            f"Available profiles: {available}"
        )
    with open(profile_path) as f:
        return yaml.safe_load(f) or {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_config(
    profile: str = "safe",
    user_config_path: Optional[Path] = None,
    cli_overrides: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Load config with merge chain: profile -> user -> CLI.

    The returned dict is suitable for passing directly to
    ``AgenticLaneConfig(**result)`` once config models are available.

    Args:
        profile: Name of the built-in profile to start from
            (default ``"safe"``).
        user_config_path: Optional path to a user-provided YAML config
            file.  If the path does not exist it is silently ignored.
        cli_overrides: Optional dict of CLI-provided overrides that take
            highest precedence.

    Returns:
        A fully-merged configuration dict.

    Raises:
        FileNotFoundError: If the requested profile does not exist.
    """
    # 1. Load profile defaults
    config = load_profile(profile)

    # 2. Merge user config (if provided and exists)
    if user_config_path and user_config_path.exists():
        with open(user_config_path) as f:
            user_config = yaml.safe_load(f) or {}
        config = deep_merge(config, user_config)

    # 3. Merge CLI overrides
    if cli_overrides:
        config = deep_merge(config, cli_overrides)

    return config
