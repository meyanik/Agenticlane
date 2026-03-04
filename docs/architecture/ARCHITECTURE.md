# AgenticLane System Architecture

> **Purpose:** Describe the system architecture, component relationships, data flow, and the three-plane separation model that governs the entire system.

---

## Three-Plane Separation

AgenticLane is organized into three planes with strict boundaries. Data flows downward through distillation; control flows upward through structured schemas.

```
┌─────────────────────────────────────────────────────────┐
│                   COGNITION PLANE                       │
│                   (LLM-powered)                         │
│                                                         │
│  ┌──────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │  Master   │  │   Worker     │  │   Specialist     │  │
│  │  Agent    │  │   Agents     │  │   Agents         │  │
│  │          │  │  (per-stage) │  │  (timing/route/  │  │
│  │ decisions│  │  patch       │  │   drc advice)    │  │
│  │ rollback │  │  proposals   │  │                  │  │
│  └────┬─────┘  └──────┬───────┘  └────────┬─────────┘  │
│       │               │                    │            │
│       │    ┌──────────┴──────────┐         │            │
│       │    │   Judge Ensemble    │         │            │
│       │    │  (majority vote)    │         │            │
│       │    └──────────┬──────────┘         │            │
│       │               │                    │            │
├───────┼───────────────┼────────────────────┼────────────┤
│       │               │                    │            │
│       │  ONLY: MetricsPayload, EvidencePack,            │
│       │  ConstraintDigest, bounded snippets,            │
│       │  lessons_learned (JSON)                         │
│       │               │                    │            │
│       │  NEVER: raw DEF, ODB, SPEF, GDS,               │
│       │  full logs, large artifacts                     │
│       │               │                    │            │
├───────┼───────────────┼────────────────────┼────────────┤
│       ▼               ▼                    ▼            │
│                   DISTILLATION PLANE                    │
│                   (deterministic)                       │
│                                                         │
│  ┌────────────────────────────────────────────────┐     │
│  │            Extractor Registry                  │     │
│  │                                                │     │
│  │  ┌─────────┐ ┌──────┐ ┌───────┐ ┌─────────┐  │     │
│  │  │ Timing  │ │ Area │ │ Route │ │   DRC   │  │     │
│  │  └────┬────┘ └──┬───┘ └───┬───┘ └────┬────┘  │     │
│  │  ┌────┴────┐ ┌──┴───┐ ┌───┴───┐ ┌────┴────┐  │     │
│  │  │  LVS   │ │Power │ │Runtime│ │  Crash  │  │     │
│  │  └────┬────┘ └──┬───┘ └───┬───┘ └────┬────┘  │     │
│  │  ┌────┴────┐ ┌──┴──────────┴──────────┴────┐  │     │
│  │  │Spatial │ │   Constraint Digest          │  │     │
│  │  │Hotspot │ │   Extractor                  │  │     │
│  │  └────────┘ └──────────────────────────────┘  │     │
│  └────────────────────┬───────────────────────────┘     │
│                       │                                 │
│               MetricsPayload                            │
│               EvidencePack                              │
│               ConstraintDigest                          │
│                       │                                 │
├───────────────────────┼─────────────────────────────────┤
│                       ▼                                 │
│                   EXECUTION PLANE                       │
│                   (deterministic)                       │
│                                                         │
│  ┌────────────────────────────────────────────────┐     │
│  │           Execution Adapter                    │     │
│  │                                                │     │
│  │  ┌──────────────┐   ┌───────────────────┐     │     │
│  │  │ LibreLane    │   │ LibreLane Docker  │     │     │
│  │  │ Local        │   │ Adapter           │     │     │
│  │  └──────┬───────┘   └────────┬──────────┘     │     │
│  │         │                    │                 │     │
│  │         └────────┬───────────┘                 │     │
│  │                  │                             │     │
│  │      ┌───────────┴───────────┐                 │     │
│  │      │  Per-Attempt Isolated │                 │     │
│  │      │  Workspace            │                 │     │
│  │      │  (directory isolation)│                 │     │
│  │      └───────────┬───────────┘                 │     │
│  │                  │                             │     │
│  │      ┌───────────┴───────────┐                 │     │
│  │      │  LibreLane + EDA      │                 │     │
│  │      │  Tools (OpenROAD,     │                 │     │
│  │      │  Yosys, Magic, etc.)  │                 │     │
│  │      └───────────────────────┘                 │     │
│  └────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────┘
```

### Boundary Rules

1. **Cognition -> Distillation**: Agents only receive distilled outputs (MetricsPayload, EvidencePack, ConstraintDigest, lessons_learned). Never raw artifacts.
2. **Distillation -> Execution**: Extractors read raw artifacts from attempt directories. They produce small, schema-validated JSON outputs.
3. **Cognition -> Execution**: Agent patches flow through the Patch Materialization Pipeline (validation -> ConstraintGuard -> materialization -> execution).

---

## Core Loop

The orchestrator's main loop operates at stage granularity:

```
For each stage in STAGE_ORDER:
  │
  ├─ 1. Select input state baton (prior checkpoint for branch tip)
  │
  ├─ 2. COGNITIVE RETRY LOOP (free retries)
  │     │
  │     ├─ 2a. Worker agent proposes Patch
  │     ├─ 2b. Schema validation (Pydantic)
  │     ├─ 2c. Knob range validation (KnobSpec)
  │     ├─ 2d. ConstraintGuard validation (SDC + Tcl + config)
  │     │     └─ If rejected: feedback to agent, retry (free)
  │     └─ 2e. If all cognitive retries exhausted: mark as patch_rejected
  │
  ├─ 3. PHYSICAL EXECUTION (burns attempt budget)
  │     │
  │     ├─ 3a. Macro placement resolution + grid snap
  │     ├─ 3b. SDC fragment materialization
  │     ├─ 3c. Tcl hook materialization (if enabled)
  │     ├─ 3d. Config vars override
  │     ├─ 3e. Run LibreLane stage in isolated workspace
  │     └─ 3f. Persist state_out, ExecutionResult, artifacts
  │
  ├─ 4. DISTILLATION
  │     │
  │     ├─ 4a. Extract MetricsPayload
  │     ├─ 4b. Extract EvidencePack (+ spatial hotspots)
  │     ├─ 4c. Extract ConstraintDigest
  │     └─ 4d. CrashDistiller (if execution failed)
  │
  ├─ 5. JUDGING
  │     │
  │     ├─ 5a. Deterministic gates (execution_success, metrics_parse)
  │     ├─ 5b. Judge ensemble votes PASS/FAIL (majority)
  │     └─ 5c. Record votes + aggregate
  │
  ├─ 6. DECISION
  │     │
  │     ├─ If PASS: checkpoint, advance to next stage
  │     ├─ If FAIL: retry (decrement attempt budget)
  │     ├─ If budget exhausted: consult master agent
  │     │     ├─ Rollback to prior stage
  │     │     ├─ Escalate to specialist
  │     │     └─ Stop (if deadlock)
  │     └─ Plateau detection: spawn branches or consult specialist
  │
  └─ 7. GC: apply artifact garbage collection policy
```

---

## Component Architecture

### Orchestration Layer

```
orchestrator.py          -- Main async loop, stage iteration
  ├── scheduler.py       -- Branch manager, parallel job scheduling
  ├── graph.py           -- Stage graph, rollback edges, StageSpec
  ├── policies.py        -- Rollback, deadlock, plateau policies
  ├── compaction.py      -- History compaction (lessons_learned)
  ├── initialization.py  -- Zero-shot Attempt 0
  ├── gc.py              -- Artifact garbage collection
  ├── constraint_guard.py -- Patch validation (SDC/Tcl/config)
  ├── cognitive_retry.py -- Free retry loop before physical execution
  └── events.py          -- Event bus (for dashboard/logging)
```

### Execution Layer

```
adapter.py               -- ExecutionAdapter ABC
  ├── librelane_local.py -- Local LibreLane execution
  ├── librelane_docker.py-- Docker LibreLane execution
  ├── workspaces.py      -- Attempt directory management
  ├── state_handoff.py   -- State baton I/O
  ├── state_rebase.py    -- Path tokenization/rebasing
  ├── grid_snap.py       -- Macro placement grid snap
  ├── artifacts.py       -- Artifact classification (ledger/medium/heavy)
  └── patch_materialize.py -- 10-step materialization pipeline
```

### Distillation Layer

```
registry.py              -- Extractor registration and dispatch
  ├── normalize.py       -- Scoring normalization
  ├── evidence.py        -- EvidencePack assembly
  └── extractors/
      ├── timing.py      -- STA report -> setup_wns_ns per corner
      ├── area.py        -- Area metrics
      ├── route.py       -- Congestion metrics
      ├── drc.py         -- DRC violation count
      ├── lvs.py         -- LVS pass/fail
      ├── power.py       -- Power metrics
      ├── runtime.py     -- Wall-clock timing
      ├── crash.py       -- CrashDistiller (never crashes itself)
      ├── spatial.py     -- Spatial hotspot grid extraction
      └── constraints.py -- ConstraintDigest from SDC files
```

### Agents Layer

```
llm_provider.py          -- instructor + LiteLLM wrapper
  ├── logging.py         -- LLM call JSONL logging
  ├── master.py          -- Master agent (cross-stage decisions)
  ├── workers/
  │   ├── base.py        -- Worker base class
  │   ├── synth.py       -- Synthesis worker
  │   ├── floorplan.py   -- Floorplan worker
  │   ├── placement.py   -- Placement worker
  │   ├── cts.py         -- CTS worker
  │   └── routing.py     -- Routing worker
  ├── specialists/
  │   ├── timing.py      -- Timing specialist
  │   ├── routability.py -- Routability specialist
  │   └── drc.py         -- DRC specialist
  └── prompts/           -- Jinja2 templates (.j2)
```

### Judge Layer

```
ensemble.py              -- Majority voting, tie-breaking
  ├── schemas.py         -- JudgeVote, JudgeAggregate
  └── scoring.py         -- Composite scoring, normalization, anti-cheat
```

---

## Data Flow Diagram

### Patch Flow (Agent -> Execution)

```
Worker Agent
    │
    │ produces Patch (JSON)
    ▼
┌──────────────────────┐
│ Patch Materialization │
│ Pipeline              │
│                       │
│ 1. Schema validation  │ ──> PatchRejected (cognitive retry)
│ 2. Knob range check   │ ──> PatchRejected (cognitive retry)
│ 3. ConstraintGuard    │ ──> PatchRejected (cognitive retry)
│ 4. Macro resolution   │
│ 5. Grid snap          │
│ 6. SDC materialization│
│ 7. Tcl materialization│
│ 8. Config overrides   │
│ 9. Run LibreLane      │
│10. Persist results    │
└──────────┬────────────┘
           │
           ▼
    ExecutionResult
    + attempt artifacts
```

### Metrics Flow (Execution -> Agents)

```
Attempt Directory
(state_out.json, reports, logs)
    │
    ▼
┌──────────────────────┐
│ Extractor Registry    │
│                       │
│ timing ──> setup_wns  │
│ area ──> utilization  │
│ route ──> congestion  │
│ drc ──> drc_count     │
│ spatial ──> hotspots  │
│ crash ──> error_info  │
│ constraints ──> digest│
└──────────┬────────────┘
           │
           ├──> MetricsPayload (JSON)
           ├──> EvidencePack (JSON)
           └──> ConstraintDigest (JSON)
                   │
                   ▼
            ┌──────────────┐
            │ Judge Ensemble│ ──> PASS/FAIL
            └──────┬───────┘
                   │
                   ▼
            ┌──────────────┐
            │ Worker Agent  │ (next iteration context)
            │ + Compaction  │ ──> lessons_learned
            └──────────────┘
```

---

## Directory Structure at Runtime

```
runs/<run_id>/
├── manifest.json              # Provenance + tool versions
├── agentic_config.yaml        # Frozen config for this run
├── baseline/                  # LibreLane run without patches
│   ├── metrics.json
│   └── state_out.json
├── branches/
│   ├── B0/                    # Main branch
│   │   ├── tip.json           # Current branch tip reference
│   │   └── stages/
│   │       ├── SYNTH/
│   │       │   ├── attempt_001/
│   │       │   │   ├── proposals/
│   │       │   │   │   ├── try_001/
│   │       │   │   │   │   ├── patch_proposed.json
│   │       │   │   │   │   ├── patch_rejected.json  # if rejected
│   │       │   │   │   │   └── llm_calls.jsonl
│   │       │   │   │   └── try_002/
│   │       │   │   ├── patch.json               # accepted patch
│   │       │   │   ├── metrics.json             # MetricsPayload
│   │       │   │   ├── evidence.json            # EvidencePack
│   │       │   │   ├── constraints/
│   │       │   │   │   ├── constraints_digest.json
│   │       │   │   │   └── agenticlane_synth_001.sdc
│   │       │   │   ├── judge_votes.json
│   │       │   │   ├── judge_aggregate.json
│   │       │   │   ├── lessons_learned.md
│   │       │   │   ├── lessons_learned.json
│   │       │   │   ├── agent_messages.jsonl
│   │       │   │   ├── llm_calls.jsonl
│   │       │   │   ├── state_in.json
│   │       │   │   ├── state_out.json
│   │       │   │   ├── state_rebase_map.json
│   │       │   │   ├── workspace/               # LibreLane working dir
│   │       │   │   ├── artifacts/               # Key reports
│   │       │   │   └── artifacts_heavy.tar.zst  # Compressed heavy artifacts
│   │       │   └── attempt_002/
│   │       ├── FLOORPLAN/
│   │       │   └── ...
│   │       └── ... (all 10 stages)
│   ├── B1/                    # Parallel branch (if enabled)
│   │   └── ...
│   └── B2/
│       └── ...
```

---

## Concurrency Model

### Async Architecture (asyncio)

```python
# Orchestrator runs as async main loop
async def run_flow(config):
    if config.parallel.enabled:
        # Parallel branch execution with semaphore
        sem = asyncio.Semaphore(config.parallel.max_parallel_jobs)
        tasks = [
            run_branch(branch_id, sem)
            for branch_id in range(config.parallel.max_parallel_branches)
        ]
        results = await asyncio.gather(*tasks)
        best = select_best(results)
    else:
        # Sequential single-branch execution
        result = await run_branch("B0", sem=None)
```

### Directory Isolation

- Each attempt gets its own directory (R9)
- No two running attempts share a writable workspace
- State files are treated as immutable once written
- GC acquires a file lock before modifying attempt directories

---

## Security Boundaries

```
┌─────────────────────────────────────────┐
│            User Machine                 │
│                                         │
│  ┌───────────────────────────────────┐  │
│  │        AgenticLane Process        │  │
│  │                                   │  │
│  │  Secrets: env vars only           │  │
│  │  Never written to run dirs        │  │
│  │                                   │  │
│  │  ┌─────────────────────────────┐  │  │
│  │  │  LLM Provider               │  │  │
│  │  │  (LM Studio / Ollama local) │  │  │
│  │  │  or API (keys in env)       │  │  │
│  │  └─────────────────────────────┘  │  │
│  │                                   │  │
│  │  ┌─────────────────────────────┐  │  │
│  │  │  Execution (Local or Docker)│  │  │
│  │  │                             │  │  │
│  │  │  Docker: run_root is        │  │  │
│  │  │  read-only mount            │  │  │
│  │  │                             │  │  │
│  │  │  Tcl: disabled by default   │  │  │
│  │  │  SDC: templated by default  │  │  │
│  │  └─────────────────────────────┘  │  │
│  └───────────────────────────────────┘  │
│                                         │
│  No telemetry. No network calls         │
│  unless LLM API mode is enabled.        │
└─────────────────────────────────────────┘
```

---

## Configuration Hierarchy

```
safe.yaml (defaults)
    │
    ▼
user agentic_config.yaml (project overrides)
    │
    ▼
CLI flags (--profile, --parallel, --sdc-mode, etc.)
    │
    ▼
Environment variables (secrets only: API keys)
    │
    ▼
AgenticLaneConfig (final merged Pydantic model)
```

Each layer overrides the previous. The merged config is frozen and saved to `runs/<run_id>/agentic_config.yaml` for reproducibility.
