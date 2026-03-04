"""Tests for zero-shot initialization (P5.4)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agenticlane.orchestration.zero_shot import ZeroShotInitializer
from agenticlane.schemas.patch import Patch

# ---------------------------------------------------------------------------
# Mock LLM providers
# ---------------------------------------------------------------------------


class _MockLLMProvider:
    """Mock LLM that returns a fixed patch."""

    async def generate(
        self, prompt: str, response_model: Any, **kwargs: Any
    ) -> Patch:
        return Patch(
            patch_id="llm_init",
            stage="FLOORPLAN",
            types=["config_vars"],
            config_vars={"FP_CORE_UTIL": 42},
        )


class _FailingLLMProvider:
    """Mock LLM that always fails."""

    async def generate(
        self, prompt: str, response_model: Any, **kwargs: Any
    ) -> Patch:
        raise RuntimeError("LLM unavailable")


# ---------------------------------------------------------------------------
# Core initializer tests
# ---------------------------------------------------------------------------


class TestZeroShotInitializer:
    async def test_intent_profile_produces_patch(self) -> None:
        initializer = ZeroShotInitializer()
        intent = {"optimize_for": "timing"}
        patch = await initializer.generate_init_patch(intent)
        assert isinstance(patch, Patch)
        assert patch.patch_id == "global_init_patch"
        assert patch.config_vars.get("FP_CORE_UTIL") == 35  # timing profile

    async def test_balanced_profile(self) -> None:
        initializer = ZeroShotInitializer()
        intent = {"optimize_for": "balanced"}
        patch = await initializer.generate_init_patch(intent)
        assert patch.config_vars.get("FP_CORE_UTIL") == 50

    async def test_area_profile(self) -> None:
        initializer = ZeroShotInitializer()
        intent = {"optimize_for": "area"}
        patch = await initializer.generate_init_patch(intent)
        assert patch.config_vars.get("FP_CORE_UTIL") == 65

    async def test_power_profile(self) -> None:
        initializer = ZeroShotInitializer()
        intent = {"optimize_for": "power"}
        patch = await initializer.generate_init_patch(intent)
        assert patch.config_vars.get("FP_CORE_UTIL") == 45

    async def test_config_overrides_from_intent(self) -> None:
        initializer = ZeroShotInitializer()
        intent = {
            "optimize_for": "balanced",
            "config_overrides": {"FP_CORE_UTIL": 55, "CUSTOM_VAR": "test"},
        }
        patch = await initializer.generate_init_patch(intent)
        assert patch.config_vars["FP_CORE_UTIL"] == 55  # override wins
        assert patch.config_vars["CUSTOM_VAR"] == "test"

    async def test_default_config_vars_applied(self) -> None:
        initializer = ZeroShotInitializer(default_config_vars={"MY_DEFAULT": 99})
        intent = {"optimize_for": "balanced"}
        patch = await initializer.generate_init_patch(intent)
        assert patch.config_vars["MY_DEFAULT"] == 99

    async def test_init_patch_valid_schema(self) -> None:
        initializer = ZeroShotInitializer()
        intent = {"optimize_for": "timing"}
        patch = await initializer.generate_init_patch(intent)
        # Should be serializable and valid
        data = patch.model_dump(mode="json")
        reloaded = Patch(**data)
        assert reloaded.patch_id == patch.patch_id

    async def test_master_produces_init_via_llm(self) -> None:
        llm = _MockLLMProvider()
        initializer = ZeroShotInitializer(llm_provider=llm)
        intent = {"optimize_for": "timing"}
        patch = await initializer.generate_init_patch(intent)
        assert patch.patch_id == "llm_init"
        assert patch.config_vars.get("FP_CORE_UTIL") == 42

    async def test_llm_failure_falls_back(self) -> None:
        llm = _FailingLLMProvider()
        initializer = ZeroShotInitializer(llm_provider=llm)
        intent = {"optimize_for": "area"}
        patch = await initializer.generate_init_patch(intent)
        # Should fall back to default generation
        assert patch.patch_id == "global_init_patch"
        assert patch.config_vars.get("FP_CORE_UTIL") == 65


# ---------------------------------------------------------------------------
# Persistence tests
# ---------------------------------------------------------------------------


class TestInitPatchPersistence:
    def test_write_and_load_roundtrip(self, tmp_path: Path) -> None:
        patch = Patch(
            patch_id="global_init_patch",
            stage="FLOORPLAN",
            types=["config_vars"],
            config_vars={"FP_CORE_UTIL": 50},
        )
        path = ZeroShotInitializer.write_init_patch(patch, tmp_path)
        assert path.exists()
        assert path.name == "global_init_patch.json"

        loaded = ZeroShotInitializer.load_init_patch(path)
        assert loaded.patch_id == "global_init_patch"
        assert loaded.config_vars == {"FP_CORE_UTIL": 50}

    def test_write_creates_directory(self, tmp_path: Path) -> None:
        patch = Patch(
            patch_id="init",
            stage="FLOORPLAN",
        )
        nested = tmp_path / "a" / "b"
        path = ZeroShotInitializer.write_init_patch(patch, nested)
        assert path.exists()

    async def test_init_patch_applied_to_all_branches(self, tmp_path: Path) -> None:
        """Verify the same init patch can be applied to multiple branches."""
        initializer = ZeroShotInitializer()
        intent = {"optimize_for": "balanced"}
        patch = await initializer.generate_init_patch(intent)

        # Simulate applying to 3 branches
        branch_patches = []
        for i in range(3):
            branch_dir = tmp_path / f"B{i}"
            path = ZeroShotInitializer.write_init_patch(patch, branch_dir)
            loaded = ZeroShotInitializer.load_init_patch(path)
            branch_patches.append(loaded)

        # All branches should have the same init patch
        for bp in branch_patches:
            assert bp.config_vars == patch.config_vars
            assert bp.patch_id == patch.patch_id
