"""Tests for the dashboard subprocess run manager."""

from __future__ import annotations

import signal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agenticlane.reporting.dashboard_runner import DashboardRunManager


class TestDashboardRunManager:
    @pytest.mark.asyncio
    async def test_start_run_generates_run_id(self, tmp_path: Path) -> None:
        """start_run should generate a run_id if not provided."""
        manager = DashboardRunManager()
        config: dict = {"project": {}}

        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.pid = 12345
            mock_proc.poll.return_value = None
            mock_popen.return_value = mock_proc

            result = await manager.start_run(config, tmp_path)

        assert result["status"] == "started"
        assert result["run_id"].startswith("run_")
        assert result["pid"] == 12345

    @pytest.mark.asyncio
    async def test_start_run_uses_provided_run_id(self, tmp_path: Path) -> None:
        """start_run should use config-provided run_id."""
        manager = DashboardRunManager()
        config: dict = {"project": {"run_id": "my_custom_run"}}

        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.pid = 99
            mock_proc.poll.return_value = None
            mock_popen.return_value = mock_proc

            result = await manager.start_run(config, tmp_path)

        assert result["run_id"] == "my_custom_run"

    @pytest.mark.asyncio
    async def test_stop_run_sends_sigterm(self, tmp_path: Path) -> None:
        """stop_run should send SIGTERM to the subprocess."""
        manager = DashboardRunManager()
        config: dict = {"project": {"run_id": "stop_test"}}

        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.pid = 100
            mock_proc.poll.return_value = None  # still running
            mock_popen.return_value = mock_proc

            await manager.start_run(config, tmp_path)
            stopped = await manager.stop_run("stop_test")

        assert stopped is True
        mock_proc.send_signal.assert_called_once_with(signal.SIGTERM)

    @pytest.mark.asyncio
    async def test_stop_run_unknown_id(self) -> None:
        """stop_run should return False for unknown run_id."""
        manager = DashboardRunManager()
        stopped = await manager.stop_run("nonexistent")
        assert stopped is False

    @pytest.mark.asyncio
    async def test_stop_run_already_finished(self, tmp_path: Path) -> None:
        """stop_run should return False if process already exited."""
        manager = DashboardRunManager()
        config: dict = {"project": {"run_id": "finished_run"}}

        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.pid = 200
            mock_proc.poll.return_value = 0  # already finished
            mock_proc.returncode = 0
            mock_popen.return_value = mock_proc

            await manager.start_run(config, tmp_path)
            stopped = await manager.stop_run("finished_run")

        assert stopped is False

    def test_get_active_empty(self) -> None:
        """get_active should return empty list when no runs."""
        manager = DashboardRunManager()
        assert manager.get_active() == []

    @pytest.mark.asyncio
    async def test_get_active_returns_running(self, tmp_path: Path) -> None:
        """get_active should return info for running processes."""
        manager = DashboardRunManager()
        config: dict = {"project": {"run_id": "active_run"}}

        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.pid = 300
            mock_proc.poll.return_value = None  # still running
            mock_popen.return_value = mock_proc

            await manager.start_run(config, tmp_path)

        active = manager.get_active()
        assert len(active) == 1
        assert active[0]["run_id"] == "active_run"
        assert active[0]["status"] == "running"
        assert active[0]["pid"] == 300

    @pytest.mark.asyncio
    async def test_reap_finished(self, tmp_path: Path) -> None:
        """Finished processes should be reaped from active list."""
        manager = DashboardRunManager()
        config: dict = {"project": {"run_id": "reap_test"}}

        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.pid = 400
            mock_proc.poll.return_value = None
            mock_proc.returncode = None
            mock_popen.return_value = mock_proc

            await manager.start_run(config, tmp_path)
            assert len(manager.get_active()) == 1

            # Simulate process finishing
            mock_proc.poll.return_value = 0
            mock_proc.returncode = 0
            assert len(manager.get_active()) == 0

    @pytest.mark.asyncio
    async def test_get_run_status(self, tmp_path: Path) -> None:
        """get_run_status should return status for tracked run."""
        manager = DashboardRunManager()
        config: dict = {"project": {"run_id": "status_run"}}

        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.pid = 500
            mock_proc.poll.return_value = None
            mock_popen.return_value = mock_proc

            await manager.start_run(config, tmp_path)

        status = manager.get_run_status("status_run")
        assert status is not None
        assert status["run_id"] == "status_run"
        assert status["status"] == "running"

    def test_get_run_status_unknown(self) -> None:
        """get_run_status should return None for unknown run_id."""
        manager = DashboardRunManager()
        assert manager.get_run_status("unknown") is None

    @pytest.mark.asyncio
    async def test_config_written_to_yaml(self, tmp_path: Path) -> None:
        """start_run should write config to a YAML temp file."""
        import yaml

        manager = DashboardRunManager()
        config: dict = {
            "project": {"run_id": "yaml_test"},
            "llm": {"provider": "litellm"},
        }

        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.pid = 600
            mock_proc.poll.return_value = None
            mock_popen.return_value = mock_proc

            result = await manager.start_run(config, tmp_path)

        # Verify config file was written
        config_path = Path(result["config_path"])
        assert config_path.exists()
        written = yaml.safe_load(config_path.read_text())
        assert written["project"]["run_id"] == "yaml_test"
        assert written["llm"]["provider"] == "litellm"
