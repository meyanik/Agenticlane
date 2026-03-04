"""SSE event bus and file watcher for real-time dashboard updates.

Provides:
- :class:`DashboardEventBus`: In-process pub/sub for SSE streaming.
- :class:`RunFileWatcher`: Watches run directories for new/modified JSON
  files and publishes change events to the event bus.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Files we monitor for changes in each attempt directory.
_WATCHED_FILES = (
    "metrics.json",
    "evidence.json",
    "judge_votes.json",
    "composite_score.json",
    "checkpoint.json",
    "patch.json",
)


class DashboardEventBus:
    """In-process pub/sub for SSE streaming.

    Subscribers receive events as dicts with ``type`` and ``data`` keys.
    Each subscriber gets its own asyncio Queue.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[dict[str, Any]]]] = {}
        self._global_subscribers: list[asyncio.Queue[dict[str, Any]]] = []

    async def publish(
        self, run_id: str, event_type: str, data: dict[str, Any]
    ) -> None:
        """Publish an event to all subscribers for *run_id* and global."""
        event = {
            "type": event_type,
            "run_id": run_id,
            "data": data,
            "timestamp": time.time(),
        }
        # Run-specific subscribers
        for queue in self._subscribers.get(run_id, []):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
                queue.put_nowait(event)

        # Global subscribers (for all-runs overview)
        for queue in self._global_subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
                queue.put_nowait(event)

    async def subscribe(
        self, run_id: str, max_queue: int = 256
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Subscribe to events for a specific run.

        Yields event dicts as they arrive.  The generator cleans up
        its queue on exit (e.g. when the SSE client disconnects).
        """
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            maxsize=max_queue
        )
        if run_id not in self._subscribers:
            self._subscribers[run_id] = []
        self._subscribers[run_id].append(queue)
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            self._subscribers[run_id].remove(queue)
            if not self._subscribers[run_id]:
                del self._subscribers[run_id]

    async def subscribe_global(
        self, max_queue: int = 256
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Subscribe to events for all runs."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            maxsize=max_queue
        )
        self._global_subscribers.append(queue)
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            self._global_subscribers.remove(queue)

    @property
    def subscriber_count(self) -> int:
        """Total number of active subscribers."""
        total = len(self._global_subscribers)
        for queues in self._subscribers.values():
            total += len(queues)
        return total


class RunFileWatcher:
    """Watches run directory for new/modified JSON files.

    Polls the filesystem at regular intervals and publishes events
    to a :class:`DashboardEventBus` when changes are detected.
    """

    def __init__(
        self,
        event_bus: DashboardEventBus,
        poll_interval: float = 1.0,
    ) -> None:
        self._event_bus = event_bus
        self._poll_interval = poll_interval
        self._watching: dict[str, asyncio.Task[None]] = {}
        self._file_mtimes: dict[str, float] = {}

    async def watch_run(self, run_id: str, runs_dir: Path) -> None:
        """Start watching a run directory for file changes.

        Spawns an asyncio task that polls until cancelled.
        """
        if run_id in self._watching:
            return  # Already watching

        task = asyncio.create_task(
            self._poll_loop(run_id, runs_dir / run_id),
            name=f"watch_{run_id}",
        )
        self._watching[run_id] = task

    def stop_watching(self, run_id: str) -> None:
        """Stop watching a specific run."""
        task = self._watching.pop(run_id, None)
        if task is not None:
            task.cancel()

    def stop_all(self) -> None:
        """Stop all watchers."""
        for task in self._watching.values():
            task.cancel()
        self._watching.clear()

    async def _poll_loop(self, run_id: str, run_dir: Path) -> None:
        """Periodically scan the run directory for changes."""
        try:
            while True:
                await self._scan_once(run_id, run_dir)
                await asyncio.sleep(self._poll_interval)
        except asyncio.CancelledError:
            logger.debug("File watcher stopped for run %s", run_id)

    async def _scan_once(self, run_id: str, run_dir: Path) -> None:
        """Scan all attempt directories for modified files."""
        if not run_dir.exists():
            return

        for stage_dir in run_dir.glob("branches/*/stages/*"):
            stage_name = stage_dir.name
            for attempt_dir in stage_dir.glob("attempt_*"):
                for filename in _WATCHED_FILES:
                    filepath = attempt_dir / filename
                    if not filepath.exists():
                        continue
                    key = str(filepath)
                    try:
                        mtime = os.stat(filepath).st_mtime
                    except OSError:
                        continue

                    prev_mtime = self._file_mtimes.get(key)
                    if prev_mtime is None or mtime > prev_mtime:
                        self._file_mtimes[key] = mtime
                        if prev_mtime is not None:
                            # File was modified (not first scan)
                            await self._emit_change(
                                run_id, stage_name, attempt_dir.name,
                                filename, filepath,
                            )

        # Also watch manifest.json for completion
        manifest_path = run_dir / "manifest.json"
        if manifest_path.exists():
            key = str(manifest_path)
            try:
                mtime = os.stat(manifest_path).st_mtime
            except OSError:
                return
            prev_mtime = self._file_mtimes.get(key)
            if prev_mtime is None or mtime > prev_mtime:
                self._file_mtimes[key] = mtime
                if prev_mtime is not None:
                    await self._event_bus.publish(run_id, "manifest_updated", {
                        "file": "manifest.json",
                    })

    async def _emit_change(
        self,
        run_id: str,
        stage: str,
        attempt: str,
        filename: str,
        filepath: Path,
    ) -> None:
        """Emit a file-change event with the file contents."""
        try:
            data = json.loads(filepath.read_text())
        except (json.JSONDecodeError, OSError):
            data = None

        event_type = filename.replace(".json", "_updated")
        await self._event_bus.publish(run_id, event_type, {
            "stage": stage,
            "attempt": attempt,
            "file": filename,
            "content": data,
        })
