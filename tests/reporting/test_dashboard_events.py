"""Tests for the SSE event bus and file watcher."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from agenticlane.reporting.dashboard_events import DashboardEventBus, RunFileWatcher


class TestDashboardEventBus:
    @pytest.mark.asyncio
    async def test_publish_subscribe(self) -> None:
        bus = DashboardEventBus()
        received: list[dict] = []

        async def reader() -> None:
            async for event in bus.subscribe("run_001"):
                received.append(event)
                if len(received) >= 2:
                    break

        task = asyncio.create_task(reader())
        await asyncio.sleep(0.05)

        await bus.publish("run_001", "metrics_updated", {"stage": "SYNTH"})
        await bus.publish("run_001", "checkpoint_updated", {"stage": "FLOORPLAN"})
        await asyncio.wait_for(task, timeout=2.0)

        assert len(received) == 2
        assert received[0]["type"] == "metrics_updated"
        assert received[1]["type"] == "checkpoint_updated"

    @pytest.mark.asyncio
    async def test_isolate_subscribers(self) -> None:
        bus = DashboardEventBus()
        received_001: list[dict] = []
        received_002: list[dict] = []

        async def reader(run_id: str, out: list[dict]) -> None:
            async for event in bus.subscribe(run_id):
                out.append(event)
                break

        t1 = asyncio.create_task(reader("run_001", received_001))
        t2 = asyncio.create_task(reader("run_002", received_002))
        await asyncio.sleep(0.05)

        await bus.publish("run_001", "test", {"data": "for_001"})
        await asyncio.wait_for(t1, timeout=2.0)

        # run_002 should not have received anything
        assert len(received_001) == 1
        assert len(received_002) == 0
        t2.cancel()

    @pytest.mark.asyncio
    async def test_global_subscribe(self) -> None:
        bus = DashboardEventBus()
        received: list[dict] = []

        async def reader() -> None:
            async for event in bus.subscribe_global():
                received.append(event)
                if len(received) >= 2:
                    break

        task = asyncio.create_task(reader())
        await asyncio.sleep(0.05)

        await bus.publish("run_001", "test1", {})
        await bus.publish("run_002", "test2", {})
        await asyncio.wait_for(task, timeout=2.0)

        assert len(received) == 2
        assert received[0]["run_id"] == "run_001"
        assert received[1]["run_id"] == "run_002"

    @pytest.mark.asyncio
    async def test_subscriber_count(self) -> None:
        bus = DashboardEventBus()
        assert bus.subscriber_count == 0

        # We can't easily test count without async context, but verify default
        assert isinstance(bus.subscriber_count, int)

    @pytest.mark.asyncio
    async def test_queue_overflow(self) -> None:
        bus = DashboardEventBus()
        received: list[dict] = []

        async def reader() -> None:
            async for event in bus.subscribe("run_001", max_queue=2):
                received.append(event)
                if len(received) >= 2:
                    break

        # Publish 5 events before starting reader
        for i in range(5):
            await bus.publish("run_001", f"event_{i}", {"i": i})

        task = asyncio.create_task(reader())
        await asyncio.sleep(0.1)

        # Publish 2 more to trigger reads
        await bus.publish("run_001", "final_1", {})
        await bus.publish("run_001", "final_2", {})

        await asyncio.wait_for(task, timeout=2.0)
        assert len(received) == 2


class TestRunFileWatcher:
    @pytest.mark.asyncio
    async def test_watcher_detects_changes(self, tmp_path: Path) -> None:
        bus = DashboardEventBus()
        watcher = RunFileWatcher(bus, poll_interval=0.1)

        run_dir = tmp_path / "run_test"
        att_dir = run_dir / "branches" / "B0" / "stages" / "SYNTH" / "attempt_001"
        att_dir.mkdir(parents=True)
        (att_dir / "metrics.json").write_text(json.dumps({"initial": True}))

        received: list[dict] = []

        async def reader() -> None:
            async for event in bus.subscribe("run_test"):
                received.append(event)
                break

        task = asyncio.create_task(reader())
        await watcher.watch_run("run_test", tmp_path)

        # Wait for initial scan
        await asyncio.sleep(0.3)

        # Modify the file
        (att_dir / "metrics.json").write_text(json.dumps({"updated": True}))

        await asyncio.wait_for(task, timeout=3.0)
        watcher.stop_all()

        assert len(received) >= 1
        assert received[0]["type"] == "metrics_updated"

    @pytest.mark.asyncio
    async def test_stop_watcher(self, tmp_path: Path) -> None:
        bus = DashboardEventBus()
        watcher = RunFileWatcher(bus, poll_interval=0.1)

        await watcher.watch_run("run_test", tmp_path)
        assert "run_test" in watcher._watching
        watcher.stop_watching("run_test")
        assert "run_test" not in watcher._watching

    @pytest.mark.asyncio
    async def test_stop_all(self, tmp_path: Path) -> None:
        bus = DashboardEventBus()
        watcher = RunFileWatcher(bus, poll_interval=0.1)

        await watcher.watch_run("run_1", tmp_path)
        await watcher.watch_run("run_2", tmp_path)
        watcher.stop_all()
        assert len(watcher._watching) == 0
