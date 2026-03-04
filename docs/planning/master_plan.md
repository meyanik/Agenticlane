# AgenticLane Master Build Plan

> **Purpose:** Complete blueprint for building AgenticLane from scratch. Any coding agent or developer should be able to pick up this document and build the project correctly.
>
> **Companion documents:**
> - `AgenticLane_Build_Spec_v0.6_FINAL.md` -- The prescriptive spec (source of truth for behavior)
> - `LIBRELANE_INTEGRATION.md` -- LibreLane interface reference
> - `ARCHITECTURE.md` -- System architecture and data flow
> - `SPEC_GAPS.md` -- Identified gaps and resolutions
> - `TECH_DECISIONS.md` -- Key technical decisions

---

## Project Summary

AgenticLane is a local-first, multi-agent orchestration layer that wraps **LibreLane** (successor to OpenLane 2, maintained by the FOSSi Foundation) as its deterministic RTL-to-GDS execution engine. It adds an agentic control plane that iterates, backtracks, and uses LLM-powered judge-driven evaluation to improve chip design quality -- while preventing constraint cheating and maintaining full reproducibility.

**Current state:** No code exists. Only the v0.6 spec and these planning documents.

**Language:** Python 3.10+
**Build approach:** Phase-by-phase, with full tests per phase before advancing.

---

## Phase 0: Project Bootstrap

### Goal
Buildable, testable, lintable skeleton. `pip install -e .` works, `agenticlane --help` prints, `pytest` passes with 0 tests.

### Deliverables

**`pyproject.toml`**
```toml
[project]
name = "agenticlane"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "pydantic>=2.0,<3",
    "pydantic-settings>=2.0,<3",
    "litellm>=1.0",
    "instructor>=1.0",
    "typer[all]>=0.9",
    "rich>=13.0",
    "pyyaml>=6.0",
    "zstandard>=0.20",
    "jinja2>=3.1",
    "aiofiles>=23.0",
]

[project.optional-dependencies]
librelane = ["librelane>=2.4"]
knowledge = ["chromadb>=0.4"]
dashboard = ["fastapi>=0.100", "uvicorn>=0.23"]
dev = [
    "pytest>=7.0",
    "pytest-asyncio>=0.21",
    "pytest-cov>=4.0",
    "hypothesis>=6.0",
    "ruff>=0.1",
    "mypy>=1.5",
]

[project.scripts]
agenticlane = "agenticlane.cli.main:app"
```

**Package directory structure** (all with `__init__.py`):
```
agenticlane/
  __init__.py              # __version__ = "0.1.0"
  cli/
    __init__.py
    main.py                # Typer app: init, run, report, dashboard, replay
    commands/
      __init__.py
  config/
    __init__.py
    models.py              # Pydantic config models
    loader.py              # Config merge chain
    knobs.py               # KnobSpec registry
    defaults/
      safe.yaml
      balanced.yaml
      aggressive.yaml
  orchestration/
    __init__.py
    orchestrator.py        # Core async loop
    scheduler.py           # Branch manager + parallel scheduler
    graph.py               # Stage graph + rollback edges
    policies.py            # Rollback, deadlock, plateau policies
    compaction.py          # History compaction
    initialization.py      # Zero-shot Attempt 0
    events.py              # Event system
    gc.py                  # Artifact GC
    constraint_guard.py    # ConstraintGuard validator
    cognitive_retry.py     # Cognitive retry loop
  schemas/
    __init__.py
    patch.py               # Patch, PatchRejected
    metrics.py             # MetricsPayload
    evidence.py            # EvidencePack
    constraints.py         # ConstraintDigest
    execution.py           # ExecutionResult, ExecutionStatus
    judge.py               # JudgeVote, JudgeAggregate
    llm.py                 # LLMCallRecord
  execution/
    __init__.py
    adapter.py             # ExecutionAdapter ABC
    workspaces.py          # Workspace/attempt dir manager
    librelane_local.py     # Local LibreLane adapter
    librelane_docker.py    # Docker LibreLane adapter
    state_handoff.py       # State baton I/O
    state_rebase.py        # Path rebasing (tokenized)
    grid_snap.py           # Macro grid snap
    artifacts.py           # Artifact classification
    patch_materialize.py   # 10-step materialization pipeline
  distill/
    __init__.py
    registry.py            # Extractor registration + dispatch
    normalize.py           # Percent-over-baseline normalization
    evidence.py            # EvidencePack assembly
    extractors/
      __init__.py
      timing.py
      area.py
      route.py
      drc.py
      lvs.py
      power.py
      runtime.py
      crash.py
      spatial.py
      constraints.py
  agents/
    __init__.py
    llm_provider.py        # LiteLLM + instructor wrapper
    master.py              # Master agent
    logging.py             # LLM call JSONL logging
    workers/
      __init__.py
      base.py              # Worker base class
      synth.py
      floorplan.py
      placement.py
      cts.py
      routing.py
    specialists/
      __init__.py
      timing.py
      routability.py
      drc.py
    prompts/
      # Jinja2 templates (.j2 files)
  judge/
    __init__.py
    schemas.py             # Vote/aggregate schemas
    ensemble.py            # Majority voting
    scoring.py             # Composite scoring + anti-cheat
  knowledge/
    __init__.py
    rag_interface.py
    chroma_adapter.py
  ui/
    __init__.py
    dashboard/
      __init__.py
      app.py
      static/
      templates/
tests/
  __init__.py
  conftest.py              # Shared fixtures
  mocks/
    __init__.py
    mock_adapter.py        # MockExecutionAdapter
    mock_llm.py            # MockLLMProvider
  golden/                  # Golden test data
  unit/
    __init__.py
  integration/
    __init__.py
```

**Config files:**
- `.gitignore` -- Python standard + runs/ + .env
- `ruff.toml` -- line-length=100, Python 3.10 target
- `mypy.ini` -- strict mode

### Steps
1. Create all directories and `__init__.py` files
2. Write `pyproject.toml` with full dependency list
3. Write `agenticlane/cli/main.py` with Typer skeleton (all commands as stubs)
4. Write config files (`.gitignore`, `ruff.toml`, `mypy.ini`)
5. Write `tests/conftest.py` with basic fixtures
6. Verify: `pip install -e ".[dev]"`, `agenticlane --help`, `pytest`, `ruff check`, `mypy`

---

## Phase 1: Deterministic Backbone (no LLM)

### Goal
Execute LibreLane stages in isolated directories, distill results into canonical schemas, manage state baton handoff, garbage collect artifacts. No LLM calls -- the orchestrator runs stages with default configs.

### Sub-task Dependency Graph
```
P1.1 Config Models ─────┐
                         ├──> P1.2 Config Loader
P1.3 Canonical Schemas ──┤
                         ├──> P1.4 Stage/Knob Registries
P1.5 ExecutionAdapter ───┤
ABC + Mock Adapter ──────┤
                         ├──> P1.7 Workspace Manager
P1.8 State Baton ────────┤
                         ├──> P1.9 Distillation Layer
                         ├──> P1.10 Artifact GC
                         │
                         └──> P1.11 Orchestrator (sequential, no LLM)
                                │
                                └──> P1.12 CLI
```

### P1.1 Config Models (`agenticlane/config/models.py`)

Implement the full config skeleton from spec lines 328-527 as Pydantic v2 models.

**Key models:**
```python
class ProjectConfig(BaseModel):
    name: str
    run_id: str = "auto"
    output_dir: Path = Path("./runs")

class DesignConfig(BaseModel):
    librelane_config_path: Path
    pdk: str = "sky130A"

class ExecutionConfig(BaseModel):
    mode: Literal["local", "docker"] = "local"
    tool_timeout_seconds: int = 21600
    workspace: WorkspaceConfig
    docker: Optional[DockerConfig] = None

class IntentConfig(BaseModel):
    prompt: str = ""
    weights_hint: Dict[str, float] = {"timing": 0.7, "area": 0.3}

# ... (all sections from the spec config skeleton)

class AgenticLaneConfig(BaseModel):
    """Root config model. All fields have safe defaults."""
    project: ProjectConfig
    design: DesignConfig
    execution: ExecutionConfig
    intent: IntentConfig
    initialization: InitializationConfig
    flow_control: FlowControlConfig
    parallel: ParallelConfig
    action_space: ActionSpaceConfig
    constraints: ConstraintsConfig
    distill: DistillConfig
    judging: JudgingConfig
    scoring: ScoringConfig
    artifact_gc: ArtifactGCConfig
    llm: LLMConfig
```

**Validators to include:**
- `CLOCK_PERIOD` must be positive
- `max_parallel_jobs` <= `max_parallel_branches`
- `physical_attempts_per_stage` >= 1
- `scoring.normalization.epsilon` > 0
- Constraint mode consistency (if constraints locked, SDC mode should be templated or restricted)

**Tests:**
- Default config validates successfully
- Each profile YAML loads and validates
- Invalid values raise ValidationError
- Config merge produces correct precedence

### P1.2 Config Loader (`agenticlane/config/loader.py`)

```python
def load_config(
    profile: str = "safe",
    user_config_path: Optional[Path] = None,
    cli_overrides: Optional[Dict[str, Any]] = None,
) -> AgenticLaneConfig:
    """Load config with merge chain: profile -> user -> CLI -> env."""
```

**Default profiles** (`agenticlane/config/defaults/`):
- `safe.yaml`: SDC templated, Tcl disabled, all constraints locked, parallel off
- `balanced.yaml`: SDC restricted_freeform, Tcl disabled, constraints locked, parallel on (2 branches)
- `aggressive.yaml`: SDC restricted_freeform, Tcl restricted_freeform, parallel on (3 branches)

### P1.3 Canonical Schemas (`agenticlane/schemas/`)

Implement all schemas from Appendix A of the spec. Each schema is a Pydantic model with `schema_version` field and JSON serialization.

**Files and their models:**
- `patch.py`: `Patch` (v5), `MacroPlacement`, `SDCEdit`, `TclEdit`, `PatchRejected` (v1)
- `metrics.py`: `MetricsPayload` (v3), `TimingMetrics`, `PhysicalMetrics`, `RouteMetrics`, `SignoffMetrics`, `RuntimeMetrics`
- `evidence.py`: `EvidencePack`, `SpatialHotspot`, `ErrorWarning`
- `constraints.py`: `ConstraintDigest` (v1), `ClockDefinition`, `ExceptionCounts`
- `execution.py`: `ExecutionStatus` (literal), `ExecutionResult` (dataclass)
- `judge.py`: `JudgeVote`, `JudgeAggregate`, `BlockingIssue`
- `llm.py`: `LLMCallRecord`

### P1.4 Stage/Knob Registries

**`agenticlane/orchestration/graph.py`:**
```python
@dataclass
class StageSpec:
    name: str                      # e.g., "SYNTH"
    librelane_steps: list[str]     # ordered step IDs
    first_step: str                # for --from
    last_step: str                 # for --to
    required_outputs: list[str]    # DesignFormat names
    rollback_targets: list[str]    # stage names
    relevant_metrics: list[str]
    typical_failures: list[str]

STAGE_GRAPH: dict[str, StageSpec] = {
    "SYNTH": StageSpec(
        name="SYNTH",
        librelane_steps=[
            "Verilator.Lint", "Checker.LintTimingConstructs",
            "Checker.LintErrors", "Checker.LintWarnings",
            "Yosys.JsonHeader", "Yosys.Synthesis",
            "Checker.YosysUnmappedCells", "Checker.YosysSynthChecks",
            "Checker.NetlistAssignStatements"
        ],
        first_step="Verilator.Lint",
        last_step="Checker.NetlistAssignStatements",
        required_outputs=["NETLIST"],
        rollback_targets=[],
        relevant_metrics=["cell_count", "area"],
        typical_failures=["unmapped_cells", "synthesis_error"]
    ),
    # ... all 10 stages (see LIBRELANE_INTEGRATION.md for full mapping)
}

ROLLBACK_EDGES: dict[str, list[str]] = {
    "ROUTE_DETAILED": ["ROUTE_GLOBAL", "PLACE_DETAILED", "FLOORPLAN"],
    "CTS": ["PLACE_DETAILED"],
    "SIGNOFF": ["ROUTE_DETAILED", "FLOORPLAN"],
}

STAGE_ORDER: list[str] = [
    "SYNTH", "FLOORPLAN", "PDN", "PLACE_GLOBAL", "PLACE_DETAILED",
    "CTS", "ROUTE_GLOBAL", "ROUTE_DETAILED", "FINISH", "SIGNOFF"
]
```

**`agenticlane/config/knobs.py`:**
```python
@dataclass
class KnobSpec:
    name: str                      # LibreLane variable name
    dtype: type                    # int, float, str, bool
    range_min: Optional[float]
    range_max: Optional[float]
    default: Any
    pdk_overrides: dict[str, dict]  # pdk_name -> {range_min, range_max, default}
    safety_tier: Literal["safe", "moderate", "expert"]
    is_constraint: bool = False
    locked_by_default: bool = False
    cheat_risk: bool = False
    stage_applicability: list[str]  # which stages this knob applies to

KNOB_REGISTRY: dict[str, KnobSpec] = {
    "FP_CORE_UTIL": KnobSpec(
        name="FP_CORE_UTIL", dtype=int, range_min=20, range_max=80,
        default=50, pdk_overrides={"sky130A": {"default": 45}},
        safety_tier="safe", stage_applicability=["FLOORPLAN"]
    ),
    "PL_TARGET_DENSITY_PCT": KnobSpec(
        name="PL_TARGET_DENSITY_PCT", dtype=int, range_min=20, range_max=95,
        default=60, pdk_overrides={},
        safety_tier="safe", stage_applicability=["PLACE_GLOBAL"]
    ),
    "CLOCK_PERIOD": KnobSpec(
        name="CLOCK_PERIOD", dtype=float, range_min=0.1, range_max=1000.0,
        default=10.0, pdk_overrides={},
        safety_tier="expert", is_constraint=True,
        locked_by_default=True, cheat_risk=True,
        stage_applicability=["SYNTH", "FLOORPLAN", "PLACE_GLOBAL", "CTS", "ROUTE_GLOBAL", "ROUTE_DETAILED"]
    ),
    # ... populate from LibreLane's common_variables.py
    # Key knobs to include:
    # SYNTH: SYNTH_STRATEGY, SYNTH_MAX_FANOUT, SYNTH_BUFFERING, SYNTH_SIZING
    # FLOORPLAN: FP_CORE_UTIL, FP_ASPECT_RATIO, FP_SIZING, FP_PDN_*
    # PLACEMENT: PL_TARGET_DENSITY_PCT, PL_ROUTABILITY_DRIVEN, PL_RESIZER_*
    # CTS: CTS_CLK_MAX_WIRE_LENGTH, CTS_SINK_CLUSTERING_*, CTS_DISTANCE
    # ROUTING: GRT_ADJUSTMENT, GRT_OVERFLOW_ITERS, DRT_OPT_ITERS
}
```

### P1.5 Execution Adapter (`agenticlane/execution/adapter.py`)

Abstract base class -- implement exactly as specified in spec lines 606-641.

**`agenticlane/execution/librelane_local.py`:**
```python
class LibreLaneLocalAdapter(ExecutionAdapter):
    """Runs LibreLane stages locally using the Python API."""

    async def run_stage(self, *, run_root, stage_name, librelane_config_path,
                        resolved_design_config_path, patch, state_in_path,
                        attempt_dir, timeout_seconds) -> ExecutionResult:
        # 1. Load LibreLane config
        # 2. Apply patch via Config.with_increment(patch["config_vars"])
        # 3. Resolve --from/--to step IDs from STAGE_GRAPH[stage_name]
        # 4. Create Classic flow
        # 5. Call flow.start(frm=first_step, to=last_step) with timeout
        # 6. Capture state_out.json, artifacts
        # 7. Handle crash/timeout/OOM -> appropriate ExecutionStatus
        # 8. Return ExecutionResult
```

**`tests/mocks/mock_adapter.py`:**
- Configurable per-stage: success probability, metric ranges, failure modes
- Deterministic: given same knobs, produces same metrics (with small noise)
- Responds to knob changes: e.g., lower FP_CORE_UTIL -> larger area but less congestion
- Produces realistic directory structure with synthetic files

### P1.6-P1.12 (Remaining sub-tasks)

See the detailed descriptions in the plan file. Key implementation notes:

**Workspace Manager (P1.7):** Use `os.link()` for hardlink cloning, fall back to `shutil.copytree()`. Create attempt dirs atomically.

**State Baton (P1.8):** Parse LibreLane's `State` JSON format. Tokenize paths as `{{RUN_ROOT}}/relative/path`. The `state_rebase_map.json` logs every path transformation.

**Distillation (P1.9):** Each extractor reads LibreLane output files from the attempt directory. Start with parsing OpenROAD STA report format for timing, state metrics for area/utilization. The CrashDistiller must never itself crash -- wrap everything in try/except and produce a valid MetricsPayload with null metrics.

**GC (P1.10):** Classify files by suffix:
- Ledger: `.json`, `.jsonl`, `.md` (always keep)
- Medium: `.rpt`, `.log` (error sections only)
- Heavy: `.odb`, `.def`, `.spef`, `.gds`, `.spice` (GC candidates)

**Orchestrator (P1.11):** Async main loop:
```python
async def run_flow(self, config: AgenticLaneConfig):
    for stage_name in STAGE_ORDER:
        for attempt in range(1, config.flow_control.budgets.physical_attempts_per_stage + 1):
            attempt_dir = self.workspace.create_attempt_dir(stage_name, attempt)
            result = await self.adapter.run_stage(...)
            metrics, evidence = await self.distill(attempt_dir, result)
            passed = self.check_gates(metrics, evidence)
            if passed:
                self.checkpoint(stage_name, attempt_dir)
                break
        else:
            # Budget exhausted -- handle per policy
            ...
```

### Acceptance Criteria
- [ ] Execute a stage in an isolated attempt directory
- [ ] Crash distiller outputs metrics/evidence on tool failure
- [ ] State baton handoff works between stages
- [ ] GC prunes failed heavy artifacts safely

---

## Phase 2: ConstraintGuard + Cognitive Retry

### Goal
Prevent LLM-driven constraint cheating across all channels (config_vars, SDC, Tcl). Implement the cognitive retry loop so invalid patches don't burn physical attempt budget.

### Key Implementation Details

**ConstraintGuard (`agenticlane/orchestration/constraint_guard.py`):**
```python
class ConstraintGuard:
    def validate(self, patch: Patch, config: AgenticLaneConfig) -> Union[Pass, PatchRejected]:
        # 1. Check config_vars against locked_vars
        # 2. Check sdc_edits against SDC restricted dialect
        # 3. Check tcl_edits against Tcl restricted dialect (if enabled)
        # Returns PatchRejected with offending_channel, offending_commands, remediation_hint
```

**Line continuation preprocessing** (spec lines 893-903):
```python
def join_line_continuations(text: str, max_joined: int = 32) -> list[str]:
    # 1. Normalize newlines
    # 2. Split into lines
    # 3. Join lines ending with backslash
    # 4. Enforce max_joined_lines limit
    # 5. Reject unterminated continuations (if configured)
```

**SDC scanner** -- for each logical line:
1. Skip empty lines and comment lines
2. Reject semicolons and inline comments
3. Extract first token as command
4. Reject if command in deny list (derived from locked_aspects via Appendix B)
5. Parse bracket expressions `[...]`: allow only `get_ports`, `get_pins`, `get_nets`, `get_cells`, `get_clocks`, `all_inputs`, `all_outputs`, `all_clocks`
6. Reject nested brackets, forbidden tokens (`eval`, `source`, `exec`, etc.)

**Cognitive retry loop** (`agenticlane/orchestration/cognitive_retry.py`):
```python
async def run_with_cognitive_retry(self, stage, attempt_dir, agent, context):
    for try_num in range(1, max_cognitive_retries + 1):
        proposal_dir = attempt_dir / "proposals" / f"try_{try_num:03d}"
        patch = await agent.propose_patch(context, feedback=last_rejection)
        save(proposal_dir / "patch_proposed.json", patch)

        result = self.constraint_guard.validate(patch, self.config)
        if isinstance(result, PatchRejected):
            save(proposal_dir / "patch_rejected.json", result)
            last_rejection = result
            continue

        save(attempt_dir / "patch.json", patch)
        return patch  # accepted

    # All cognitive retries exhausted
    save(attempt_dir / "patch_rejected_final.json", last_rejection)
    return None
```

**Patch materialization** (`agenticlane/execution/patch_materialize.py`):
Execute the mandatory 10-step order from spec lines 643-657. Steps 1-3 (schema validation, knob range validation, ConstraintGuard) must reject before any EDA tool runs.

### Acceptance Criteria
- [ ] Forbidden SDC command (e.g., `create_clock`) rejected without burning physical budget
- [ ] Line continuation join prevents bypass (e.g., `cre\\\nate_clock`)
- [ ] `read_sdc` in Tcl hook rejected when constraints are locked
- [ ] Proposals recorded deterministically in `attempt_dir/proposals/try_NNN/`

---

## Phase 3: Single-Stage Agent Loop

### Goal
LLM-powered patch generation and judge-driven evaluation for PLACE_GLOBAL stage. Demonstrate metrics improvement across retries.

### LLM Provider Stack
```
AgenticLane Code
       |
       v
LLMProvider (agenticlane/agents/llm_provider.py)
  - async interface
  - call logging (JSONL)
  - response hashing (SHA256)
  - reproducibility mode (temp/seed)
       |
       v
instructor (Pydantic schema enforcement)
  - response_model=PatchModel
  - automatic retries on validation failure
  - max_retries from config
       |
       v
litellm (provider abstraction)
  - supports 100+ providers
       |
       +---> LM Studio (localhost:1234)
       +---> Ollama (localhost:11434)
       +---> OpenAI API
       +---> Anthropic API
```

**Configuration for local LM Studio:**
```yaml
llm:
  mode: local
  provider: litellm
  models:
    worker: "openai/local-model"  # LiteLLM routes to LM Studio
    judge: ["openai/local-model"]
  # LiteLLM will use OPENAI_API_BASE=http://localhost:1234/v1
```

### Prompt Engineering

**Worker prompt structure** (Jinja2 template):
```
SYSTEM: You are an ASIC physical design engineer working on the {{stage}} stage.
Your job is to propose configuration changes that improve {{intent_summary}}.

CONSTRAINTS:
- You may only modify these knobs: {{allowed_knobs_table}}
- You MUST NOT modify: {{locked_constraints}}
- All values must be within the specified ranges.

CURRENT STATE:
{{metrics_table}}

EVIDENCE:
{{evidence_summary}}

HISTORY:
{{lessons_learned_table}}

Respond with a JSON patch proposal following this schema:
{{patch_schema}}
```

**Judge prompt structure:**
```
SYSTEM: You are a senior ASIC design reviewer. Evaluate whether this design iteration
should PASS or FAIL based on the metrics and evidence.

BEFORE (previous attempt):
{{prev_metrics}}

AFTER (current attempt):
{{curr_metrics}}

EVIDENCE:
{{evidence_summary}}

CONSTRAINT DIGEST:
{{constraint_digest_summary}}

Vote PASS or FAIL. If FAIL, cite specific metric keys as blocking issues.
Respond with JSON following this schema: {{vote_schema}}
```

### Scoring Formula

Composite score = weighted sum of normalized per-metric scores:

```python
score = sum(
    weight * normalize(metric_value, baseline_value)
    for metric, weight in intent.weights_hint.items()
)

def normalize(value, baseline, epsilon=1e-6, clamp=1.0):
    """Percent improvement over baseline, clamped."""
    if baseline is None or abs(baseline) < epsilon:
        return 0.0
    improvement = (baseline - value) / (abs(baseline) + epsilon)  # lower is better
    return max(-clamp, min(clamp, improvement))
```

For timing: use effective setup period (anti-cheat):
```python
effective_setup_period = applied_clock_period - setup_wns  # from ConstraintDigest
```

### Acceptance Criteria
- [ ] Placement stage shows metrics improvement across 3-5 retries
- [ ] `lessons_learned.md` table generated with attempt history
- [ ] LLM calls logged to `llm_calls.jsonl`
- [ ] Judge ensemble votes recorded

---

## Phase 4: Rollback + Spatial Actuator

### Goal
Cross-stage rollback (routing failure -> floorplan re-run) and macro placement adjustment from spatial hotspot evidence.

### Rollback Engine

When routing fails with congestion:
1. Master agent receives cross-stage metrics and evidence
2. Master decides: retry current stage, or rollback to FLOORPLAN
3. If rollback: select the best prior FLOORPLAN checkpoint as state baton
4. Resume flow from FLOORPLAN with specialist advice

### Spatial Actuator

Macro placement changes without Tcl -- uses LibreLane's `MACRO_PLACEMENT_CFG`:
1. Spatial extractor identifies congestion hotspots (grid bins)
2. Worker proposes `macro_placements[]` in patch
3. Grid snap: coordinates snapped to placement site grid (from tech LEF SITE)
4. Collision detection: sorted instance names, deterministic offsets
5. Write to `MACRO_PLACEMENT_CFG` format for LibreLane

### Acceptance Criteria
- [ ] Routing congestion complaint triggers macro move proposal
- [ ] Rollback from ROUTE_DETAILED to FLOORPLAN works with correct state baton

---

## Phase 5: Full Flow + Parallel Branches

### Goal
End-to-end 10-stage flow with parallel branch exploration, pruning, and selection.

### Branch Model
- Each branch is a timeline of stages and attempts, diverging by patch stacks
- Branches run concurrently with `asyncio.Semaphore(max_parallel_jobs)`
- Each branch has isolated directories
- Pruning: if branch score < best - `prune_delta_score` for `prune_patience_attempts`, prune it

### Full Flow Features
- Zero-shot initialization (Attempt 0): Master compiles IntentProfile -> `global_init_patch.json`
- Plateau detection: sliding window of scores, trigger specialist agents
- Cycle detection: hash of (patch + key_overrides), detect repeats
- Deadlock policy: `ask_human` / `auto_relax` / `stop`
- Reproducibility: `manifest.json` with full provenance

### Report + Dashboard
- CLI report: rich terminal tables with branch comparison, best metrics
- Dashboard: FastAPI + Jinja2, reads run folder JSON, displays timelines/plots/votes

### Acceptance Criteria
- [ ] 3 parallel branches execute in isolated directories
- [ ] Pruning removes underperforming branches
- [ ] Best branch selected based on composite score
- [ ] `manifest.json` contains complete provenance

---

## Testing Strategy

### Test Pyramid
```
         /  E2E  \         2-3 tests: full flow with mock adapter + mock LLM
        /----------\
       / Integration \      10-15 tests: component combinations
      /----------------\
     /   Unit Tests      \   100+ tests: individual functions
    /----------------------\
   / Golden File Tests       \ 20+ tests: known inputs -> expected outputs
  /----------------------------\
```

### Critical Mocks

**MockExecutionAdapter** (`tests/mocks/mock_adapter.py`):
- Configurable per-stage behavior
- Deterministic metric generation based on config knobs
- Simulates improvement: lower FP_CORE_UTIL -> larger area, less congestion
- Failure injection: crash, timeout, OOM modes
- Produces realistic directory structure

**MockLLMProvider** (`tests/mocks/mock_llm.py`):
- Returns pre-recorded responses by prompt hash
- Can return Pydantic models directly
- Records all calls for assertion
- Simulates validation failures for testing retries

### Property-Based Testing (hypothesis)
- ConstraintGuard: fuzz SDC/Tcl inputs to find bypass vectors
- Grid snap: verify output always on valid grid
- Path rebasing: tokenize/detokenize roundtrip
- Scoring: normalization always in [-clamp, clamp]

### CI Pipeline
- **Fast CI (every PR):** ruff + mypy + unit + golden + ConstraintGuard tests
- **Nightly CI:** integration tests with mock adapter + mock LLM, full flow E2E
- **Weekly CI:** real LibreLane on sky130/gf180 small designs (when available)

---

## Risk Register

| # | Risk | Severity | Likelihood | Mitigation |
|---|------|----------|------------|------------|
| 1 | Local LLM (7B-30B) fails to produce valid structured JSON patches | High | Medium | instructor retries + JSON extraction fallback + template-based patch generation fallback |
| 2 | LibreLane report format changes between versions | Medium | Medium | Lenient parsing + `missing_report_policy: record_and_continue` + version pinning |
| 3 | Concurrent branch filesystem conflicts | Medium | Low | Per-attempt directory isolation (spec R9) + filesystem locks for GC |
| 4 | KnobSpec incomplete for PDKs beyond sky130 | Medium | High | Start with sky130, extract programmatically from LibreLane's `Variable` class |
| 5 | Prompt engineering requires extensive iteration | Medium | High | Start simple, iterate with mock adapter, collect failure modes |
| 6 | Large designs cause memory/disk pressure | Medium | Medium | GC policy, disk limits, compression, streaming parsers |

---

## Verification Checklist (per phase)

After completing each phase:
1. All spec acceptance tests pass
2. Full test suite green (`pytest --cov`)
3. Type checking passes (`mypy --strict`)
4. Linting passes (`ruff check`)
5. CLI smoke test with relevant commands
6. Phase 3+: test with real LM Studio model against mock adapter
7. Phase 5: test with real LibreLane + sky130 PDK on SPM example design
