"""AgenticLane CLI - Typer-based command-line interface."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from agenticlane import __version__

app = typer.Typer(
    name="agenticlane",
    help="Multi-agent orchestration layer for LibreLane RTL-to-GDS flows.",
    no_args_is_help=True,
)
console = Console()


def version_callback(value: bool) -> None:
    if value:
        console.print(f"agenticlane {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        "-v",
        help="Show version and exit.",
        callback=version_callback,
        is_eager=True,
    ),
) -> None:
    """AgenticLane: Agentic RTL-to-GDS orchestration."""


@app.command()
def init(
    design: str = typer.Option(..., "--design", "-d", help="Design name."),
    pdk: str = typer.Option("sky130A", "--pdk", "-p", help="PDK name."),
    output_dir: Path = typer.Option(
        ".", "--output-dir", "-o", help="Directory to create project in."
    ),
) -> None:
    """Initialize a new AgenticLane project."""
    project_dir = output_dir / design
    project_dir.mkdir(parents=True, exist_ok=True)

    config_content = f"""# AgenticLane project config
project:
  name: "{design}"
  run_id: "auto"
  output_dir: "./runs"

design:
  librelane_config_path: "./design/config.yaml"
  pdk: "{pdk}"

execution:
  mode: "local"
  tool_timeout_seconds: 21600

llm:
  mode: "local"
  provider: "litellm"
"""
    config_path = project_dir / "agentic_config.yaml"
    config_path.write_text(config_content)

    design_dir = project_dir / "design"
    design_dir.mkdir(exist_ok=True)
    design_config = f"""DESIGN_NAME: {design}
VERILOG_FILES: "dir::src/*.v"
CLOCK_PORT: clk
CLOCK_PERIOD: 10.0
PDK: {pdk}
STD_CELL_LIBRARY: sky130_fd_sc_hd
# Physical parameters below are auto-calculated by agents.
# Uncomment to override:
# FP_SIZING: absolute
# DIE_AREA: [0, 0, 600, 600]
# FP_CORE_UTIL: 45
"""
    (design_dir / "config.yaml").write_text(design_config)

    src_dir = project_dir / "src"
    src_dir.mkdir(exist_ok=True)

    console.print(f"[green]Project initialized at {project_dir}[/green]")
    console.print(f"  Config: {config_path}")
    console.print(f"  Design: {design_dir / 'config.yaml'}")


@app.command()
def run(
    config: Path = typer.Argument(..., help="Path to agentic_config.yaml"),
    profile: str = typer.Option("safe", "--profile", help="Config profile."),
    stage: Optional[str] = typer.Option(None, "--stage", help="Run only this stage."),
    mock: bool = typer.Option(False, "--mock", help="Use mock execution adapter and mock LLM (for testing)."),
    model: Optional[str] = typer.Option(None, "--model", help="Override LLM model name (e.g. gemini-2.5-pro)."),
    step: Optional[str] = typer.Option(None, "--step", help="Run only this step."),
    parallel: Optional[bool] = typer.Option(
        None, "--parallel", help="Enable parallel branches."
    ),
    zero_shot: Optional[bool] = typer.Option(
        None, "--zero-shot", help="Enable zero-shot init."
    ),
    repro_mode: Optional[str] = typer.Option(
        None, "--repro-mode", help="Reproducibility mode: replay|deterministic|stochastic."
    ),
    unlock_constraint: Optional[str] = typer.Option(
        None, "--unlock-constraint", help="Unlock a constraint (dangerous)."
    ),
    sdc_mode: Optional[str] = typer.Option(
        None, "--sdc-mode", help="SDC mode: templated|restricted|expert."
    ),
    max_disk_gb: Optional[int] = typer.Option(
        None, "--max-disk-gb", help="Max disk usage in GB."
    ),
    resume: Optional[str] = typer.Option(None, "--resume", help="Resume from run ID."),
    flow_mode: Optional[str] = typer.Option(
        None, "--flow-mode", help="Flow mode: flat|hierarchical|auto."
    ),
) -> None:
    """Run the AgenticLane flow."""
    import asyncio

    # Verify config file exists
    if not config.exists():
        console.print(f"[red]Config file not found: {config}[/red]")
        raise typer.Exit(code=1)

    # Build CLI overrides from command-line options
    cli_overrides: dict[str, object] = {}
    if parallel is not None:
        cli_overrides.setdefault("parallel", {})  # type: ignore[arg-type]
        cli_overrides["parallel"] = {"enabled": parallel}  # type: ignore[index]
    if zero_shot is not None:
        cli_overrides.setdefault("initialization", {})  # type: ignore[arg-type]
        cli_overrides["initialization"] = {  # type: ignore[index]
            "zero_shot": {"enabled": zero_shot}
        }
    if repro_mode is not None:
        cli_overrides.setdefault("llm", {})  # type: ignore[arg-type]
        cli_overrides["llm"] = {"reproducibility_mode": repro_mode}  # type: ignore[index]
    if sdc_mode is not None:
        cli_overrides.setdefault("action_space", {})  # type: ignore[arg-type]
        cli_overrides["action_space"] = {"sdc": {"mode": sdc_mode}}  # type: ignore[index]
    if max_disk_gb is not None:
        cli_overrides.setdefault("artifact_gc", {})  # type: ignore[arg-type]
        cli_overrides["artifact_gc"] = {  # type: ignore[index]
            "max_run_disk_gb": max_disk_gb
        }

    # Load config via the merge chain
    from agenticlane.config.loader import load_config
    from agenticlane.config.models import AgenticLaneConfig

    config_dict = load_config(
        profile=profile,
        user_config_path=config,
        cli_overrides=cli_overrides if cli_overrides else None,
    )

    # Apply flow_mode CLI override
    if flow_mode is not None:
        config_dict.setdefault("design", {})
        if isinstance(config_dict["design"], dict):
            config_dict["design"]["flow_mode"] = flow_mode

    # Build a validated Pydantic config from the merged dict
    try:
        agentic_config = AgenticLaneConfig(**config_dict)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Config validation error: {exc}[/red]")
        raise typer.Exit(code=1) from None

    # Interactive flow mode prompt when auto and not mock
    if agentic_config.design.flow_mode == "auto" and not mock:
        from rich.prompt import Prompt

        console.print("\n[bold]Flow Mode Selection[/bold]")
        console.print("  [1] Flat (monolithic) - single top-level flow")
        console.print("  [2] Hierarchical (modular) - per-module sub-flows")
        choice = Prompt.ask(
            "Choose flow mode",
            choices=["1", "2"],
            default="1",
            console=console,
        )
        if choice == "2":
            if not agentic_config.design.modules:
                console.print(
                    "[red]Hierarchical flow requires 'design.modules' in config.[/red]"
                )
                console.print(
                    "[yellow]Define sub-modules in your agentic_config.yaml under "
                    "design.modules. See examples/picosoc_sky130/ for reference.[/yellow]"
                )
                raise typer.Exit(code=1)
            agentic_config.design.flow_mode = "hierarchical"
        else:
            agentic_config.design.flow_mode = "flat"

    # Create the execution adapter
    from agenticlane.execution.adapter import ExecutionAdapter

    adapter: ExecutionAdapter
    if mock:
        from tests.mocks.mock_adapter import MockExecutionAdapter

        adapter = MockExecutionAdapter()
    elif agentic_config.execution.mode == "docker":
        from agenticlane.execution.docker_adapter import DockerAdapter

        docker_cfg = agentic_config.execution.docker
        if not DockerAdapter.check_docker_available():
            console.print(
                "[red]Docker is not available. Ensure Docker is installed and running.[/red]"
            )
            raise typer.Exit(code=1)
        if docker_cfg and not DockerAdapter.check_image_exists(docker_cfg.image):
            console.print(
                f"[yellow]Docker image '{docker_cfg.image}' not found locally. "
                f"It will be pulled on first run.[/yellow]"
            )

        adapter = DockerAdapter(
            docker_config=docker_cfg,
            pdk=agentic_config.design.pdk,
            extra_env=agentic_config.execution.env,
        )
    else:
        from agenticlane.execution.librelane_adapter import LibreLaneLocalAdapter

        adapter = LibreLaneLocalAdapter(
            pdk=agentic_config.design.pdk,
        )

    # Create the LLM provider.
    # --mock without --model → passthrough mode (no LLM, for CI/testing).
    # --model mock → mock LLM for agentic-mode testing without API keys.
    # --model <name> → real LLM provider with given model.
    # No flags → real LLM provider with config defaults.
    from agenticlane.agents.llm_provider import LLMProvider

    llm_provider: LLMProvider | None = None
    if model == "mock":
        from tests.mocks.mock_llm import MockLLMProvider as _MockLLM

        mock_llm = _MockLLM()
        mock_llm.set_default_response({"config_vars": {}})
        llm_provider = mock_llm  # type: ignore[assignment]
    elif mock and model is None:
        # --mock without --model: passthrough mode (no LLM)
        pass
    elif agentic_config.llm.provider != "mock":
        try:
            from agenticlane.agents.litellm_provider import LiteLLMProvider

            llm_provider = LiteLLMProvider(
                config=agentic_config.llm,
                default_model=model,
            )
        except ImportError:
            console.print(
                "[yellow]litellm not installed, running without LLM provider.[/yellow]"
            )

    # Create orchestrator
    from agenticlane.orchestration.orchestrator import SequentialOrchestrator

    orchestrator = SequentialOrchestrator(
        config=agentic_config,
        adapter=adapter,
        llm_provider=llm_provider,
        resume_from=resume,
    )

    stages = [stage] if stage else None

    console.print("[bold]Starting AgenticLane flow...[/bold]")
    console.print(f"  Config: {config}")
    console.print(f"  Profile: {profile}")
    if stage:
        console.print(f"  Stage: {stage}")

    result = asyncio.run(orchestrator.run_flow(stages=stages))

    # Display results
    console.print(f"\n[bold]Flow completed: {result.run_id}[/bold]")
    console.print(f"  Stages passed: {len(result.stages_completed)}")
    console.print(f"  Stages failed: {len(result.stages_failed)}")
    if result.stages_completed:
        console.print(f"  Completed: {', '.join(result.stages_completed)}")
    if result.stages_failed:
        console.print(f"  [red]Failed: {', '.join(result.stages_failed)}[/red]")

    if not result.completed:
        raise typer.Exit(code=1)


@app.command()
def report(
    run_id: str = typer.Argument(..., help="Run ID to generate report for."),
    runs_dir: Path = typer.Option("./runs", "--runs-dir", help="Runs directory."),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Generate a report for a completed run."""
    manifest_path = runs_dir / run_id / "manifest.json"
    if not manifest_path.exists():
        console.print(f"[red]Manifest not found: {manifest_path}[/red]")
        raise typer.Exit(code=1)

    manifest = json.loads(manifest_path.read_text())

    from agenticlane.reporting.report import ReportGenerator

    run_report = ReportGenerator.from_manifest(manifest)

    if json_output:
        console.print_json(ReportGenerator.to_json(run_report))
    else:
        console.print(ReportGenerator.render_terminal(run_report))


@app.command()
def dashboard(
    runs_dir: Path = typer.Option("./runs", "--runs-dir", help="Runs directory."),
    port: int = typer.Option(8080, "--port", help="Dashboard port."),
    dev: bool = typer.Option(False, "--dev", help="Development mode (proxy to Vite dev server)."),
    examples_dir: Path = typer.Option("./examples", "--examples-dir", help="Examples directory."),
) -> None:
    """Launch the AgenticLane dashboard (React UI + API)."""
    try:
        from agenticlane.reporting.dashboard import create_dashboard_app
    except ImportError:
        console.print(
            "[red]FastAPI is required for the dashboard. "
            "Install with: pip install agenticlane[dashboard][/red]"
        )
        raise typer.Exit(code=1) from None

    app_instance = create_dashboard_app(
        Path(runs_dir),
        dev_mode=dev,
        examples_dir=Path(examples_dir) if examples_dir else None,
    )
    if dev:
        console.print(
            f"[bold]Starting dashboard API on http://localhost:{port}[/bold]\n"
            "[dim]Dev mode: run 'cd dashboard-ui && npm run dev' for React UI[/dim]"
        )
    else:
        console.print(f"[bold]Starting dashboard on http://localhost:{port}[/bold]")

    import uvicorn

    uvicorn.run(app_instance, host="127.0.0.1", port=port)


@app.command()
def replay(
    run_id: str = typer.Argument(..., help="Run ID to replay."),
    runs_dir: Path = typer.Option("./runs", "--runs-dir", help="Runs directory."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show summary only, do not re-run."),
    rerun: bool = typer.Option(False, "--rerun", help="Create a new run with the same config and seed."),
) -> None:
    """Replay a previous run: inspect its manifest or re-run with the same config."""
    from agenticlane.orchestration.manifest import ManifestBuilder

    manifest_path = runs_dir / run_id / "manifest.json"
    if not manifest_path.exists():
        console.print(f"[red]Manifest not found: {manifest_path}[/red]")
        raise typer.Exit(code=1)

    manifest = ManifestBuilder.load_manifest(manifest_path)

    # --- Print summary ---
    console.print(f"\n[bold]Run Summary: {manifest.run_id}[/bold]")
    console.print(f"  Flow mode: {manifest.flow_mode}")
    if manifest.duration_seconds is not None:
        console.print(f"  Duration: {manifest.duration_seconds:.1f}s")
    if manifest.best_branch_id:
        score_str = (
            f"{manifest.best_composite_score:.4f}"
            if manifest.best_composite_score is not None
            else "N/A"
        )
        console.print(f"  Best branch: {manifest.best_branch_id} (score: {score_str})")
    console.print(f"  Total stages: {manifest.total_stages}")
    console.print(f"  Total attempts: {manifest.total_attempts}")
    if manifest.random_seed is not None:
        console.print(f"  Seed: {manifest.random_seed}")

    # Stage decisions summary
    if manifest.decisions:
        console.print("\n[bold]Stage Decisions:[/bold]")
        seen_stages: dict[str, list[dict[str, object]]] = {}
        for d in manifest.decisions:
            stage = str(d.get("stage", "unknown"))
            if stage not in seen_stages:
                seen_stages[stage] = []
            seen_stages[stage].append(d)
        for stage_name, decisions in seen_stages.items():
            actions = [str(d.get("action", "?")) for d in decisions]
            scores: list[float] = []
            for d in decisions:
                cs = d.get("composite_score")
                if cs is not None and isinstance(cs, (int, float)):
                    scores.append(float(cs))
            best = f", best={max(scores):.4f}" if scores else ""
            actions_str = ", ".join(actions)
            console.print(
                f"  {stage_name}: {len(decisions)} decision(s) "
                f"\\[{actions_str}]{best}"
            )

    # Branch summary
    if manifest.branches:
        console.print("\n[bold]Branches:[/bold]")
        for bid, bdata in sorted(manifest.branches.items()):
            status = bdata.get("status", "unknown")
            bscore = bdata.get("best_score")
            score_str = f"{bscore:.4f}" if bscore is not None else "N/A"
            console.print(f"  {bid}: {status} (score: {score_str})")

    # Module results for hierarchical flows
    if manifest.module_results:
        console.print("\n[bold]Module Results:[/bold]")
        for mod_name, mod_info in manifest.module_results.items():
            completed = mod_info.get("completed", False)
            status = "completed" if completed else "incomplete"
            mod_score = mod_info.get("best_score")
            score_str = f"{mod_score:.4f}" if mod_score is not None else "N/A"
            console.print(f"  {mod_name}: {status} (score: {score_str})")

    if dry_run or not rerun:
        return

    # --- Rerun with same config and seed ---
    if not manifest.resolved_config:
        console.print("[red]No resolved config in manifest; cannot rerun.[/red]")
        raise typer.Exit(code=1)

    console.print("\n[bold]Re-running with same config and seed...[/bold]")

    import asyncio

    import yaml as _yaml

    from agenticlane.config.models import AgenticLaneConfig

    # Write resolved config to a temp file so the orchestrator can use it
    replay_config_path = runs_dir / run_id / "replay_config.yaml"
    replay_config_path.write_text(
        _yaml.dump(manifest.resolved_config, default_flow_style=False)
    )

    try:
        agentic_config = AgenticLaneConfig(**manifest.resolved_config)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Config validation error: {exc}[/red]")
        raise typer.Exit(code=1) from None

    # Override seed if present
    if manifest.random_seed is not None:
        agentic_config.llm.seed = manifest.random_seed

    from agenticlane.execution.adapter import ExecutionAdapter
    from agenticlane.execution.librelane_adapter import LibreLaneLocalAdapter

    adapter: ExecutionAdapter = LibreLaneLocalAdapter(
        pdk=agentic_config.design.pdk,
    )

    llm_provider = None
    if agentic_config.llm.provider != "mock":
        try:
            from agenticlane.agents.litellm_provider import LiteLLMProvider

            llm_provider = LiteLLMProvider(config=agentic_config.llm)
        except ImportError:
            console.print(
                "[yellow]litellm not installed, running without LLM provider.[/yellow]"
            )

    from agenticlane.orchestration.orchestrator import SequentialOrchestrator

    orchestrator = SequentialOrchestrator(
        config=agentic_config,
        adapter=adapter,
        llm_provider=llm_provider,
    )

    result = asyncio.run(orchestrator.run_flow())

    console.print(f"\n[bold]Replay completed: {result.run_id}[/bold]")
    console.print(f"  Stages passed: {len(result.stages_completed)}")
    console.print(f"  Stages failed: {len(result.stages_failed)}")
    if not result.completed:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
