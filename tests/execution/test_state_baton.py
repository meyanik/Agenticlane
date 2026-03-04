"""Tests for the state baton (state_handoff + state_rebase)."""

from __future__ import annotations

import json
from pathlib import Path

from agenticlane.execution.state_handoff import (
    detokenize_path,
    load_state,
    save_state,
    tokenize_path,
    tokenize_state,
    write_rebase_map,
)
from agenticlane.execution.state_rebase import rebase_paths

# ------------------------------------------------------------------
# tokenize / detokenize single paths
# ------------------------------------------------------------------


class TestTokenizePath:
    """Verify single-path tokenization."""

    def test_tokenize_absolute_paths(self) -> None:
        """An absolute path under run_root is tokenized correctly."""
        run_root = "/tmp/runs/my_run"
        result = tokenize_path("/tmp/runs/my_run/stages/synth/out.json", run_root)
        assert result == "{{RUN_ROOT}}/stages/synth/out.json"

    def test_tokenize_path_outside_root_unchanged(self) -> None:
        """A path outside run_root is returned unchanged."""
        result = tokenize_path("/other/path/file.txt", "/tmp/runs/my_run")
        assert result == "/other/path/file.txt"

    def test_tokenize_run_root_itself(self) -> None:
        """Tokenizing the run_root itself yields ``{{RUN_ROOT}}/.``."""
        result = tokenize_path("/tmp/runs", "/tmp/runs")
        assert result == "{{RUN_ROOT}}/."


class TestDetokenizePath:
    """Verify single-path detokenization."""

    def test_detokenize_restores_paths(self) -> None:
        """Round-trip: tokenize then detokenize returns the original
        (modulo normalization)."""
        run_root = "/tmp/runs/my_run"
        original = "/tmp/runs/my_run/stages/synth/out.json"

        tokenized = tokenize_path(original, run_root)
        restored = detokenize_path(tokenized, run_root)

        assert restored == original

    def test_detokenize_no_token(self) -> None:
        """A string without a token is returned unchanged."""
        result = detokenize_path("just_a_name.json", "/tmp/runs")
        assert result == "just_a_name.json"


# ------------------------------------------------------------------
# Recursive state tokenization
# ------------------------------------------------------------------


class TestTokenizeState:
    """Verify recursive dict tokenization."""

    def test_tokenize_state_recursive(self) -> None:
        """Handles nested dicts and lists with path-like values."""
        run_root = "/data/run"
        state = {
            "name": "synth",
            "output": "/data/run/out/result.json",
            "nested": {
                "logs": ["/data/run/logs/a.log", "/data/run/logs/b.log"],
                "count": 42,
            },
            "external": "/other/place/file.txt",
        }

        result = tokenize_state(state, run_root)

        # Path-like values under run_root are tokenized.
        assert result["output"] == "{{RUN_ROOT}}/out/result.json"
        assert result["nested"]["logs"][0] == "{{RUN_ROOT}}/logs/a.log"
        assert result["nested"]["logs"][1] == "{{RUN_ROOT}}/logs/b.log"

        # Non-path values are unchanged.
        assert result["name"] == "synth"
        assert result["nested"]["count"] == 42

        # Path outside run_root stays as-is.
        assert result["external"] == "/other/place/file.txt"


# ------------------------------------------------------------------
# save / load round-trip
# ------------------------------------------------------------------


class TestSaveAndLoad:
    """Verify save then load produces the same data."""

    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        """Write tokenized state, read it back, and compare."""
        from typing import Any

        run_root = str(tmp_path / "run_root")
        state: dict[str, Any] = {
            "design": "spm",
            "state_out": f"{run_root}/stages/synth/state_out.json",
            "metrics": {
                "timing_rpt": f"{run_root}/reports/timing.rpt",
                "wns": -0.5,
            },
        }

        state_path = tmp_path / "state.json"
        rebase_map = save_state(state, state_path, run_root)

        # File should exist and contain tokenized paths.
        assert state_path.exists()
        raw = json.loads(state_path.read_text())
        assert "{{RUN_ROOT}}" in raw["state_out"]

        # Rebase map should record the two transformed paths.
        assert len(rebase_map) == 2

        # Loading restores the original absolute paths.
        loaded = load_state(state_path, run_root)
        assert loaded["state_out"] == state["state_out"]
        assert loaded["metrics"]["timing_rpt"] == state["metrics"]["timing_rpt"]
        assert loaded["metrics"]["wns"] == -0.5
        assert loaded["design"] == "spm"


class TestWriteRebaseMap:
    """Verify rebase map persistence."""

    def test_write_rebase_map(self, tmp_path: Path) -> None:
        rmap = {"/old/path/a": "{{RUN_ROOT}}/a", "/old/path/b": "{{RUN_ROOT}}/b"}
        out = tmp_path / "rebase_map.json"
        write_rebase_map(rmap, out)

        loaded = json.loads(out.read_text())
        assert loaded == rmap


# ------------------------------------------------------------------
# state_rebase
# ------------------------------------------------------------------


class TestRebasePaths:
    """Verify path rebasing from old root to new root."""

    def test_rebase_paths_to_new_root(self) -> None:
        """Paths under old_root are rewritten to new_root."""
        state = {
            "out": "/old_root/stages/synth/result.json",
            "nested": {
                "log": "/old_root/logs/run.log",
            },
            "external": "/other/file.txt",
            "count": 7,
        }

        rebased, rmap = rebase_paths(state, "/old_root", "/new_root")

        assert rebased["out"] == "/new_root/stages/synth/result.json"
        assert rebased["nested"]["log"] == "/new_root/logs/run.log"
        assert rebased["external"] == "/other/file.txt"
        assert rebased["count"] == 7

    def test_rebase_map_logged(self) -> None:
        """The rebase map contains all transformed paths."""
        state = {
            "a": "/old/x/one.json",
            "b": "/old/x/two.json",
            "c": "not_a_path",
        }

        _, rmap = rebase_paths(state, "/old/x", "/new/y")

        assert len(rmap) == 2
        assert rmap["/old/x/one.json"] == "/new/y/one.json"
        assert rmap["/old/x/two.json"] == "/new/y/two.json"
