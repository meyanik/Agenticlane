"""LibreLane local execution adapter.

Implements :class:`ExecutionAdapter` by driving the LibreLane Python API
(``Flow.factory.get("Classic")`` + ``flow.start()``) to run individual
ASIC PnR stages.

LibreLane: https://github.com/librelane/librelane
Docs: https://librelane.readthedocs.io/en/latest/
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any, Optional

from agenticlane.execution.adapter import ExecutionAdapter
from agenticlane.orchestration.graph import STAGE_GRAPH, StageSpec
from agenticlane.schemas.execution import ExecutionResult

try:
    from librelane.flows import Flow  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    Flow = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

# Report file names we look for when collecting artifacts
_REPORT_GLOBS = [
    "*.rpt",
    "*.log",
    "*.json",
    "*.def",
    "*.v",
    "*.nl.v",
    "*.sdc",
    "*.spef",
    "*.gds",
    "*.lef",
]


class LibreLaneLocalAdapter(ExecutionAdapter):
    """Runs LibreLane stages locally via the Python API.

    Parameters
    ----------
    pdk_root:
        Path to the PDK installation root.  If *None*, LibreLane will
        use its default ``PDK_ROOT`` environment variable or Volare.
    pdk:
        PDK name (e.g. ``sky130A``).  Passed to the flow constructor.
    scl:
        Standard cell library name.
    design_dir:
        Path to the design directory containing Verilog sources.
        If *None*, derived from the config file's parent directory.
    """

    def __init__(
        self,
        *,
        pdk_root: Optional[str] = None,
        pdk: str = "sky130A",
        scl: Optional[str] = None,
        design_dir: Optional[str] = None,
    ) -> None:
        self.pdk_root = pdk_root
        self.pdk = pdk
        self.scl = scl
        self.design_dir = design_dir

    async def run_stage(
        self,
        *,
        run_root: str,
        stage_name: str,
        librelane_config_path: str,
        resolved_design_config_path: str,
        patch: dict[str, Any],
        state_in_path: Optional[str],
        attempt_dir: str,
        timeout_seconds: int,
    ) -> ExecutionResult:
        """Run a single LibreLane stage in an isolated workspace."""
        start = time.monotonic()

        # Create directory structure
        workspace_dir = os.path.join(attempt_dir, "workspace")
        artifacts_dir = os.path.join(attempt_dir, "artifacts")
        os.makedirs(workspace_dir, exist_ok=True)
        os.makedirs(artifacts_dir, exist_ok=True)

        # Look up stage spec
        stage_upper = stage_name.upper()
        try:
            stage_spec: StageSpec = STAGE_GRAPH[stage_upper]
        except KeyError:
            runtime = time.monotonic() - start
            return ExecutionResult(
                execution_status="config_error",
                exit_code=1,
                runtime_seconds=runtime,
                attempt_dir=attempt_dir,
                workspace_dir=workspace_dir,
                artifacts_dir=artifacts_dir,
                state_out_path=None,
                stderr_tail=f"Unknown stage: {stage_name}",
                error_summary=f"Unknown stage '{stage_name}'",
            )

        # Build attempt tag
        attempt_tag = Path(attempt_dir).name

        try:
            # Run LibreLane stage
            state_out_path = await asyncio.wait_for(
                self._run_librelane(
                    config_path=librelane_config_path,
                    stage_spec=stage_spec,
                    patch=patch,
                    attempt_tag=attempt_tag,
                    workspace_dir=workspace_dir,
                    state_in_path=state_in_path,
                ),
                timeout=timeout_seconds,
            )

            runtime = time.monotonic() - start

            # Collect artifacts
            self._collect_artifacts(workspace_dir, artifacts_dir)

            # Copy state_out.json into attempt_dir if found
            final_state_out = None
            if state_out_path and os.path.isfile(state_out_path):
                dest = os.path.join(attempt_dir, "state_out.json")
                shutil.copy2(state_out_path, dest)
                final_state_out = dest
            else:
                # Try to find state_out.json in workspace
                found = self._find_state_out(workspace_dir)
                if found:
                    dest = os.path.join(attempt_dir, "state_out.json")
                    shutil.copy2(found, dest)
                    final_state_out = dest

            return ExecutionResult(
                execution_status="success",
                exit_code=0,
                runtime_seconds=runtime,
                attempt_dir=attempt_dir,
                workspace_dir=workspace_dir,
                artifacts_dir=artifacts_dir,
                state_out_path=final_state_out,
                stderr_tail=None,
                error_summary=None,
            )

        except asyncio.TimeoutError:
            runtime = time.monotonic() - start
            self._collect_artifacts(workspace_dir, artifacts_dir)
            return ExecutionResult(
                execution_status="timeout",
                exit_code=124,
                runtime_seconds=runtime,
                attempt_dir=attempt_dir,
                workspace_dir=workspace_dir,
                artifacts_dir=artifacts_dir,
                state_out_path=None,
                stderr_tail=f"Stage {stage_name} timed out after {timeout_seconds}s",
                error_summary=f"Timeout after {timeout_seconds}s",
            )

        except Exception as exc:  # noqa: BLE001
            runtime = time.monotonic() - start
            stderr_tail = self._capture_stderr(workspace_dir, str(exc))
            self._collect_artifacts(workspace_dir, artifacts_dir)

            # LibreLane raises an exception for "deferred errors" (DRC/LVS
            # violations) even though the flow ran to completion and produced
            # all artifacts.  Detect this case and treat it as success so the
            # agentic loop can evaluate the actual metrics instead of being
            # blocked by the execution_status hard gate.
            exc_msg = str(exc).lower()
            is_deferred = "deferred" in exc_msg and (
                "drc" in exc_msg or "lvs" in exc_msg or "error" in exc_msg
            )

            # Also check if the flow actually produced a state_out — that
            # means it ran to completion despite the deferred errors.
            final_state_out = None
            if is_deferred:
                found = self._find_state_out(workspace_dir)
                if found:
                    dest = os.path.join(attempt_dir, "state_out.json")
                    shutil.copy2(found, dest)
                    final_state_out = dest

            if is_deferred and final_state_out:
                logger.info(
                    "LibreLane deferred errors (flow completed): %s",
                    exc,
                )
                return ExecutionResult(
                    execution_status="success",
                    exit_code=0,
                    runtime_seconds=runtime,
                    attempt_dir=attempt_dir,
                    workspace_dir=workspace_dir,
                    artifacts_dir=artifacts_dir,
                    state_out_path=final_state_out,
                    stderr_tail=stderr_tail,
                    error_summary=f"Deferred violations: {exc}",
                )

            return ExecutionResult(
                execution_status="tool_crash",
                exit_code=1,
                runtime_seconds=runtime,
                attempt_dir=attempt_dir,
                workspace_dir=workspace_dir,
                artifacts_dir=artifacts_dir,
                state_out_path=None,
                stderr_tail=stderr_tail,
                error_summary=f"LibreLane error: {exc}",
            )

    # ------------------------------------------------------------------
    # LibreLane invocation
    # ------------------------------------------------------------------

    async def _run_librelane(
        self,
        *,
        config_path: str,
        stage_spec: StageSpec,
        patch: dict[str, Any],
        attempt_tag: str,
        workspace_dir: str,
        state_in_path: Optional[str] = None,
    ) -> Optional[str]:
        """Create a Classic flow, apply patches, run the stage in a thread.

        Uses the Flow constructor to handle config loading, and passes
        config_vars patches as ``config_override_strings`` in the
        ``KEY=VALUE`` format that LibreLane supports natively.

        Parameters
        ----------
        state_in_path:
            Path to a ``state_out.json`` from a previous stage.  When provided,
            the state is loaded and passed as ``with_initial_state`` so
            LibreLane can find prior design artifacts (netlist, ODB, etc.).

        Returns the path to state_out.json if found.
        """
        if Flow is None:
            raise ImportError(
                "LibreLane is required for LibreLaneLocalAdapter. "
                "Install with: pip install librelane  "
                "(see https://librelane.readthedocs.io/en/latest/)"
            )

        # Get the Classic flow class via factory
        ClassicFlow = Flow.factory.get("Classic")  # type: ignore[union-attr]  # noqa: N806
        if ClassicFlow is None:
            raise RuntimeError("LibreLane 'Classic' flow not found in factory")

        # Build config override strings from patch["config_vars"]
        config_vars = patch.get("config_vars", {})
        override_strings = [f"{k}={v}" for k, v in config_vars.items()]

        # Materialize SDC fragment files and inject via PNR_SDC_FILE
        sdc_edits = patch.get("sdc_edits", [])
        if sdc_edits:
            sdc_paths = self._materialize_sdc_fragments(
                sdc_edits, Path(workspace_dir)
            )
            if sdc_paths:
                # LibreLane's PNR_SDC_FILE accepts a list of SDC files.
                # Append agent fragments to existing SDC constraints.
                sdc_str = " ".join(str(p) for p in sdc_paths)
                override_strings.append(f"PNR_SDC_FILE={sdc_str}")
                logger.info(
                    "Injecting %d SDC fragment(s) via PNR_SDC_FILE: %s",
                    len(sdc_paths),
                    sdc_str,
                )

        # Build flow constructor kwargs
        flow_kwargs: dict[str, Any] = {
            "config": config_path,
            "pdk": self.pdk,
            "config_override_strings": override_strings if override_strings else None,
        }
        if self.pdk_root:
            flow_kwargs["pdk_root"] = self.pdk_root
        if self.scl:
            flow_kwargs["scl"] = self.scl
        if self.design_dir:
            flow_kwargs["design_dir"] = self.design_dir

        # Create the flow instance
        flow = ClassicFlow(**flow_kwargs)

        # Load initial state from previous stage if provided
        initial_state = None
        if state_in_path and os.path.isfile(state_in_path):
            from librelane.state import State  # type: ignore[import-untyped]

            with open(state_in_path) as f:
                initial_state = State.loads(f.read())
            logger.info("Loaded initial state from %s", state_in_path)

        # Run in a thread to avoid blocking the event loop.
        # flow.start() returns the final State; frm/to are passed
        # through **kwargs to SequentialFlow.run().
        # _force_run_dir redirects LibreLane's output into the workspace
        # directory (instead of {design_dir}/runs/{tag}/).
        await asyncio.to_thread(
            flow.start,
            with_initial_state=initial_state,
            tag=attempt_tag,
            _force_run_dir=workspace_dir,
            frm=stage_spec.first_step,
            to=stage_spec.last_step,
        )

        # Try to find state_out.json from the last step in the workspace
        return self._find_state_out(workspace_dir)

    # ------------------------------------------------------------------
    # Artifact collection
    # ------------------------------------------------------------------

    def _collect_artifacts(self, workspace_dir: str, artifacts_dir: str) -> None:
        """Copy report and output files from workspace into artifacts dir."""
        workspace_path = Path(workspace_dir)
        artifacts_path = Path(artifacts_dir)

        if not workspace_path.is_dir():
            return

        for pattern in _REPORT_GLOBS:
            for f in workspace_path.rglob(pattern):
                if f.is_file():
                    dest = artifacts_path / f.name
                    # Avoid overwriting (keep first found)
                    if not dest.exists():
                        try:
                            shutil.copy2(f, dest)
                        except OSError:
                            logger.debug("Failed to copy artifact: %s", f)

    def _find_state_out(self, search_dir: str) -> Optional[str]:
        """Find the last step's state_out.json in the directory tree.

        LibreLane creates numbered step directories (e.g. ``01-verilator-lint``,
        ``09-checker-netlistassignstatements``).  We need the state_out.json
        from the highest-numbered directory (the last step that ran).
        """
        candidates = sorted(
            Path(search_dir).rglob("state_out.json"),
            key=lambda p: p.parent.name,
        )
        for path in reversed(candidates):
            if path.is_file():
                return str(path)
        return None

    @staticmethod
    def _materialize_sdc_fragments(
        sdc_edits: list[dict[str, Any]],
        workspace_dir: Path,
    ) -> list[Path]:
        """Write SDC edit fragments to files in the workspace.

        Each SDC edit is written to a file named after ``sdc_edit["name"]``
        inside ``workspace_dir/constraints/``.  Returns the list of
        written file paths.
        """
        constraints_dir = workspace_dir / "constraints"
        constraints_dir.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []

        for sdc_edit in sdc_edits:
            name = sdc_edit.get("name", "agent_fragment.sdc")
            lines = sdc_edit.get("lines", [])
            if not lines:
                continue
            fragment_path = constraints_dir / name
            content = "\n".join(lines) + "\n"
            fragment_path.write_text(content)
            paths.append(fragment_path)
            logger.debug("Wrote SDC fragment: %s (%d lines)", fragment_path, len(lines))

        return paths

    def _capture_stderr(self, workspace_dir: str, exception_text: str) -> str:
        """Capture stderr from log files and exception text."""
        lines: list[str] = [exception_text]

        # Look for log files in workspace
        workspace_path = Path(workspace_dir)
        if workspace_path.is_dir():
            for log_file in workspace_path.rglob("*.log"):
                try:
                    content = log_file.read_text(errors="replace")
                    # Take last 50 lines
                    tail = "\n".join(content.splitlines()[-50:])
                    if tail:
                        lines.append(f"\n--- {log_file.name} (tail) ---\n{tail}")
                except OSError:
                    continue

        return "\n".join(lines)[-2000:]  # Limit to 2000 chars
