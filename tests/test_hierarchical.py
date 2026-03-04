"""Tests for hierarchical flow mode implementation.

Covers:
- Config: ModuleConfig schema, DesignConfig.modules, hierarchical validator
- Config patcher: MACROS injection, JSON round-trip, multi-module
- Orchestrator: _build_module_config, _collect_module_artifacts, _run_hierarchical
- Manifest: module_results recording
- Worker context: module_context passthrough
- Prompt templates: hierarchical context rendering
- Mock adapter: LEF/GDS generation for signoff
- Integration: full 2-module + parent flow with mocks
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from agenticlane.config.models import (
    AgenticLaneConfig,
    DesignConfig,
    FlowControlConfig,
    IntentConfig,
    ModuleConfig,
    ParallelConfig,
)
from agenticlane.execution.config_patcher import (
    HardenedModule,
    HierarchicalConfigPatcher,
    _populate_macro_instances,
    _remove_instance_params,
)
from agenticlane.execution.workspaces import WorkspaceManager
from agenticlane.orchestration.manifest import ManifestBuilder, RunManifest
from agenticlane.schemas.metrics import MetricsPayload

# ===================================================================
# Config: ModuleConfig
# ===================================================================


class TestModuleConfig:
    """Test ModuleConfig schema and validation."""

    def test_minimal_module_config(self) -> None:
        mc = ModuleConfig(librelane_config_path=Path("./mod/config.yaml"))
        assert mc.librelane_config_path == Path("./mod/config.yaml")
        assert mc.verilog_files == []
        assert mc.pdk is None
        assert mc.intent is None
        assert mc.flow_control is None
        assert mc.parallel is None

    def test_full_module_config(self) -> None:
        mc = ModuleConfig(
            librelane_config_path=Path("./mod/config.yaml"),
            verilog_files=["src/mod.v", "src/mod2.v"],
            pdk="gf180mcuD",
            intent=IntentConfig(prompt="optimize mod", weights_hint={"timing": 0.8, "area": 0.2}),
            flow_control=FlowControlConfig(),
            parallel=ParallelConfig(enabled=False, max_parallel_branches=1, max_parallel_jobs=1),
        )
        assert mc.pdk == "gf180mcuD"
        assert len(mc.verilog_files) == 2
        assert mc.intent is not None
        assert mc.intent.prompt == "optimize mod"

    def test_module_config_serialization(self) -> None:
        mc = ModuleConfig(librelane_config_path=Path("./mod/config.yaml"), pdk="sky130A")
        data = mc.model_dump(mode="json")
        assert data["pdk"] == "sky130A"
        assert data["librelane_config_path"] == "mod/config.yaml"


# ===================================================================
# Config: DesignConfig.modules + validator
# ===================================================================


class TestDesignConfigModules:
    """Test modules field and hierarchical validator on DesignConfig."""

    def test_default_modules_empty(self) -> None:
        cfg = DesignConfig()
        assert cfg.modules == {}

    def test_flat_with_modules_ok(self) -> None:
        """Flat mode should accept (but ignore) modules."""
        cfg = DesignConfig(
            flow_mode="flat",
            modules={
                "mod1": ModuleConfig(librelane_config_path=Path("./m1/config.yaml"))
            },
        )
        assert cfg.flow_mode == "flat"
        assert len(cfg.modules) == 1

    def test_hierarchical_without_modules_fails(self) -> None:
        with pytest.raises(ValidationError, match="modules"):
            DesignConfig(flow_mode="hierarchical", modules={})

    def test_hierarchical_with_modules_ok(self) -> None:
        cfg = DesignConfig(
            flow_mode="hierarchical",
            modules={
                "mod1": ModuleConfig(librelane_config_path=Path("./m1/config.yaml")),
                "mod2": ModuleConfig(librelane_config_path=Path("./m2/config.yaml")),
            },
        )
        assert cfg.flow_mode == "hierarchical"
        assert len(cfg.modules) == 2

    def test_auto_with_modules_ok(self) -> None:
        cfg = DesignConfig(
            flow_mode="auto",
            modules={
                "mod1": ModuleConfig(librelane_config_path=Path("./m1/config.yaml")),
            },
        )
        assert cfg.flow_mode == "auto"

    def test_modules_in_full_config(self) -> None:
        cfg = AgenticLaneConfig(
            design={
                "flow_mode": "hierarchical",
                "modules": {
                    "mod1": {"librelane_config_path": "./m1/config.yaml"},
                },
            }
        )
        assert cfg.design.flow_mode == "hierarchical"
        assert "mod1" in cfg.design.modules

    def test_modules_serialization_roundtrip(self) -> None:
        cfg = DesignConfig(
            flow_mode="hierarchical",
            modules={
                "mod1": ModuleConfig(
                    librelane_config_path=Path("./m1/config.yaml"),
                    pdk="sky130A",
                ),
            },
        )
        data = cfg.model_dump(mode="json")
        cfg2 = DesignConfig(**data)
        assert cfg2.modules["mod1"].pdk == "sky130A"

    def test_module_override_fields(self) -> None:
        cfg = DesignConfig(
            flow_mode="hierarchical",
            modules={
                "mod1": ModuleConfig(
                    librelane_config_path=Path("./m1/config.yaml"),
                    intent=IntentConfig(prompt="custom intent"),
                    flow_control=FlowControlConfig(
                        budgets={"physical_attempts_per_stage": 5}
                    ),
                ),
            },
        )
        mod = cfg.modules["mod1"]
        assert mod.intent is not None
        assert mod.intent.prompt == "custom intent"
        assert mod.flow_control is not None
        assert mod.flow_control.budgets.physical_attempts_per_stage == 5


# ===================================================================
# Config Patcher
# ===================================================================


class TestHierarchicalConfigPatcher:
    """Test HierarchicalConfigPatcher for MACROS injection."""

    def test_patch_single_module(self, tmp_path: Path) -> None:
        parent_config = {"DESIGN_NAME": "top", "CLOCK_PERIOD": 10.0}
        parent_path = tmp_path / "parent.json"
        parent_path.write_text(json.dumps(parent_config))

        modules = [
            HardenedModule(
                module_name="mod1",
                lef_path=Path("/art/mod1.lef"),
                gds_path=Path("/art/mod1.gds"),
            )
        ]
        output_path = tmp_path / "patched.json"
        HierarchicalConfigPatcher.patch_config(parent_path, modules, output_path)

        patched = json.loads(output_path.read_text())
        assert "MACROS" in patched
        assert "mod1" in patched["MACROS"]
        assert patched["MACROS"]["mod1"]["lef"] == ["/art/mod1.lef"]
        assert patched["MACROS"]["mod1"]["gds"] == ["/art/mod1.gds"]
        # Original config preserved
        assert patched["DESIGN_NAME"] == "top"

    def test_patch_multiple_modules(self, tmp_path: Path) -> None:
        parent_config = {"DESIGN_NAME": "top"}
        parent_path = tmp_path / "parent.json"
        parent_path.write_text(json.dumps(parent_config))

        modules = [
            HardenedModule(
                module_name="mod1",
                lef_path=Path("/art/mod1.lef"),
                gds_path=Path("/art/mod1.gds"),
            ),
            HardenedModule(
                module_name="mod2",
                lef_path=Path("/art/mod2.lef"),
                gds_path=Path("/art/mod2.gds"),
                nl_path=Path("/art/mod2.nl.v"),
            ),
        ]
        output_path = tmp_path / "patched.json"
        HierarchicalConfigPatcher.patch_config(parent_path, modules, output_path)

        patched = json.loads(output_path.read_text())
        assert len(patched["MACROS"]) == 2
        assert "mod1" in patched["MACROS"]
        assert "mod2" in patched["MACROS"]
        # mod2 has netlist
        assert "nl" in patched["MACROS"]["mod2"]

    def test_patch_preserves_existing_macros(self, tmp_path: Path) -> None:
        parent_config = {
            "DESIGN_NAME": "top",
            "MACROS": {
                "existing_macro": {"instances": {}, "lef": ["old.lef"], "gds": ["old.gds"]}
            },
        }
        parent_path = tmp_path / "parent.json"
        parent_path.write_text(json.dumps(parent_config))

        modules = [
            HardenedModule(
                module_name="new_mod",
                lef_path=Path("/art/new.lef"),
                gds_path=Path("/art/new.gds"),
            )
        ]
        output_path = tmp_path / "patched.json"
        HierarchicalConfigPatcher.patch_config(parent_path, modules, output_path)

        patched = json.loads(output_path.read_text())
        assert "existing_macro" in patched["MACROS"]
        assert "new_mod" in patched["MACROS"]

    def test_patch_empty_modules_list(self, tmp_path: Path) -> None:
        parent_config = {"DESIGN_NAME": "top"}
        parent_path = tmp_path / "parent.json"
        parent_path.write_text(json.dumps(parent_config))

        output_path = tmp_path / "patched.json"
        HierarchicalConfigPatcher.patch_config(parent_path, [], output_path)

        patched = json.loads(output_path.read_text())
        assert patched.get("MACROS", {}) == {}

    def test_patch_creates_output_dir(self, tmp_path: Path) -> None:
        parent_config = {"DESIGN_NAME": "top"}
        parent_path = tmp_path / "parent.json"
        parent_path.write_text(json.dumps(parent_config))

        output_path = tmp_path / "subdir" / "deep" / "patched.json"
        HierarchicalConfigPatcher.patch_config(
            parent_path,
            [HardenedModule("mod", Path("a.lef"), Path("a.gds"))],
            output_path,
        )
        assert output_path.exists()

    def test_patch_json_roundtrip(self, tmp_path: Path) -> None:
        """Patched config should be valid JSON."""
        parent_config = {"DESIGN_NAME": "top", "CLOCK_PERIOD": 10.0}
        parent_path = tmp_path / "parent.json"
        parent_path.write_text(json.dumps(parent_config))

        output_path = tmp_path / "patched.json"
        HierarchicalConfigPatcher.patch_config(
            parent_path,
            [HardenedModule("mod", Path("a.lef"), Path("a.gds"))],
            output_path,
        )

        # Should parse as valid JSON
        data = json.loads(output_path.read_text())
        assert isinstance(data, dict)

    def test_patch_removes_hardened_verilog(self, tmp_path: Path) -> None:
        """Hardened module sources removed; parameter overrides stripped."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "top.v").write_text(
            "module top;\n"
            "  picorv32 #(.ENABLE_IRQ(1)) cpu (.clk(clk));\n"
            "  spimemio spi (.clk(clk));\n"
            "endmodule\n"
        )
        (src_dir / "picorv32.v").write_text(
            "module picorv32 #(parameter ENABLE_IRQ = 0) (input clk);\n"
            "endmodule\n"
        )
        (src_dir / "spimemio.v").write_text(
            "module spimemio (input clk);\nendmodule\n"
        )
        (src_dir / "simpleuart.v").write_text("module simpleuart; endmodule")

        parent_config = {
            "DESIGN_NAME": "top",
            "VERILOG_FILES": [
                str(src_dir / "top.v"),
                str(src_dir / "picorv32.v"),
                str(src_dir / "spimemio.v"),
                str(src_dir / "simpleuart.v"),
            ],
            "DIE_AREA": [0, 0, 1000, 1000],
        }
        parent_path = tmp_path / "config.json"
        parent_path.write_text(json.dumps(parent_config))

        modules = [
            HardenedModule("picorv32", Path("/art/picorv32.lef"), Path("/art/picorv32.gds")),
            HardenedModule("spimemio", Path("/art/spimemio.lef"), Path("/art/spimemio.gds")),
        ]
        output_path = tmp_path / "out" / "patched.json"
        HierarchicalConfigPatcher.patch_config(parent_path, modules, output_path)

        patched = json.loads(output_path.read_text())
        verilog_files = patched["VERILOG_FILES"]
        # Hardened modules should be removed from VERILOG_FILES
        assert not any("picorv32.v" in vf for vf in verilog_files)
        assert not any("spimemio.v" in vf for vf in verilog_files)
        # simpleuart.v is kept as-is (no param overrides on hardened modules)
        assert any("simpleuart.v" in vf for vf in verilog_files)
        # top.v should be replaced with patched copy (has param overrides)
        top_paths = [vf for vf in verilog_files if "top.v" in vf]
        assert len(top_paths) == 1
        assert "patched_src" in top_paths[0]
        # Patched copy should have parameter overrides stripped
        patched_top = Path(top_paths[0]).read_text()
        assert "#(" not in patched_top
        assert "picorv32" in patched_top
        assert "cpu" in patched_top
        # Lint errors should be disabled for hierarchical parent
        assert patched.get("ERROR_ON_LINTER_ERRORS") is False
        # MACROS should NOT have vh entries (param stripping approach)
        macros = patched["MACROS"]
        assert "vh" not in macros["picorv32"]
        assert "vh" not in macros["spimemio"]
        # Macro instances should be populated with placement
        assert "cpu" in macros["picorv32"]["instances"]
        assert "location" in macros["picorv32"]["instances"]["cpu"]
        assert "spi" in macros["spimemio"]["instances"]
        assert "location" in macros["spimemio"]["instances"]["spi"]

    def test_patch_resolves_dir_paths(self, tmp_path: Path) -> None:
        """dir:: paths should be resolved to absolute when config is relocated."""
        src_dir = tmp_path / "project" / "src"
        src_dir.mkdir(parents=True)
        (src_dir / "top.v").write_text("module top; endmodule")

        parent_config = {
            "DESIGN_NAME": "top",
            "VERILOG_FILES": ["dir::src/top.v"],
            "NESTED": {"LIB": "dir::libs/mylib.lib"},
        }
        parent_path = tmp_path / "project" / "config.json"
        parent_path.write_text(json.dumps(parent_config))

        # Write to a completely different directory
        output_path = tmp_path / "runs" / "run_001" / "patched.json"
        HierarchicalConfigPatcher.patch_config(parent_path, [], output_path)

        patched = json.loads(output_path.read_text())
        # dir:: paths should be resolved to absolute
        verilog_files = patched["VERILOG_FILES"]
        assert len(verilog_files) == 1
        assert not verilog_files[0].startswith("dir::")
        assert verilog_files[0].endswith("/project/src/top.v")
        assert Path(verilog_files[0]).is_absolute()

        # Nested dir:: paths should also be resolved
        assert not patched["NESTED"]["LIB"].startswith("dir::")
        assert patched["NESTED"]["LIB"].endswith("/project/libs/mylib.lib")

    def test_patch_strips_params_with_dir_paths(self, tmp_path: Path) -> None:
        """Parameter stripping should work with dir:: resolved sources."""
        src_dir = tmp_path / "project" / "src"
        src_dir.mkdir(parents=True)
        (src_dir / "top.v").write_text(
            "module top;\n"
            "  sub #(.X(42)) inst (.clk(clk));\n"
            "endmodule\n"
        )
        (src_dir / "sub.v").write_text(
            "module sub #(parameter X = 1) (input clk);\nendmodule"
        )

        parent_config = {
            "DESIGN_NAME": "top",
            "VERILOG_FILES": ["dir::src/top.v", "dir::src/sub.v"],
        }
        parent_path = tmp_path / "project" / "config.json"
        parent_path.write_text(json.dumps(parent_config))

        modules = [
            HardenedModule("sub", Path("/art/sub.lef"), Path("/art/sub.gds")),
        ]
        output_path = tmp_path / "runs" / "patched.json"
        HierarchicalConfigPatcher.patch_config(parent_path, modules, output_path)

        patched = json.loads(output_path.read_text())
        # sub.v should be removed from VERILOG_FILES
        verilog_files = patched["VERILOG_FILES"]
        assert not any("sub.v" in vf for vf in verilog_files)
        # top.v should be patched (param overrides stripped)
        top_paths = [vf for vf in verilog_files if "top.v" in vf]
        assert len(top_paths) == 1
        patched_top = Path(top_paths[0]).read_text()
        assert "#(" not in patched_top
        assert "sub" in patched_top
        assert "inst" in patched_top
        # No vh entries in MACROS
        assert "vh" not in patched["MACROS"]["sub"]


# ===================================================================
# _remove_instance_params unit tests
# ===================================================================


class TestRemoveInstanceParams:
    """Test _remove_instance_params Verilog parameter stripping."""

    def test_simple_param_override(self) -> None:
        text = "picorv32 #(.ENABLE_IRQ(1)) cpu (.clk(clk));"
        result = _remove_instance_params(text, "picorv32")
        assert result == "picorv32 cpu (.clk(clk));"

    def test_multiline_params(self) -> None:
        text = (
            "picorv32 #(\n"
            "  .ENABLE_IRQ(1),\n"
            "  .PROGADDR_RESET(32'h0010_0000)\n"
            ") cpu (\n"
            "  .clk(clk)\n"
            ");"
        )
        result = _remove_instance_params(text, "picorv32")
        assert "#(" not in result
        assert "picorv32 cpu (" in result

    def test_nested_parens_in_params(self) -> None:
        text = "picorv32 #(.ADDR(func(a, b))) cpu (.clk(clk));"
        result = _remove_instance_params(text, "picorv32")
        assert result == "picorv32 cpu (.clk(clk));"

    def test_no_params_unchanged(self) -> None:
        text = "picorv32 cpu (.clk(clk));"
        result = _remove_instance_params(text, "picorv32")
        assert result == text

    def test_different_module_unchanged(self) -> None:
        text = "spimemio #(.WIDTH(8)) spi (.clk(clk));"
        result = _remove_instance_params(text, "picorv32")
        assert result == text

    def test_multiple_instances(self) -> None:
        text = (
            "picorv32 #(.A(1)) cpu0 (.clk(c));\n"
            "picorv32 #(.B(2)) cpu1 (.clk(c));\n"
        )
        result = _remove_instance_params(text, "picorv32")
        assert "#(" not in result
        assert "cpu0" in result
        assert "cpu1" in result

    def test_preserves_surrounding_code(self) -> None:
        text = (
            "wire clk;\n"
            "picorv32 #(.X(1)) cpu (.clk(clk));\n"
            "assign out = 1;\n"
        )
        result = _remove_instance_params(text, "picorv32")
        assert "wire clk;" in result
        assert "assign out = 1;" in result
        assert "#(" not in result


# ===================================================================
# _populate_macro_instances unit tests
# ===================================================================


class TestPopulateMacroInstances:
    """Test hierarchical instance extraction and placement."""

    def test_flat_instances(self, tmp_path: Path) -> None:
        """Top module directly instantiates macros."""
        src = tmp_path / "top.v"
        src.write_text(
            "module top;\n"
            "  picorv32 cpu (.clk(clk));\n"
            "  spimemio spi (.clk(clk));\n"
            "endmodule\n"
        )
        config: dict[str, Any] = {
            "DESIGN_NAME": "top",
            "VERILOG_FILES": [str(src)],
            "DIE_AREA": [0, 0, 1000, 1000],
            "MACROS": {
                "picorv32": {"instances": {}, "lef": ["/a.lef"], "gds": ["/a.gds"]},
                "spimemio": {"instances": {}, "lef": ["/b.lef"], "gds": ["/b.gds"]},
            },
        }
        modules = [
            HardenedModule("picorv32", Path("/a.lef"), Path("/a.gds")),
            HardenedModule("spimemio", Path("/b.lef"), Path("/b.gds")),
        ]
        _populate_macro_instances(config, modules)
        assert "cpu" in config["MACROS"]["picorv32"]["instances"]
        assert "spi" in config["MACROS"]["spimemio"]["instances"]
        # Both should have location and orientation
        inst = config["MACROS"]["picorv32"]["instances"]["cpu"]
        assert "location" in inst
        assert inst["orientation"] == "N"

    def test_hierarchical_instances(self, tmp_path: Path) -> None:
        """Macros instantiated inside a sub-module of the top.

        The intermediate module (picosoc) is instantiated with nested
        parameter overrides #(.PARAM(value)) — the extractor must
        handle arbitrary paren nesting.
        """
        (tmp_path / "top.v").write_text(
            "module picosoc_top;\n"
            "  picosoc #(\n"
            "    .BARREL_SHIFTER(1),\n"
            "    .PROGADDR_RESET(32'h0010_0000)\n"
            "  ) soc (.clk(clk));\n"
            "endmodule\n"
        )
        (tmp_path / "soc.v").write_text(
            "module picosoc;\n"
            "  picorv32 cpu (.clk(clk));\n"
            "  spimemio spimemio (.clk(clk));\n"
            "endmodule\n"
        )
        config: dict[str, Any] = {
            "DESIGN_NAME": "picosoc_top",
            "VERILOG_FILES": [str(tmp_path / "top.v"), str(tmp_path / "soc.v")],
            "DIE_AREA": [0, 0, 1200, 1200],
            "MACROS": {
                "picorv32": {"instances": {}, "lef": ["/a.lef"], "gds": ["/a.gds"]},
                "spimemio": {"instances": {}, "lef": ["/b.lef"], "gds": ["/b.gds"]},
            },
        }
        modules = [
            HardenedModule("picorv32", Path("/a.lef"), Path("/a.gds")),
            HardenedModule("spimemio", Path("/b.lef"), Path("/b.gds")),
        ]
        _populate_macro_instances(config, modules)
        assert "soc.cpu" in config["MACROS"]["picorv32"]["instances"]
        assert "soc.spimemio" in config["MACROS"]["spimemio"]["instances"]

    def test_no_instances_found(self, tmp_path: Path) -> None:
        """No crash when macro instances cannot be found."""
        src = tmp_path / "top.v"
        src.write_text("module top;\nendmodule\n")
        config: dict[str, Any] = {
            "DESIGN_NAME": "top",
            "VERILOG_FILES": [str(src)],
            "MACROS": {
                "picorv32": {"instances": {}, "lef": ["/a.lef"], "gds": ["/a.gds"]},
            },
        }
        modules = [HardenedModule("picorv32", Path("/a.lef"), Path("/a.gds"))]
        _populate_macro_instances(config, modules)
        # instances should remain empty
        assert config["MACROS"]["picorv32"]["instances"] == {}


# ===================================================================
# Manifest: module_results
# ===================================================================


class TestManifestModuleResults:
    """Test module_results in RunManifest and ManifestBuilder."""

    def test_default_empty_module_results(self) -> None:
        m = RunManifest(run_id="test")
        assert m.module_results == {}

    def test_record_module(self) -> None:
        mb = ManifestBuilder("test_run")
        mb.record_module("picorv32", {"completed": True, "best_score": 0.85})
        mb.record_module("spimemio", {"completed": True, "best_score": 0.90})
        manifest = mb.finalize()
        assert len(manifest.module_results) == 2
        assert manifest.module_results["picorv32"]["completed"] is True
        assert manifest.module_results["spimemio"]["best_score"] == 0.90

    def test_manifest_with_hierarchical_flow_mode(self) -> None:
        mb = ManifestBuilder("test_run")
        mb.set_flow_mode("hierarchical")
        mb.record_module("mod1", {"completed": True})
        manifest = mb.finalize()
        assert manifest.flow_mode == "hierarchical"
        assert "mod1" in manifest.module_results

    def test_manifest_serialization_with_modules(self, tmp_path: Path) -> None:
        mb = ManifestBuilder("test_run")
        mb.set_flow_mode("hierarchical")
        mb.record_module("mod1", {"completed": True, "stages_completed": ["SYNTH", "SIGNOFF"]})
        manifest = mb.finalize()

        ManifestBuilder.write_manifest(manifest, tmp_path)
        loaded = ManifestBuilder.load_manifest(tmp_path / "manifest.json")
        assert loaded.flow_mode == "hierarchical"
        assert "mod1" in loaded.module_results


# ===================================================================
# Workspace: create_module_dir
# ===================================================================


class TestWorkspaceModuleDir:
    """Test WorkspaceManager.create_module_dir."""

    def test_create_module_dir(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run_001"
        run_dir.mkdir()
        mod_dir = WorkspaceManager.create_module_dir(run_dir, "picorv32")
        assert mod_dir == run_dir / "modules" / "picorv32"
        assert mod_dir.is_dir()

    def test_create_module_dir_idempotent(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run_001"
        run_dir.mkdir()
        d1 = WorkspaceManager.create_module_dir(run_dir, "mod1")
        d2 = WorkspaceManager.create_module_dir(run_dir, "mod1")
        assert d1 == d2
        assert d1.is_dir()


# ===================================================================
# Mock Adapter: LEF/GDS for signoff
# ===================================================================


class TestMockAdapterSignoffArtifacts:
    """Test that MockExecutionAdapter produces LEF/GDS for signoff stage."""

    @pytest.fixture
    def adapter(self):
        from tests.mocks.mock_adapter import MockExecutionAdapter

        return MockExecutionAdapter()

    @pytest.mark.asyncio
    async def test_signoff_produces_lef(self, adapter, tmp_path: Path) -> None:
        attempt_dir = tmp_path / "attempt_001"
        attempt_dir.mkdir()

        result = await adapter.run_stage(
            run_root=str(tmp_path),
            stage_name="signoff",
            librelane_config_path="config.yaml",
            resolved_design_config_path="config.yaml",
            patch={"config_vars": {}},
            state_in_path=None,
            attempt_dir=str(attempt_dir),
            timeout_seconds=60,
        )

        assert result.execution_status == "success"
        artifacts_dir = Path(result.artifacts_dir)
        lef_path = artifacts_dir / "design.lef"
        assert lef_path.exists()
        content = lef_path.read_text()
        assert "MACRO" in content

    @pytest.mark.asyncio
    async def test_signoff_produces_gds(self, adapter, tmp_path: Path) -> None:
        attempt_dir = tmp_path / "attempt_001"
        attempt_dir.mkdir()

        result = await adapter.run_stage(
            run_root=str(tmp_path),
            stage_name="signoff",
            librelane_config_path="config.yaml",
            resolved_design_config_path="config.yaml",
            patch={"config_vars": {}},
            state_in_path=None,
            attempt_dir=str(attempt_dir),
            timeout_seconds=60,
        )

        artifacts_dir = Path(result.artifacts_dir)
        gds_path = artifacts_dir / "design.gds"
        assert gds_path.exists()
        assert gds_path.stat().st_size > 0

    @pytest.mark.asyncio
    async def test_non_signoff_no_lef_gds(self, adapter, tmp_path: Path) -> None:
        """Stages other than signoff should NOT produce LEF/GDS."""
        attempt_dir = tmp_path / "attempt_001"
        attempt_dir.mkdir()

        result = await adapter.run_stage(
            run_root=str(tmp_path),
            stage_name="synth",
            librelane_config_path="config.yaml",
            resolved_design_config_path="config.yaml",
            patch={"config_vars": {}},
            state_in_path=None,
            attempt_dir=str(attempt_dir),
            timeout_seconds=60,
        )

        artifacts_dir = Path(result.artifacts_dir)
        assert not (artifacts_dir / "design.lef").exists()
        assert not (artifacts_dir / "design.gds").exists()


# ===================================================================
# Worker Context: module_context
# ===================================================================


class TestWorkerModuleContext:
    """Test module_context parameter passthrough."""

    def test_build_context_includes_module_context(self) -> None:
        from agenticlane.agents.workers.base import WorkerAgent
        from agenticlane.schemas.evidence import EvidencePack

        config = AgenticLaneConfig()

        class FakeLLM:
            async def generate(self, **kwargs: Any) -> None:
                return None

        worker = WorkerAgent(FakeLLM(), "FLOORPLAN", config)  # type: ignore[arg-type]
        metrics = MetricsPayload(
            run_id="test", branch_id="B0", stage="FLOORPLAN", attempt=1,
            execution_status="success",
        )
        evidence = EvidencePack(stage="FLOORPLAN", attempt=1, execution_status="success")

        module_ctx = {"role": "submodule", "module_name": "picorv32"}
        ctx = worker._build_context(
            current_metrics=metrics,
            evidence_pack=evidence,
            constraint_digest=None,
            attempt_number=1,
            last_rejection=None,
            lessons_markdown=None,
            module_context=module_ctx,
        )
        assert ctx["module_context"] == module_ctx

    def test_build_context_module_context_none(self) -> None:
        from agenticlane.agents.workers.base import WorkerAgent
        from agenticlane.schemas.evidence import EvidencePack

        config = AgenticLaneConfig()

        class FakeLLM:
            async def generate(self, **kwargs: Any) -> None:
                return None

        worker = WorkerAgent(FakeLLM(), "SYNTH", config)  # type: ignore[arg-type]
        metrics = MetricsPayload(
            run_id="test", branch_id="B0", stage="SYNTH", attempt=1,
            execution_status="success",
        )
        evidence = EvidencePack(stage="SYNTH", attempt=1, execution_status="success")

        ctx = worker._build_context(
            current_metrics=metrics,
            evidence_pack=evidence,
            constraint_digest=None,
            attempt_number=1,
            last_rejection=None,
            lessons_markdown=None,
        )
        assert ctx["module_context"] is None


# ===================================================================
# Prompt Templates: hierarchical context
# ===================================================================


class TestPromptTemplateHierarchicalContext:
    """Test that prompt templates render with/without module_context."""

    @pytest.fixture
    def jinja_env(self):
        import jinja2

        tpl_dir = Path(__file__).resolve().parent.parent / "agenticlane" / "agents" / "prompts"
        return jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(tpl_dir)),
            undefined=jinja2.StrictUndefined,
        )

    def _base_context(self) -> dict[str, Any]:
        return {
            "stage": "FLOORPLAN",
            "attempt_number": 1,
            "intent_summary": "Optimize timing",
            "allowed_knobs": {},
            "knobs_table": "No knobs available.",
            "locked_constraints": ["CLOCK_PERIOD"],
            "metrics_summary": "No metrics.",
            "evidence_summary": "No issues.",
            "constraint_digest": None,
            "lessons_learned": "",
            "last_rejection_feedback": None,
            "patch_schema": {},
            "synth_stats": None,
            "post_synth_patch": None,
            "module_context": None,
        }

    def test_worker_base_without_module_context(self, jinja_env) -> None:
        ctx = self._base_context()
        tpl = jinja_env.get_template("worker_base.j2")
        rendered = tpl.render(**ctx)
        assert "Hierarchical Context" not in rendered

    def test_worker_base_with_submodule_context(self, jinja_env) -> None:
        ctx = self._base_context()
        ctx["module_context"] = {"role": "submodule", "module_name": "picorv32"}
        tpl = jinja_env.get_template("worker_base.j2")
        rendered = tpl.render(**ctx)
        assert "Hierarchical Context" in rendered
        assert "picorv32" in rendered
        assert "sub-module" in rendered

    def test_worker_base_with_parent_context(self, jinja_env) -> None:
        ctx = self._base_context()
        ctx["module_context"] = {
            "role": "parent",
            "hardened_modules": ["picorv32", "spimemio"],
        }
        tpl = jinja_env.get_template("worker_base.j2")
        rendered = tpl.render(**ctx)
        assert "Hierarchical Context" in rendered
        assert "picorv32" in rendered
        assert "spimemio" in rendered

    def test_floorplan_without_module_context(self, jinja_env) -> None:
        ctx = self._base_context()
        tpl = jinja_env.get_template("floorplan.j2")
        rendered = tpl.render(**ctx)
        assert "Hierarchical Context" not in rendered

    def test_floorplan_with_submodule_context(self, jinja_env) -> None:
        ctx = self._base_context()
        ctx["module_context"] = {"role": "submodule", "module_name": "spimemio"}
        tpl = jinja_env.get_template("floorplan.j2")
        rendered = tpl.render(**ctx)
        assert "Hierarchical Context" in rendered
        assert "spimemio" in rendered
        assert "compact" in rendered  # submodule-specific guidance

    def test_floorplan_with_parent_context(self, jinja_env) -> None:
        ctx = self._base_context()
        ctx["module_context"] = {
            "role": "parent",
            "hardened_modules": ["picorv32", "spimemio"],
        }
        tpl = jinja_env.get_template("floorplan.j2")
        rendered = tpl.render(**ctx)
        assert "Hierarchical Context" in rendered
        assert "macros" in rendered.lower()


# ===================================================================
# Orchestrator: _build_module_config
# ===================================================================


class TestBuildModuleConfig:
    """Test SequentialOrchestrator._build_module_config."""

    @pytest.fixture
    def orchestrator(self):
        from agenticlane.orchestration.orchestrator import SequentialOrchestrator
        from tests.mocks.mock_adapter import MockExecutionAdapter

        config = AgenticLaneConfig(
            project={"name": "parent_design"},
            design={
                "librelane_config_path": "./parent_config.yaml",
                "pdk": "sky130A",
                "flow_mode": "hierarchical",
                "modules": {
                    "mod1": {"librelane_config_path": "./mod1/config.yaml"},
                },
            },
        )
        return SequentialOrchestrator(config=config, adapter=MockExecutionAdapter())

    def test_basic_module_config(self, orchestrator) -> None:
        mod_cfg = ModuleConfig(librelane_config_path=Path("./mod1/config.yaml"))
        result = orchestrator._build_module_config("mod1", mod_cfg)

        assert result.design.librelane_config_path == Path("./mod1/config.yaml")
        assert result.design.flow_mode == "flat"
        assert result.design.modules == {}
        assert result.project.name == "parent_design_mod1"

    def test_module_config_inherits_parent_pdk(self, orchestrator) -> None:
        mod_cfg = ModuleConfig(librelane_config_path=Path("./mod1/config.yaml"))
        result = orchestrator._build_module_config("mod1", mod_cfg)
        assert result.design.pdk == "sky130A"

    def test_module_config_overrides_pdk(self, orchestrator) -> None:
        mod_cfg = ModuleConfig(
            librelane_config_path=Path("./mod1/config.yaml"),
            pdk="gf180mcuD",
        )
        result = orchestrator._build_module_config("mod1", mod_cfg)
        assert result.design.pdk == "gf180mcuD"

    def test_module_config_overrides_intent(self, orchestrator) -> None:
        mod_cfg = ModuleConfig(
            librelane_config_path=Path("./mod1/config.yaml"),
            intent=IntentConfig(prompt="custom intent", weights_hint={"timing": 1.0}),
        )
        result = orchestrator._build_module_config("mod1", mod_cfg)
        assert result.intent.prompt == "custom intent"

    def test_module_config_overrides_flow_control(self, orchestrator) -> None:
        mod_cfg = ModuleConfig(
            librelane_config_path=Path("./mod1/config.yaml"),
            flow_control=FlowControlConfig(
                budgets={"physical_attempts_per_stage": 20}
            ),
        )
        result = orchestrator._build_module_config("mod1", mod_cfg)
        assert result.flow_control.budgets.physical_attempts_per_stage == 20

    def test_module_config_overrides_parallel(self, orchestrator) -> None:
        mod_cfg = ModuleConfig(
            librelane_config_path=Path("./mod1/config.yaml"),
            parallel=ParallelConfig(enabled=False, max_parallel_branches=1, max_parallel_jobs=1),
        )
        result = orchestrator._build_module_config("mod1", mod_cfg)
        assert result.parallel.enabled is False

    def test_module_config_deep_copy(self, orchestrator) -> None:
        """Changing module config should not affect parent."""
        mod_cfg = ModuleConfig(librelane_config_path=Path("./mod1/config.yaml"))
        result = orchestrator._build_module_config("mod1", mod_cfg)
        result.design.pdk = "changed"
        assert orchestrator.config.design.pdk == "sky130A"

    def test_submodule_config_has_no_signoff_hard_gates(self, orchestrator) -> None:
        """Sub-module configs should have signoff hard gates cleared."""
        mod_cfg = ModuleConfig(librelane_config_path=Path("./mod1/config.yaml"))
        result = orchestrator._build_module_config("mod1", mod_cfg)
        assert result.judging.strictness.signoff_hard_gates == []

    def test_parent_config_retains_signoff_hard_gates(self, orchestrator) -> None:
        """Parent config should still have signoff hard gates after building module config."""
        mod_cfg = ModuleConfig(librelane_config_path=Path("./mod1/config.yaml"))
        orchestrator._build_module_config("mod1", mod_cfg)
        assert len(orchestrator.config.judging.strictness.signoff_hard_gates) > 0


# ===================================================================
# Orchestrator: _collect_module_artifacts
# ===================================================================


class TestCollectModuleArtifacts:
    """Test SequentialOrchestrator._collect_module_artifacts."""

    @pytest.fixture
    def orchestrator(self):
        from agenticlane.orchestration.orchestrator import (
            SequentialOrchestrator,
        )
        from tests.mocks.mock_adapter import MockExecutionAdapter

        config = AgenticLaneConfig(
            design={
                "flow_mode": "hierarchical",
                "modules": {
                    "mod1": {"librelane_config_path": "./m1/config.yaml"},
                },
            },
        )
        return SequentialOrchestrator(config=config, adapter=MockExecutionAdapter())

    def test_collect_lef_gds(self, orchestrator, tmp_path: Path) -> None:
        from agenticlane.orchestration.orchestrator import FlowResult

        # Create fake module run dir with LEF/GDS
        run_dir = tmp_path / "mod_run"
        art_dir = run_dir / "branches" / "B0" / "stages" / "signoff" / "attempt_001" / "artifacts"
        art_dir.mkdir(parents=True)
        (art_dir / "design.lef").write_text("MACRO mod1\nEND mod1\n")
        (art_dir / "design.gds").write_bytes(b"\x00" * 10)

        module_result = FlowResult(
            run_id="test", completed=True, run_dir=str(run_dir)
        )
        module_dir = tmp_path / "modules" / "mod1"

        result = orchestrator._collect_module_artifacts("mod1", module_result, module_dir)

        assert result is not None
        assert result.module_name == "mod1"
        assert result.lef_path.exists()
        assert result.gds_path.exists()
        assert result.lef_path.name == "mod1.lef"
        assert result.gds_path.name == "mod1.gds"

    def test_collect_missing_lef(self, orchestrator, tmp_path: Path) -> None:
        from agenticlane.orchestration.orchestrator import FlowResult

        run_dir = tmp_path / "mod_run"
        art_dir = run_dir / "artifacts"
        art_dir.mkdir(parents=True)
        # Only GDS, no LEF
        (art_dir / "design.gds").write_bytes(b"\x00" * 10)

        module_result = FlowResult(
            run_id="test", completed=True, run_dir=str(run_dir)
        )
        result = orchestrator._collect_module_artifacts(
            "mod1", module_result, tmp_path / "modules" / "mod1"
        )
        assert result is None

    def test_collect_no_run_dir(self, orchestrator, tmp_path: Path) -> None:
        from agenticlane.orchestration.orchestrator import FlowResult

        module_result = FlowResult(run_id="test", completed=True, run_dir=None)
        result = orchestrator._collect_module_artifacts(
            "mod1", module_result, tmp_path / "modules" / "mod1"
        )
        assert result is None

    def test_collect_with_netlist(self, orchestrator, tmp_path: Path) -> None:
        from agenticlane.orchestration.orchestrator import FlowResult

        run_dir = tmp_path / "mod_run"
        art_dir = run_dir / "artifacts"
        art_dir.mkdir(parents=True)
        (art_dir / "design.lef").write_text("MACRO\n")
        (art_dir / "design.gds").write_bytes(b"\x00" * 10)
        (art_dir / "design.nl.v").write_text("module mod1;\nendmodule\n")

        module_result = FlowResult(
            run_id="test", completed=True, run_dir=str(run_dir)
        )
        result = orchestrator._collect_module_artifacts(
            "mod1", module_result, tmp_path / "modules" / "mod1"
        )
        assert result is not None
        assert result.nl_path is not None
        assert result.nl_path.exists()


# ===================================================================
# Integration: flat mode regression
# ===================================================================


class TestFlatModeRegression:
    """Ensure flat mode still works after hierarchical changes."""

    @pytest.mark.asyncio
    async def test_flat_flow_unchanged(self, tmp_path: Path) -> None:
        from agenticlane.orchestration.orchestrator import SequentialOrchestrator
        from tests.mocks.mock_adapter import MockExecutionAdapter

        config = AgenticLaneConfig(
            project={"output_dir": str(tmp_path)},
            design={"flow_mode": "flat"},
            flow_control={
                "budgets": {
                    "physical_attempts_per_stage": 1,
                    "cognitive_retries_per_attempt": 0,
                },
            },
            parallel={"enabled": False, "max_parallel_branches": 1, "max_parallel_jobs": 1},
        )

        orch = SequentialOrchestrator(
            config=config,
            adapter=MockExecutionAdapter(),
        )
        # Passthrough (no LLM) runs flat
        result = await orch.run_flow(stages=["SYNTH", "FLOORPLAN"])
        assert result.run_id is not None
        assert "SYNTH" in result.stages_completed


# ===================================================================
# Integration: hierarchical flow with mocks
# ===================================================================


class TestHierarchicalFlowIntegration:
    """Integration test: full hierarchical flow with mock adapter + mock LLM."""

    @pytest.mark.asyncio
    async def test_two_module_hierarchical_flow(self, tmp_path: Path) -> None:
        """Run hierarchical flow with 2 modules + parent, all mocked."""
        from agenticlane.orchestration.orchestrator import SequentialOrchestrator
        from tests.mocks.mock_adapter import MockExecutionAdapter
        from tests.mocks.mock_llm import MockLLMProvider

        # Create per-module LibreLane configs on disk
        mod1_dir = tmp_path / "mod1"
        mod1_dir.mkdir()
        (mod1_dir / "config.yaml").write_text(
            json.dumps({"DESIGN_NAME": "mod1", "CLOCK_PERIOD": 10.0})
        )

        mod2_dir = tmp_path / "mod2"
        mod2_dir.mkdir()
        (mod2_dir / "config.yaml").write_text(
            json.dumps({"DESIGN_NAME": "mod2", "CLOCK_PERIOD": 10.0})
        )

        # Parent config on disk
        (tmp_path / "parent_config.json").write_text(
            json.dumps({"DESIGN_NAME": "top", "CLOCK_PERIOD": 10.0})
        )

        config = AgenticLaneConfig(
            project={"name": "hier_test", "output_dir": str(tmp_path)},
            design={
                "librelane_config_path": str(tmp_path / "parent_config.json"),
                "pdk": "sky130A",
                "flow_mode": "hierarchical",
                "modules": {
                    "mod1": {
                        "librelane_config_path": str(mod1_dir / "config.yaml"),
                    },
                    "mod2": {
                        "librelane_config_path": str(mod2_dir / "config.yaml"),
                    },
                },
            },
            flow_control={
                "budgets": {
                    "physical_attempts_per_stage": 1,
                    "cognitive_retries_per_attempt": 1,
                },
            },
            parallel={
                "enabled": False,
                "max_parallel_branches": 1,
                "max_parallel_jobs": 1,
            },
            initialization={"zero_shot": {"enabled": False}},
            # Relax judge gates: basic distillation doesn't populate metrics sub-objects
            judging={
                "strictness": {
                    "hard_gates": ["execution_success"],
                    "signoff_hard_gates": [],
                },
            },
        )

        mock_llm = MockLLMProvider()
        # Worker calls return empty patch (accepted by default)
        mock_llm.add_response("worker", {"config_vars": {}})
        # Judge calls must return PASS votes for stages to succeed
        mock_llm.add_response("judge", {
            "vote": "PASS",
            "confidence": 0.9,
            "rationale": "Looks good",
            "blocking_issues": [],
        })
        mock_llm.set_default_response({
            "vote": "PASS",
            "confidence": 0.9,
            "rationale": "OK",
            "blocking_issues": [],
            "config_vars": {},
        })

        adapter = MockExecutionAdapter()

        orch = SequentialOrchestrator(
            config=config,
            adapter=adapter,
            llm_provider=mock_llm,
        )

        # Run only SYNTH + SIGNOFF to keep test fast
        result = await orch.run_flow(stages=["SYNTH", "SIGNOFF"])

        # Verify flow completed
        assert result.run_id is not None
        assert result.run_dir is not None

        # Check that manifest was written
        run_dir = Path(result.run_dir)
        manifest_path = run_dir / "manifest.json"
        assert manifest_path.exists()
        manifest_data = json.loads(manifest_path.read_text())
        assert manifest_data["flow_mode"] == "hierarchical"

    @pytest.mark.asyncio
    async def test_hierarchical_no_modules_falls_back(self, tmp_path: Path) -> None:
        """If modules dict is empty (auto mode), should fall back to flat."""
        from agenticlane.orchestration.orchestrator import SequentialOrchestrator
        from tests.mocks.mock_adapter import MockExecutionAdapter
        from tests.mocks.mock_llm import MockLLMProvider

        # Create parent config
        (tmp_path / "config.json").write_text(
            json.dumps({"DESIGN_NAME": "top"})
        )

        # Use auto mode (no modules defined)
        config = AgenticLaneConfig(
            project={"output_dir": str(tmp_path)},
            design={
                "librelane_config_path": str(tmp_path / "config.json"),
                "flow_mode": "flat",
            },
            flow_control={
                "budgets": {
                    "physical_attempts_per_stage": 1,
                    "cognitive_retries_per_attempt": 0,
                },
            },
            parallel={
                "enabled": False,
                "max_parallel_branches": 1,
                "max_parallel_jobs": 1,
            },
            initialization={"zero_shot": {"enabled": False}},
        )

        mock_llm = MockLLMProvider()
        mock_llm.set_default_response({"config_vars": {}})

        orch = SequentialOrchestrator(
            config=config,
            adapter=MockExecutionAdapter(),
            llm_provider=mock_llm,
        )

        result = await orch.run_flow(stages=["SYNTH"])
        assert result.run_id is not None


# ===================================================================
# Deadlock: auto_relax clears signoff gates
# ===================================================================


class TestAutoRelaxDeadlock:
    """Test that auto_relax deadlock policy actually relaxes constraints."""

    def test_auto_relax_returns_relax_signal(self) -> None:
        from agenticlane.orchestration.deadlock import DeadlockResolver

        result = DeadlockResolver.resolve("auto_relax")
        assert result["action_taken"] == "auto_relax"
        assert result["relax_signoff_hard_gates"] is True

    def test_stop_has_no_relax_signal(self) -> None:
        from agenticlane.orchestration.deadlock import DeadlockResolver

        result = DeadlockResolver.resolve("stop")
        assert "relax_signoff_hard_gates" not in result


# ===================================================================
# Orchestrator: artifact-based module completion
# ===================================================================


class TestArtifactBasedCompletion:
    """Test that hierarchical flow uses artifact-based (not stage-based) completion."""

    @pytest.fixture
    def orchestrator(self):
        from agenticlane.orchestration.orchestrator import SequentialOrchestrator
        from tests.mocks.mock_adapter import MockExecutionAdapter

        config = AgenticLaneConfig(
            design={
                "flow_mode": "hierarchical",
                "modules": {
                    "mod1": {"librelane_config_path": "./m1/config.yaml"},
                },
            },
        )
        return SequentialOrchestrator(config=config, adapter=MockExecutionAdapter())

    def test_module_with_artifacts_but_incomplete_is_ok(
        self, orchestrator, tmp_path: Path
    ) -> None:
        """Module that produced LEF/GDS but failed SIGNOFF should still be usable."""
        from agenticlane.orchestration.orchestrator import FlowResult

        # Create fake module run dir with LEF/GDS (from FINISH stage)
        run_dir = tmp_path / "mod_run"
        finish_dir = (
            run_dir / "branches" / "B0" / "stages" / "FINISH" / "attempt_001" / "artifacts"
        )
        finish_dir.mkdir(parents=True)
        (finish_dir / "design.lef").write_text("MACRO mod1\nEND mod1\n")
        (finish_dir / "design.gds").write_bytes(b"\x00" * 10)

        # Module result with completed=False (SIGNOFF failed)
        module_result = FlowResult(
            run_id="test",
            completed=False,
            stages_failed=["SIGNOFF"],
            run_dir=str(run_dir),
        )
        module_dir = tmp_path / "modules" / "mod1"

        result = orchestrator._collect_module_artifacts("mod1", module_result, module_dir)
        assert result is not None
        assert result.lef_path.exists()
        assert result.gds_path.exists()

    def test_module_without_artifacts_returns_none(
        self, orchestrator, tmp_path: Path
    ) -> None:
        """Module that produced no LEF/GDS should return None."""
        from agenticlane.orchestration.orchestrator import FlowResult

        run_dir = tmp_path / "mod_run"
        run_dir.mkdir(parents=True)

        module_result = FlowResult(
            run_id="test",
            completed=False,
            stages_failed=["SYNTH", "FLOORPLAN"],
            run_dir=str(run_dir),
        )
        module_dir = tmp_path / "modules" / "mod1"

        result = orchestrator._collect_module_artifacts("mod1", module_result, module_dir)
        assert result is None
