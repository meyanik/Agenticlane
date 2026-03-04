# AgenticLane Build Specification (v0.6 FINAL)
**A local‑first, reproducible, multi‑agent orchestration layer for LibreLane RTL→GDS flows with judge‑driven iteration, backtracking, strict distillation boundaries, safe concurrency, bounded disk usage, optional parallel branch exploration, and hardened constraint/SDC/Tcl safety nets.**

> **Audience:** A coding agent / engineering team implementing the system.
>
> **Status:** FINAL implementation spec (prescriptive). Implement exactly as written. If something is ambiguous, implement the safest deterministic option and open a tracked issue.
>
> **Design philosophy:** “Deterministic where possible, probabilistic only where useful, and audited everywhere.”

---

## Executive Summary
AgenticLane wraps **LibreLane** as the deterministic execution engine and adds an agentic control plane that:
- iterates and backtracks like a real physical-design team,
- uses deterministic distillation to prevent LLM hallucinations,
- supports safe local-first operation,
- supports optional parallel exploration,
- enforces reproducibility and provenance,
- and prevents “constraint cheating” through config, SDC, and Tcl backdoors.

This v0.6 final spec incorporates all prior hardening:
- Artifact GC to prevent disk explosions
- Per-attempt directory isolation for concurrency
- Crash/timeout/OOM distillation
- Spatial hotspot evidence + safe macro placement actuator
- Zero-shot “Attempt 0” initialization patch
- Explicit state baton handoff with path rebasing
- MCMM scoring normalization and anti-cheat
- ConstraintGuard across all channels
- SDC/Tcl loophole defenses (`read_sdc`, line continuations, hook structuring)
- Cognitive retry loop (prevents budget burn on rejected patches)

---

## Table of Contents
1. [Project Charter](#project-charter)  
2. [Glossary](#glossary)  
3. [Hard Requirements](#hard-requirements)  
4. [Non‑Goals](#non-goals)  
5. [System Architecture](#system-architecture)  
6. [Repository Layout](#repository-layout)  
7. [Configuration System](#configuration-system)  
8. [Orchestration Model](#orchestration-model)  
9. [Parallel Branch Exploration](#parallel-branch-exploration)  
10. [Execution Layer](#execution-layer)  
11. [State Baton Handoff + Path Rebasing](#state-baton-handoff--path-rebasing)  
12. [Distillation Layer](#distillation-layer)  
13. [Spatial Evidence + Actuators](#spatial-evidence--actuators)  
14. [Artifact Retention + Garbage Collection](#artifact-retention--garbage-collection)  
15. [Agents Layer](#agents-layer)  
16. [Judging Layer](#judging-layer)  
17. [Scoring + MCMM Normalization + Anti‑Cheat](#scoring--mcmm-normalization--anti-cheat)  
18. [ConstraintGuard FINAL](#constraintguard-final)  
19. [Cognitive Retry Loop](#cognitive-retry-loop)  
20. [KnobSpec + StageSpec Registries](#knobspec--stagespec-registries)  
21. [Reproducibility + Provenance](#reproducibility--provenance)  
22. [CLI Specification](#cli-specification)  
23. [Local Dashboard](#local-dashboard)  
24. [Benchmarking + Baselines](#benchmarking--baselines)  
25. [CI Strategy](#ci-strategy)  
26. [Security Model](#security-model)  
27. [Implementation Phases + Acceptance Tests](#implementation-phases--acceptance-tests)  
28. [Appendix A: Canonical Schemas](#appendix-a-canonical-schemas)  
29. [Appendix B: Constraint Command Maps](#appendix-b-constraint-command-maps)  
30. [Appendix C: SDC/Tcl Restricted Dialect](#appendix-c-sdctcl-restricted-dialect)  
31. [Appendix D: Macro Placement Mapping + Grid Snap](#appendix-d-macro-placement-mapping--grid-snap)  
32. [Appendix E: State Path Rebasing](#appendix-e-state-path-rebasing)  
33. [Appendix F: Directory Layout](#appendix-f-directory-layout)  

---

# Project Charter

## Vision
An open-source “virtual ASIC design team” for RTL→GDS that:
- improves quality via multi-agent iteration/backtracking,
- remains reproducible and auditable,
- stays offline-capable and local-first,
- is safe by default (no silent constraint cheating).

## Intended Users
- hobbyists
- researchers
- EDA tool developers

## Disclaimer (must be in README)
Research/open-source only; no tapeout guarantees; users own responsibility.

---

# Glossary
- **LibreLane:** deterministic flow runner. AgenticLane does not replace tools; it orchestrates LibreLane execution.
- **Stage:** a coarse unit of work (set of LibreLane steps) governed by one worker agent.
- **Step:** a single LibreLane step (fine-grained).
- **Attempt:** one physical run attempt of a stage (EDA tools executed).
- **Cognitive try:** an LLM patch proposal that is rejected before running tools (free retry loop).
- **Branch:** one candidate timeline (for parallel exploration).
- **Patch:** structured proposal that modifies allowed inputs (config vars, macro placements, SDC fragments, Tcl hooks, RTL ECO).
- **ConstraintGuard:** deterministic validator that prevents forbidden constraint modifications across all channels.
- **ConstraintDigest:** distilled “constraints fingerprint” describing applied constraints (clocks/periods/exceptions counts).
- **MetricsPayload:** canonical JSON metrics (small, reliable).
- **EvidencePack:** canonical evidence bundle (errors/warnings + spatial hotspots + crash info).
- **State baton:** serialized LibreLane state passed between attempts/stages.
- **GC:** artifact garbage collection policy (prunes heavy artifacts while keeping ledgers).

---

# Hard Requirements

## R1 — Build on LibreLane
Do not rewrite EDA tools. AgenticLane orchestrates LibreLane.

## R2 — Local-first
Must run fully offline (local LLM + local LibreLane). API models optional.

## R3 — Docker supported
Must support docker execution mode for users.

## R4 — Deterministic distillation boundary
LLMs never read large raw artifacts (DEF/ODB/SPEF/GDS/full logs). LLMs only see:
- MetricsPayload
- EvidencePack
- bounded snippets

## R5 — LLM-as-judge authority with redundancy
Judge ensemble (default 3) decides PASS/FAIL by majority vote. Deterministic sanity gates always apply.

## R6 — Policy-configurable everything
Permissions, gates, rollbacks, budgets, parallel mode, GC, constraint locks, etc.

## R7 — Reproducibility and provenance
Every run emits a manifest with enough information to replay:
- patches
- tool versions (best effort)
- run directory structure
- LLM parameters and hashes

## R8 — Full RTL→GDS and partial stage/step execution
CLI must support: full flow, stage-only, step-only.

## R9 — Concurrency safety (directory isolation)
Each attempt must have its own working directory. No two running attempts share a writable workspace.

## R10 — Robust failure distillation
Tool crash/timeout/OOM must still yield MetricsPayload + EvidencePack (with null metrics) without crashing orchestrator.

## R11 — Structured LLM output enforcement
All LLM outputs must be schema-valid JSON:
- structured generation where possible
- schema validation
- deterministic JSON extraction fallback (if enabled)

## R12 — Spatial hotspot actuator exists without Tcl
If spatial hotspots are enabled, the system must have at least one safe actuator in safe mode. This is:
- `macro_placements` mapping to config macro instance locations/orientation

## R13 — State baton must be explicit
Never rely on “latest run directory” heuristics. Always pass state explicitly from a chosen prior checkpoint.

## R14 — Macro placements must be snapped to legal grid
Coordinates must be snapped to:
- placement site grid (from tech LEF SITE) when available
- plus integer DBU (um→dbu→um roundtrip)

## R15 — Constraint anti-cheat must exist
Default locked constraints include the user clock period (and other user constraints as configured). Patches must not silently relax constraints.

## R16 — Constraint locks apply across all channels
If an aspect is locked, it must not be modifiable through:
- config vars
- SDC fragments
- Tcl hooks
including “loader” commands like `read_sdc` that can bring in more constraints.

## R17 — PatchRejected must not burn physical budget instantly
Invalid/forbidden patches must trigger cognitive retries (bounded) before consuming physical attempt budgets.

---

# Non-Goals
- guaranteed signoff correctness for tapeout
- proprietary PDK integration without user providing it
- hosted SaaS

---

# System Architecture

## Three-plane separation
```
Cognition Plane (LLMs)
  - Master Agent
  - Worker Agents
  - Specialist Agents
  - Judge Ensemble
        |
        |  bounded JSON + snippets
        v
Distillation Plane (deterministic)
  - Extractors (timing/area/route/drc/lvs/power/runtime)
  - Spatial hotspot extraction
  - CrashDistiller
  - ConstraintDigest extractor
        |
        |  attempt artifacts + state baton
        v
Execution Plane (deterministic)
  - Per-attempt isolated workspace runner (local or docker)
  - LibreLane flow/step runner
  - Open-source EDA tools
```

## Core loop at stage granularity
For each stage in stage graph:
1) choose input state baton (prior checkpoint) for branch tip
2) run cognitive retry loop to get an accepted patch
3) execute stage attempt in isolated workspace
4) distill MetricsPayload + EvidencePack + ConstraintDigest
5) judge ensemble votes PASS/FAIL
6) if PASS: checkpoint and advance
7) if FAIL: retry, rollback, or escalate per policy
8) apply GC policy

---

# Repository Layout
Recommended monorepo:

```
agenticlane/
  pyproject.toml
  README.md
  LICENSE
  docs/
    build_spec_v0.6_final.md
    user_guide.md
    security.md
    contributing.md
  agenticlane/
    cli/
      main.py
      commands/...
    config/
      models.py
      loader.py
      defaults/
        safe.yaml
        balanced.yaml
        aggressive.yaml
    orchestration/
      orchestrator.py
      scheduler.py
      graph.py
      policies.py
      compaction.py
      initialization.py
      events.py
      gc.py
      constraint_guard.py
      cognitive_retry.py
    execution/
      adapter.py
      workspaces.py
      librelane_local.py
      librelane_docker.py
      state_handoff.py
      state_rebase.py
      grid_snap.py
      artifacts.py
      patch_materialize.py
    distill/
      registry.py
      normalize.py
      evidence.py
      extractors/
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
      llm_provider.py
      master.py
      workers/...
      specialists/...
      prompts/...
    judge/
      schemas.py
      ensemble.py
      scoring.py
    knowledge/
      rag_interface.py
      chroma_adapter.py
    ui/
      dashboard/
        app.py
        static/
        templates/
  tests/
    unit/...
    golden/...
    integration/...
```

---

# Configuration System

## Config merge order
1) default profile (safe/balanced/aggressive)
2) user project `agentic_config.yaml`
3) CLI overrides
4) env vars (secrets only)

## Guiding rule
Defaults must be safe and non-cheating:
- safe/balanced: restricted SDC, Tcl disabled, constraints locked
- aggressive: can unlock, but only with explicit user config

## Full config skeleton (v0.6)
This is the canonical shape (Pydantic). Real configs may omit optional keys; loader fills defaults.

```yaml
project:
  name: "my_block"
  run_id: "auto"
  output_dir: "./runs"

design:
  librelane_config_path: "./design.json"
  pdk: "sky130A"

execution:
  mode: "local"                # local | docker
  tool_timeout_seconds: 21600
  env: {}                      # optional deterministic env vars
  workspace:
    isolation: "per_attempt"   # REQUIRED
    base_clone_strategy: "reflink_or_hardlink"
  docker:                       # only if mode=docker
    image: "agenticlane:latest"
    mount_root: "/run_root"     # run root (read-only)
    attempt_root: "/attempt"    # attempt dir (rw)

intent:
  prompt: "70% timing, 30% area. power not important. fully autonomous."
  weights_hint: {timing: 0.7, area: 0.3}

initialization:
  zero_shot:
    enabled: true
    apply_to_branches: "all"    # all | master_only | none

flow_control:
  stage_granularity: "major"    # major | step
  budgets:
    physical_attempts_per_stage: 12
    cognitive_retries_per_attempt: 3
    cognitive_fail_counts_as_physical_attempt: true
    max_total_cognitive_retries_per_stage: 30
  plateau_detection:
    enabled: true
    window: 3
    min_delta_score: 0.01
  deadlock_policy: "auto_relax" # ask_human | auto_relax | stop
  ask_human:
    enabled: false

parallel:
  enabled: true
  max_parallel_branches: 3
  max_parallel_jobs: 2
  branch_policy: "best_of_n"    # best_of_n | pareto
  branch_budget_per_stage: 4
  prune:
    enabled: true
    prune_delta_score: 0.05
    prune_patience_attempts: 2

action_space:
  permissions:
    config_vars: true
    macro_placements: true
    sdc: true
    tcl: false
    rtl_eco: false
  sdc:
    mode: "templated"           # templated | restricted_freeform | expert_freeform
  tcl:
    enabled: false
    mode: "restricted_freeform" # restricted_freeform | expert_freeform
    hooks_allowed:
      - "pre_step"
      - "post_step"
    tools_allowed:
      - "openroad"
  macro_placements:
    snap:
      enabled: true
      rounding: "nearest"        # nearest | floor | ceil
      max_iterations: 5          # offset search attempts to avoid overlap (best effort)

constraints:
  locked_vars:
    - "CLOCK_PERIOD"
  allow_relaxation: false
  max_relaxation_pct: 0.0
  locked_aspects:
    - "clock_period"
    - "timing_exceptions"
    - "max_min_delay"
    - "clock_uncertainty"
  guard:
    enabled: true
    preprocess:
      join_line_continuations: true
      max_joined_lines: 32
      reject_unterminated_continuation: true
    sdc:
      mode: "templated"          # templated | restricted_freeform | expert_freeform
      deny_commands: []          # derived from locked_aspects if empty
      allow_commands: []         # optional allowlist in restricted mode
      allow_bracket_cmds:
        - "get_ports"
        - "get_pins"
        - "get_nets"
        - "get_cells"
        - "get_clocks"
        - "all_inputs"
        - "all_outputs"
        - "all_clocks"
      forbid_tokens:
        - "eval"
        - "source"
        - "exec"
        - "open"
        - "puts"
        - "file"
        - "glob"
      reject_semicolons: true
      ignore_comment_lines: true
      reject_inline_comments: true
    tcl:
      mode: "restricted_freeform"
      deny_commands: []          # derived from locked_aspects if empty
      forbid_tokens:
        - "eval"
        - "source"
        - "exec"
        - "open"
        - "puts"
        - "file"
        - "glob"
      reject_semicolons: true
      ignore_comment_lines: true

distill:
  crash_handling:
    stderr_tail_lines: 200
    missing_report_policy: "record_and_continue"
  spatial:
    enabled: true
    grid_bins_x: 2
    grid_bins_y: 2
    max_hotspots: 12
    macro_nearby_radius_um: 50
  constraints_digest:
    enabled: true
    sources:
      - "baseline"
      - "user"
      - "agent_fragments"

judging:
  ensemble:
    models: ["judge_model_a","judge_model_b","judge_model_c"]
    vote: "majority"
    tie_breaker: "fail"
  strictness:
    hard_gates:
      - "execution_success"
      - "metrics_parse_valid"
    signoff_hard_gates:
      - "drc_clean"
      - "lvs_pass"

scoring:
  normalization:
    method: "percent_over_baseline"  # percent_over_baseline | absolute_scaled
    epsilon: 1e-6
    clamp: 1.0
  timing:
    effective_clock:
      enabled: true
      reducer: "worst_corner"

artifact_gc:
  enabled: true
  policy: "keep_pass_and_tips"
  max_run_disk_gb: 40
  keep_failed_attempt_artifacts: 1
  keep_branch_tips: true
  compress_pass_artifacts: true
  compression: "zstd"
  on_exceed: "prune_then_warn"

llm:
  mode: "local"                    # local | api
  provider: "litellm"
  models:
    master: "model_master"
    worker: "model_worker"
    judge:  ["model_j1","model_j2","model_j3"]
  structured_output:
    enabled: true
    strategy: "json_schema"        # json_schema | function_call | constrained_decoding
    strict: true
    max_retries: 2                 # internal provider retries to satisfy schema
    json_extraction_fallback: true
  temperature: 0.0
  seed: 42
  reproducibility_mode: "deterministic" # replay | deterministic | stochastic
```

---

# Orchestration Model

## Canonical stages (major granularity)
- SYNTH
- FLOORPLAN
- PDN
- PLACE_GLOBAL
- PLACE_DETAILED
- CTS
- ROUTE_GLOBAL
- ROUTE_DETAILED
- FINISH
- SIGNOFF

## Rollback edges (default)
- ROUTE_DETAILED → ROUTE_GLOBAL
- ROUTE_DETAILED → PLACE_DETAILED
- ROUTE_DETAILED → FLOORPLAN
- CTS → PLACE_DETAILED
- SIGNOFF → ROUTE_DETAILED
- SIGNOFF → FLOORPLAN

Rollback edges are configurable. Implementation must use a deterministic shortest-cost policy unless user overrides.

## Attempt 0: Zero-shot initialization
If enabled:
1) Master compiles `IntentProfile`.
2) Master emits a `global_init_patch.json` constrained to “global” safe knobs.
3) Orchestrator applies it before Stage 1 Attempt 1 (per policy).

Important:
- Baseline run must remain unmodified unless baseline comparisons are disabled.

## Plateau detection
Per stage per branch:
- keep last `window` scores
- plateau if `max - min < min_delta_score`
- on plateau:
  - call specialist agents
  - optionally spawn parallel branches (if enabled)
  - optionally rollback (if suggested)

## Cycle detection
Compute stable patch hash + key overrides hash. If repeating:
- treat as deadlock
- apply deadlock policy

---

# Parallel Branch Exploration

## Branch model
A branch is a timeline of stages and attempts. Branches diverge by patch stacks.

## Scheduling
- at most `max_parallel_jobs` concurrent EDA executions
- branch attempts must run in isolated directories
- branch pruning must trigger GC

## Branch generation strategies
At minimum:
1) Diverse sampling of knob sets (within KnobSpec)
2) Mutational hill climb from best patch

---

# Execution Layer

## Key invariants
- Every physical attempt runs in its own directory.
- Every attempt has explicit inputs and outputs.
- Previous checkpoints are treated as read-only inputs whenever possible.

## ExecutionAdapter interface (canonical)
```python
from dataclasses import dataclass
from typing import Optional, Dict, Any, Literal

ExecutionStatus = Literal[
    "success",
    "tool_crash",
    "timeout",
    "oom_killed",
    "config_error",
    "patch_rejected",
    "unknown_fail"
]

@dataclass
class ExecutionResult:
    execution_status: ExecutionStatus
    exit_code: int
    runtime_seconds: float
    attempt_dir: str                 # run-relative
    workspace_dir: str               # run-relative
    artifacts_dir: str               # run-relative
    state_out_path: Optional[str]    # run-relative; may be None on crash
    stderr_tail: Optional[str]
    error_summary: Optional[str]

class ExecutionAdapter:
    def run_stage(self, *, run_root: str, stage_name: str,
                  librelane_config_path: str,
                  resolved_design_config_path: str,
                  patch: Dict[str, Any],
                  state_in_path: Optional[str],
                  attempt_dir: str,
                  timeout_seconds: int) -> ExecutionResult:
        raise NotImplementedError
```

## Patch materialization order (MANDATORY)
For a physical attempt, the adapter must apply patch actions in this order:

1) **Patch schema validation** (Pydantic)
2) **Knob range validation** (KnobSpec with PDK overrides)
3) **ConstraintGuard validation** (SDC + Tcl + config)
4) **Macro placement resolution** (hint→coords)
5) **Macro grid snapping** (site + DBU)
6) **Materialize SDC fragments** (append-only unless override allowed)
7) **Materialize Tcl hook scripts** (structured hooks, only if enabled)
8) **Apply config_vars overrides**
9) **Run LibreLane stage** with explicit `state_in` baton
10) Persist `state_out.json`, ExecutionResult, artifacts index

If any of steps 1–3 fails, do not start EDA tools; return ExecutionResult with `execution_status="patch_rejected"` and a structured PatchRejected record written to attempt dir.

## SDC injection pattern (MANDATORY)
AgenticLane must never overwrite baseline/user SDC in place.
Instead:
- write agent fragment(s) to:
  - `attempt_dir/constraints/agenticlane_<stage>_<attempt>_<k>.sdc`
- configure LibreLane/run wrapper to include these fragments in a deterministic order:
  1) baseline constraints (from project)
  2) user constraints (from design config)
  3) agent fragments (append-only by default)

If user explicitly allows “override mode” (not recommended):
- agent fragments may be inserted earlier in order.
- ConstraintGuard must still enforce locked aspects.

## Tcl injection pattern (STRUCTURED; only if enabled)
If enabled, tcl is injected only via structured hooks:
- pre_step/post_step at specific step boundaries
- tool-specific (default openroad only)

AgenticLane writes scripts to:
- `attempt_dir/scripts/agenticlane_<tool>_<hook>_<id>.tcl`

How the hook is executed depends on runner mode:
- Preferred: custom step runner that calls the tool with scripts sourced at hook points.
- Acceptable: LibreLane-supported hook variables if available.
- Must be deterministic and logged.

---

# State Baton Handoff + Path Rebasing

## State baton rules
- Each attempt stores:
  - `state_in.json` (copy of what was used; optional for first stage)
  - `state_out.json` (immutable output snapshot if produced)
- Never mutate old `state_out.json`.
- Always generate new `state_in.json` for next attempt.

## Path rebasing problem
State files may contain absolute paths. With isolated workspaces and Docker mount roots, these paths may break.

## Path rebasing solution (FINAL)
AgenticLane must support `state_handoff.path_rebasing.mode`:
- `tokenized` (recommended): store `{{RUN_ROOT}}/<relpath>`
- `make_relative`: store only `<relpath>` (less portable)
- `rebase_to_mount_root`: store `/run_root/<relpath>` (docker-only simplicity)

See Appendix E for the deterministic algorithm.

---

# Distillation Layer

## Distillation outputs per physical attempt
Write these deterministically into attempt dir:
- `metrics.json` (MetricsPayload)
- `evidence.json` (EvidencePack)
- `constraints/constraints_digest.json` (ConstraintDigest) if enabled
- `distill_log.jsonl` (diagnostics)

## CrashDistiller (MANDATORY)
On non-success execution:
- set PPA metrics to null
- populate evidence with:
  - stderr tail
  - missing reports list
  - crash signature tags
- never crash orchestrator due to missing files

## ConstraintDigest extractor (MANDATORY if constraints_digest.enabled)
Inputs (best effort):
- baseline constraint sources used by flow
- user constraint sources
- agent fragments produced by patch
Output:
- applied clocks with periods (if parseable)
- counts of exception commands (false_path/multicycle/disable_timing)
- counts of max/min delay constraints
- uncertainty commands count
- `opaque=true` if parsing is unreliable (expert mode)

ConstraintDigest is used for:
- judge context (did constraints change?)
- scoring (effective clock period)

---

# Spatial Evidence + Actuators

## Spatial hotspots (EvidencePack)
EvidencePack includes `spatial_hotspots[]` describing:
- type: congestion / drc
- grid bin + region label
- severity
- nearby_macros[]

## Safe actuator: macro_placements
Worker may propose `macro_placements[]` to move macros away from localized hotspots.
Macro placement mapping is deterministic and validated, and does not require Tcl.

Appendix D defines:
- mapping to design config MACROS
- hint→coords deterministic resolver
- grid snap procedure

---

# Artifact Retention + Garbage Collection

## Artifact taxonomy
1) Ledger artifacts (always keep):
   - patch proposals + accepted patch
   - metrics.json, evidence.json, constraints_digest.json
   - judge votes + aggregate
   - complaints
   - LLM call logs (hashes)
2) Medium artifacts (policy-based):
   - key reports
   - errors-only logs
3) Heavy artifacts (GC candidates):
   - odb/def/spef/full logs/intermediate gds

## GC policy (MANDATORY)
Must keep cognitive history even when pruning heavy artifacts.
Must never delete artifacts referenced by:
- current branch tips
- rollback horizon checkpoints

GC runs after each attempt and after branch prune.

---

# Agents Layer

## Roles
- Master agent: lead architect, policies, rollbacks, branching.
- Worker agents: per-stage patch proposal.
- Specialist agents: timing/routability/drc advice.

## Input boundary (MANDATORY)
Agents only receive:
- compacted history (“Lessons Learned”)
- MetricsPayload
- EvidencePack
- ConstraintDigest summary (if enabled)
- allowed knobs subset

Never raw DEF/ODB logs.

## History compaction (MANDATORY)
For each stage/branch produce:
- `lessons_learned.md` (table)
- `lessons_learned.json`

Only last few full attempts go into prompt; older attempts summarized.

---

# Judging Layer

## Two-level judgment
1) deterministic gates:
   - execution_status success (or allowed failure class) as configured
   - metrics parse valid
   - required outputs exist
2) judge ensemble votes PASS/FAIL

Judges must cite metric keys in blocking issues.

---

# Scoring + MCMM Normalization + Anti‑Cheat

## MCMM reduction
Default worst-corner policy:
- for slack-like metrics: use min across corners
- for delay-like metrics: use max across corners

## Normalization
Default: percent improvement over baseline with clamp and epsilon.

## Anti-cheat mechanisms (FINAL)
### Layer 1: Constraint locks
Locked constraints cannot be modified unless explicitly enabled.

### Layer 2: ConstraintGuard across all channels
Reject forbidden constraint modifications in:
- config_vars
- sdc_edits
- tcl_edits

### Layer 3: Scoring uses applied constraint digest
Compute effective timing using ConstraintDigest periods (not config var).
This defeats backdoor changes if they somehow slipped through.

### Effective setup period
Per corner:
- `effective_setup_period_ns = applied_clock_period_ns - setup_wns_ns`
Worst corner = max effective setup period.
Lower is better.

---

# ConstraintGuard FINAL

## Why this exists
Agents may try to “improve timing” by relaxing constraints. ConstraintGuard prevents:
- clock period changes
- false path / multicycle / disable_timing exceptions
- max/min delay overrides
- uncertainty manipulation
- constraint file loading (`read_sdc`) via Tcl

## Inputs
- Patch (proposed)
- constraints.locked_vars and constraints.locked_aspects
- constraints.guard settings
- action_space permissions

## Outputs
- PASS, or
- FAIL with `PatchRejected.json` written to attempt dir and returned to orchestrator

## Command set derivation
If config `deny_commands` lists are empty, derive them from locked_aspects using Appendix B.

## Preprocessing step (MANDATORY)
To prevent bypass by line continuations (`\`):
- Join lines ending with a backslash-newline into one logical line.
- Enforce:
  - maximum joined lines per logical line (`max_joined_lines`)
  - if file ends with unterminated continuation, reject (if configured)

### Deterministic join algorithm
Given raw text:
1) Normalize newlines to `\n`.
2) Split into lines.
3) Iterate, building `logical_lines`:
   - take current line `L` (without trailing newline)
   - while `L.rstrip().endswith("\\")`:
     - remove the trailing backslash
     - append a single space
     - concatenate next physical line (after lstrip)
     - increment join counter; if exceeds max, reject
   - push final `L` to `logical_lines`

## Restricted dialect scanning (MANDATORY in restricted_freeform)
For each logical line:
- ignore empty lines
- if ignore_comment_lines: ignore lines whose first non-space char is `#`
- if reject_inline_comments: reject any line containing `#` not at start (simple deterministic rule)
- if reject_semicolons: reject any line containing `;`

Extract command token:
- first whitespace-delimited token

Reject if:
- command token in deny_commands
- any forbid_tokens appear as standalone tokens or substrings (configurable; default substring match)

Bracket expression rules (SDC restricted mode)
Because SDC commonly uses `[get_ports ...]`, **we do NOT ban brackets**.
Instead, we enforce safe bracket expressions:

- Find all occurrences of `[...]` with no nesting.
- For each bracket content:
  - extract its first token (e.g., get_ports)
  - allow only tokens in `allow_bracket_cmds`
  - reject if bracket content contains any deny command tokens
  - reject if bracket content contains `;`, `eval`, `source`, `exec`, `$`

If nested brackets are detected (a `[` inside bracket content), reject in restricted mode.

## `read_sdc` loophole closure
Even if create_clock is blocked, a Tcl hook could load a separate constraints file:
- `read_sdc malicious.sdc`
Therefore:
- `read_sdc` must be denylisted in Tcl when any constraints are locked (default).
- Also deny `source` and file IO commands in restricted mode (already in forbid_tokens).

## Channels covered
ConstraintGuard must scan:
- Patch.sdc_edits lines (each fragment)
- Patch.tcl_edits lines (each hook script)
- Patch.config_vars changes for locked_vars

---

# Cognitive Retry Loop

## Problem
If PatchRejected consumes physical attempt budget, a model can burn the entire stage budget instantly (without running tools).

## Solution (FINAL)
Introduce **cognitive retries** that are free up to a bound.

### Budget rules
- `cognitive_retries_per_attempt`: free retries per physical attempt
- If exhausted:
  - either count as one physical attempt failure (default), or
  - stop immediately (configurable)
- `max_total_cognitive_retries_per_stage`: global stage cap to prevent infinite loops

### Implementation
For each physical attempt directory:
- store proposals under:
  - `attempt_dir/proposals/try_001/patch_proposed.json`
  - `attempt_dir/proposals/try_001/patch_rejected.json`
  - `attempt_dir/proposals/try_001/llm_calls.jsonl`

Accepted patch saved as:
- `attempt_dir/patch.json`

If cognitive retries exhausted:
- create `attempt_dir/patch_rejected_final.json`
- mark attempt execution_status = patch_rejected
- proceed per deadlock policy

---

# KnobSpec + StageSpec Registries

## StageSpec
Defines:
- stage name
- ordered LibreLane steps in stage
- required outputs/views
- rollback targets
- relevant metrics
- typical failure signatures

## KnobSpec
Defines:
- knob name
- dtype and range
- PDK overrides for ranges
- safety tier
- whether it is a constraint knob (cheat risk)
- stage applicability

Constraint knobs (like CLOCK_PERIOD) must be marked:
- is_constraint=true
- locked_by_default=true
- cheat_risk=true

---

# Reproducibility + Provenance

## Reproducibility modes
- replay: do not call LLMs; replay stored outputs
- deterministic: temp=0, seed if supported, record everything
- stochastic: normal exploration

## Required logging
Every LLM call must be recorded (jsonl):
- model, provider, parameters (temp/seed), prompt hash, response hash
Optionally store full prompt/response if user enabled debug mode.

---

# CLI Specification
Commands:
- `agenticlane init`
- `agenticlane run`
- `agenticlane run --stage <STAGE>`
- `agenticlane run --step <STEP>`
- `agenticlane report <run_id>`
- `agenticlane dashboard <run_id>`
- `agenticlane replay <run_id>`

Useful flags:
- `--profile safe|balanced|aggressive`
- `--parallel on|off`
- `--zero-shot on|off`
- `--repro-mode replay|deterministic|stochastic`
- `--unlock-constraint CLOCK_PERIOD` (dangerous; explicit)
- `--sdc-mode templated|restricted|expert`
- `--tcl-mode restricted|expert`
- `--max-disk-gb N`
- `--keep-all-artifacts` (debug)

---

# Local Dashboard
Must work offline, reading run folder JSON files.
Must display:
- branches and attempt timelines
- metrics plots
- judge votes
- constraint digest summaries
- PatchRejected events
- spatial hotspots grid

---

# Benchmarking + Baselines

## Certified CI set
- sky130
- gf180

## Baseline definition
Baseline = LibreLane run without agent patches (unless user disables baseline).
Store baseline metrics/digest for scoring normalization.

---

# CI Strategy

## Fast CI
- schema validation
- constraint guard unit tests (including read_sdc, line continuation)
- compaction tests
- scoring anti-cheat tests

## Nightly CI
- run small benchmarks on sky130 and gf180
- run baseline + agentic
- detect regressions

---

# Security Model
- local-first; no telemetry
- secrets never written into run dirs
- Tcl disabled by default; when enabled, restricted mode + sandbox recommended
- SDC in templated mode by default
- Docker mode should mount run_root read-only

---

# Implementation Phases + Acceptance Tests (FINAL)

## Phase 1: Deterministic backbone (no LLM)
Acceptance:
- execute a stage in isolated attempt dir
- crash distiller outputs metrics/evidence on failure
- state baton handoff works
- GC prunes failed heavy artifacts safely

## Phase 2: ConstraintGuard + cognitive retry
Acceptance:
- patch with forbidden SDC command rejected without burning physical budget immediately
- line continuation join prevents bypass
- read_sdc in Tcl rejected when constraints locked
- proposals recorded deterministically

## Phase 3: Single-stage agent loop
Acceptance:
- placement stage improves metrics across retries
- lessons learned table generated

## Phase 4: Rollback + spatial actuator
Acceptance:
- routing complaint triggers macro move and/or floorplan rollback

## Phase 5: Full flow + parallel branches
Acceptance:
- parallel run executes in isolated dirs, prunes, selects best

---

# Appendix A: Canonical Schemas

## A1) Patch (schema_version=5)
```json
{
  "schema_version": 5,
  "patch_id": "uuid-or-hash",
  "stage": "FLOORPLAN",
  "types": ["config_vars", "macro_placements", "sdc_edits", "tcl_edits"],
  "config_vars": {"FP_CORE_UTIL": 55},
  "macro_placements": [
    {"instance": "U_SRAM_0", "location_hint": "SW", "x_um": null, "y_um": null, "orientation": "N"}
  ],
  "sdc_edits": [
    {"name": "agent_floorplan.sdc", "mode": "append_lines", "lines": ["set_input_delay 1.0 -clock core_clk [get_clocks core_clk] [get_ports in0]"]}
  ],
  "tcl_edits": [
    {"name": "post_gp_fix.tcl", "tool": "openroad", "hook": {"type": "post_step", "step_id": "OpenROAD.GlobalPlacement"}, "mode": "append_lines", "lines": ["# example hook", "puts \"Hello\""]}
  ],
  "rtl_changes": null,
  "declared_constraint_changes": {"CLOCK_PERIOD": null},
  "rationale": "Relieve localized congestion; do not relax user constraints."
}
```
Notes:
- `puts` shown above is only valid if Tcl is enabled and not forbidden; in restricted mode it would be rejected. This is illustrative only.

## A2) PatchRejected (schema_version=1)
```json
{
  "schema_version": 1,
  "patch_id": "uuid-or-hash",
  "stage": "PLACE_GLOBAL",
  "reason_code": "locked_constraint_backdoor",
  "offending_channel": "sdc_edits",
  "offending_commands": ["create_clock"],
  "offending_lines": [1],
  "remediation_hint": "CLOCK_PERIOD is locked. Improve timing via placement/CTS/routing knobs, not constraints."
}
```

## A3) MetricsPayload (schema_version=3)
```json
{
  "schema_version": 3,
  "run_id": "run_abcdef",
  "branch_id": "B0",
  "stage": "PLACE_GLOBAL",
  "attempt": 2,
  "execution_status": "success",
  "missing_metrics": [],
  "constraints_digest_path": "constraints/constraints_digest.json",
  "timing": {"setup_wns_ns": {"tt": -0.10}},
  "physical": {"core_area_um2": 1500000, "utilization_pct": 72.5},
  "route": {"congestion_overflow_pct": 8.2},
  "signoff": {"drc_count": null, "lvs_pass": null},
  "runtime": {"stage_seconds": 312.4}
}
```

## A4) ConstraintDigest (schema_version=1)
```json
{
  "schema_version": 1,
  "opaque": false,
  "clocks": [{"name": "core_clk", "period_ns": 10.0, "targets": ["clk"]}],
  "exceptions": {"false_path_count": 0, "multicycle_path_count": 0, "disable_timing_count": 0},
  "delays": {"set_max_delay_count": 0, "set_min_delay_count": 0},
  "uncertainty": {"set_clock_uncertainty_count": 0},
  "notes": []
}
```

---

# Appendix B: Constraint Command Maps
Map locked aspects → deny commands.

- `clock_period`:
  - create_clock
  - remove_clock
  - create_generated_clock
  - set_propagated_clock
  - (plus any tool-specific clock definition overrides)

- `timing_exceptions`:
  - set_false_path
  - set_multicycle_path
  - set_disable_timing
  - set_clock_groups
  - group_path
  - set_case_analysis

- `max_min_delay`:
  - set_max_delay
  - set_min_delay

- `clock_uncertainty`:
  - set_clock_uncertainty
  - set_clock_latency
  - set_clock_transition

Additionally, when ANY constraints are locked and Tcl is enabled:
- deny `read_sdc` (loader loophole)
- deny `source` and file IO tokens (already forbidden)

---

# Appendix C: SDC/Tcl Restricted Dialect
Restricted mode is designed to be “parseable enough” without a full Tcl parser.

## Restricted mode rules summary
- no semicolons
- no inline comments
- limited bracket expressions only (allowlist)
- denylist commands based on locked aspects
- forbid dangerous tokens (eval/source/exec/open/puts/file/glob)
- join line continuations before scanning

If user needs full Tcl power, they must opt into expert mode and accept reduced safety and `opaque=true` constraint digest risk.

---

# Appendix D: Macro Placement Mapping + Grid Snap

## Deterministic hint→coords resolver
- NW/NE/SW/SE/CENTER/PERIPHERY map to fixed percent points of core bbox.
- Multi-macro collisions resolved by deterministic offsets based on sorted instance names.

## Grid snap algorithm (FINAL)
1) Determine placement site size (w_um, h_um):
   - preferred: from tech LEF SITE named by PDK placement site setting
   - fallback: use DBU integer snapping only
2) Snap:
   - x := round(x / w_um) * w_um
   - y := round(y / h_um) * h_um
3) DBU roundtrip:
   - x_dbu := int(round(x * dbu_per_um))
   - x := x_dbu / dbu_per_um
   (same for y)

## Validation
- instance must exist in macro instances list
- orientation must be allowlisted
- x/y must be within die/core bounds if known

---

# Appendix E: State Path Rebasing
Tokenized mode is recommended.

Algorithm (tokenized):
- convert absolute paths under run_root_abs to `{{RUN_ROOT}}/<relpath>`
- at runtime resolve token:
  - local: token→run_root_abs
  - docker: token→docker.mount_root

Also log `state_rebase_map.json`.

---

# Appendix F: Directory Layout (FINAL)
Run root:
```
runs/<run_id>/
  manifest.json
  agentic_config.yaml
  baseline/
  branches/
    <branch_id>/
      tip.json
      stages/
        <stage>/
          attempt_001/
            proposals/
              try_001/
              try_002/
            patch.json
            metrics.json
            evidence.json
            constraints/
              constraints_digest.json
            judge_votes.json
            judge_aggregate.json
            lessons_learned.md
            agent_messages.jsonl
            llm_calls.jsonl
            state_in.json
            state_out.json
            state_rebase_map.json
            workspace/
            artifacts/
            artifacts_heavy.tar.zst
```
