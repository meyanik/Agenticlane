"""Phase 0 smoke tests: verify build, CLI, and tooling."""

import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agenticlane import __version__
from agenticlane.cli.main import app

runner = CliRunner()


class TestPackageImport:
    """Verify the package imports correctly."""

    def test_version_string(self) -> None:
        assert __version__ == "0.1.0"

    def test_import_cli(self) -> None:
        from agenticlane.cli import main  # noqa: F401

    def test_import_config_package(self) -> None:
        import agenticlane.config  # noqa: F401

    def test_import_schemas_package(self) -> None:
        import agenticlane.schemas  # noqa: F401

    def test_import_execution_package(self) -> None:
        import agenticlane.execution  # noqa: F401

    def test_import_orchestration_package(self) -> None:
        import agenticlane.orchestration  # noqa: F401

    def test_import_distill_package(self) -> None:
        import agenticlane.distill  # noqa: F401

    def test_import_agents_package(self) -> None:
        import agenticlane.agents  # noqa: F401

    def test_import_judge_package(self) -> None:
        import agenticlane.judge  # noqa: F401


class TestCLI:
    """Verify the CLI skeleton works."""

    def test_cli_help(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "agenticlane" in result.stdout.lower() or "AgenticLane" in result.stdout

    def test_cli_version(self) -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.stdout

    def test_init_help(self) -> None:
        result = runner.invoke(app, ["init", "--help"])
        assert result.exit_code == 0
        assert "design" in result.stdout.lower()

    def test_run_help(self) -> None:
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0

    def test_report_help(self) -> None:
        result = runner.invoke(app, ["report", "--help"])
        assert result.exit_code == 0

    def test_dashboard_help(self) -> None:
        result = runner.invoke(app, ["dashboard", "--help"])
        assert result.exit_code == 0

    def test_replay_help(self) -> None:
        result = runner.invoke(app, ["replay", "--help"])
        assert result.exit_code == 0

    def test_init_creates_project(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app, ["init", "--design", "test_spm", "--pdk", "sky130A", "-o", str(tmp_path)]
        )
        assert result.exit_code == 0
        project_dir = tmp_path / "test_spm"
        assert project_dir.exists()
        assert (project_dir / "agentic_config.yaml").exists()
        assert (project_dir / "design" / "config.yaml").exists()
        assert (project_dir / "src").exists()

    def test_init_config_content(self, tmp_path: Path) -> None:
        runner.invoke(
            app, ["init", "--design", "my_block", "--pdk", "gf180mcu", "-o", str(tmp_path)]
        )
        config_text = (tmp_path / "my_block" / "agentic_config.yaml").read_text()
        assert 'name: "my_block"' in config_text
        assert 'pdk: "gf180mcu"' in config_text


class TestTooling:
    """Verify linting and type checking pass on the codebase."""

    @pytest.mark.slow
    def test_ruff_check(self, project_root: Path) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "check", str(project_root / "agenticlane")],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"ruff check failed:\n{result.stdout}\n{result.stderr}"

    @pytest.mark.slow
    def test_mypy_check(self, project_root: Path) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "mypy", str(project_root / "agenticlane"),
             "--ignore-missing-imports"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"mypy failed:\n{result.stdout}\n{result.stderr}"
