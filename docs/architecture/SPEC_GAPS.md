# AgenticLane Spec v0.6 -- Identified Gaps & Resolutions

> **Purpose:** Document gaps, ambiguities, and missing details found in `AgenticLane_Build_Spec_v0.6_FINAL.md` during planning. Each gap has a proposed resolution.

---

## Critical Gaps

### Gap 1: KnobSpec Registry Data -- No Actual Knob Definitions

**What the spec says:** Section "KnobSpec + StageSpec Registries" (lines 979-1003) defines the KnobSpec schema (name, dtype, range, PDK overrides, safety tier, constraint flag, stage applicability) but provides **zero actual knob entries**.

**Why this matters:** Without a populated registry, agents don't know what they can tune, and KnobSpec validation is impossible.

**Resolution:** Extract knob definitions programmatically from LibreLane's source code:
- `librelane/steps/common_variables.py` -- Shared config variables with types, defaults, descriptions
- `librelane/config/variable.py` -- `Variable` dataclass with validation rules
- Individual step files (`openroad.py`, `yosys.py`, `odb.py`) -- Step-specific variables

Initial registry will cover these key knobs per stage:

| Stage | Key Knobs |
|-------|-----------|
| SYNTH | `SYNTH_STRATEGY`, `SYNTH_MAX_FANOUT`, `SYNTH_BUFFERING`, `SYNTH_SIZING` |
| FLOORPLAN | `FP_CORE_UTIL`, `FP_ASPECT_RATIO`, `FP_SIZING`, `DIE_AREA`, `FP_PDN_*` |
| PLACE_GLOBAL | `PL_TARGET_DENSITY_PCT`, `PL_ROUTABILITY_DRIVEN`, `PL_RESIZER_*` |
| PLACE_DETAILED | (limited -- mostly inherits from PLACE_GLOBAL) |
| CTS | `CTS_CLK_MAX_WIRE_LENGTH`, `CTS_SINK_CLUSTERING_SIZE`, `CTS_DISTANCE` |
| ROUTE_GLOBAL | `GRT_ADJUSTMENT`, `GRT_OVERFLOW_ITERS` |
| ROUTE_DETAILED | `DRT_OPT_ITERS` |

PDK-specific overrides for sky130 and gf180 will be included. Other PDKs: best-effort defaults with documentation to add overrides.

**Status:** Will be implemented in Phase 1 (P1.4).

---

### Gap 2: Prompt Templates -- Completely Absent

**What the spec says:** `agents/prompts/` directory is listed in the repo layout (line 290) but no prompt content, structure, or examples are provided anywhere in the spec.

**Why this matters:** The entire Cognition Plane depends on prompt quality. Bad prompts = bad patches = no value.

**Resolution:** Design prompts in Phase 3. Structure:

**Worker prompt (per-stage):**
- System: Role definition, stage context, constraints
- Context: MetricsPayload table, EvidencePack summary, allowed knobs with ranges, lessons_learned history
- Output: JSON schema for Patch model
- Few-shot: 1-2 examples of good patches for this stage

**Judge prompt:**
- System: Senior reviewer role, evaluation criteria
- Context: Before/after metrics comparison, evidence, constraint digest
- Output: JSON schema for JudgeVote (PASS/FAIL + blocking issues)

**Master prompt:**
- System: Lead architect role, cross-stage context
- Context: All stage metrics, worker complaints, branch status
- Output: JSON schema for MasterDecision (advance/retry/rollback/escalate)

**Specialist prompt (per-domain):**
- System: Domain expert role (timing/routability/DRC)
- Context: Relevant metrics subset, spatial hotspots, failure signatures
- Output: JSON schema for SpecialistAdvice (knob recommendations + rationale)

Templates stored as Jinja2 files in `agenticlane/agents/prompts/`:
- `worker_base.j2`
- `worker_synth.j2`, `worker_floorplan.j2`, `worker_placement.j2`, etc.
- `judge.j2`
- `master.j2`
- `specialist_timing.j2`, `specialist_routability.j2`, `specialist_drc.j2`

**Status:** Will be designed and implemented in Phase 3.

---

### Gap 3: Composite Scoring Formula

**What the spec says:** Section "Scoring + MCMM Normalization + Anti-Cheat" (lines 830-860) describes:
- Percent-over-baseline normalization with clamp and epsilon
- MCMM worst-corner reduction
- Effective setup period anti-cheat
- `intent.weights_hint` for user priorities

But **never defines the formula** for combining individual metric dimensions into one composite score.

**Why this matters:** The judge and branch pruning need a single comparable score.

**Resolution:** Implement as weighted sum:

```python
composite_score = sum(
    weight * normalized_metric_score(metric_name, current_value, baseline_value)
    for metric_name, weight in intent.weights_hint.items()
    if metric_name in available_metrics
)
```

Where `normalized_metric_score` uses percent-over-baseline:
```python
def normalized_metric_score(name, value, baseline, epsilon=1e-6, clamp=1.0):
    if baseline is None or value is None:
        return 0.0
    if abs(baseline) < epsilon:
        return 0.0
    # For metrics where lower is better (timing WNS, area, congestion):
    improvement = (baseline - value) / (abs(baseline) + epsilon)
    return max(-clamp, min(clamp, improvement))
```

For timing specifically, use **effective setup period** (anti-cheat):
```python
effective_setup = applied_clock_period - setup_wns  # from ConstraintDigest
# Score on effective_setup instead of raw WNS
```

Default weights if `weights_hint` is empty: `{"timing": 0.5, "area": 0.3, "route": 0.2}`

**Status:** Will be implemented in Phase 3 (P3.8).

---

### Gap 4: History Compaction Schema

**What the spec says:** Section "History compaction (MANDATORY)" (lines 808-814) says produce `lessons_learned.md` and `lessons_learned.json` with a "table", but does not define table columns or JSON schema.

**Why this matters:** History compaction is what makes multi-attempt learning work. Without a defined schema, the prompt context assembly is ad-hoc.

**Resolution:** Define schema:

```json
{
  "schema_version": 1,
  "stage": "PLACE_GLOBAL",
  "branch": "B0",
  "total_attempts": 5,
  "entries": [
    {
      "attempt": 1,
      "patch_summary": "FP_CORE_UTIL=55, PL_TARGET_DENSITY_PCT=65",
      "key_changes": {"FP_CORE_UTIL": [50, 55], "PL_TARGET_DENSITY_PCT": [60, 65]},
      "metrics_delta": {
        "setup_wns_ns": {"before": -0.5, "after": -0.3, "delta": "+0.2"},
        "utilization_pct": {"before": 72, "after": 75, "delta": "+3.0"}
      },
      "composite_score": 0.15,
      "judge_result": "PASS",
      "key_insight": "Increasing density improved timing but raised utilization",
      "was_rollback": false,
      "cognitive_retries": 0
    }
  ],
  "best_attempt": 3,
  "best_score": 0.28,
  "trend": "improving"
}
```

Markdown table for prompt inclusion:
```
| Attempt | Key Changes | WNS (ns) | Area (%) | Score | Result | Insight |
|---------|-------------|-----------|----------|-------|--------|---------|
| 1       | UTIL=55     | -0.3      | 75       | 0.15  | PASS   | ...     |
| 2       | UTIL=50     | -0.2      | 72       | 0.22  | PASS   | ...     |
```

Only the last N (configurable, default 5) attempts go into the prompt as full entries. Older attempts are summarized as a single "historical trend" paragraph.

**Status:** Will be implemented in Phase 3 (P3.7).

---

### Gap 5: RAG/Knowledge Layer

**What the spec says:** `knowledge/rag_interface.py` and `chroma_adapter.py` are listed in the repo layout (lines 297-298) but never specified. No mention of what data goes in, how it's indexed, or when it's queried.

**Why this matters:** Low priority -- the core system works without RAG. But it could significantly improve agent quality by providing EDA domain knowledge.

**Resolution:** Defer to post-Phase 5. When implemented:
- Index: EDA textbook knowledge, OpenROAD documentation, PDK-specific design rules, past successful runs
- Query: Agents query RAG for domain-specific guidance when proposing patches
- Implementation: ChromaDB with text embeddings, queried before prompt assembly

**Status:** Deferred. Not blocking any phase.

---

## Moderate Gaps

### Gap 6: Branch Divergence Strategy Details

**What the spec says:** Section "Branch generation strategies" (lines 592-596) lists two approaches:
1. Diverse sampling of knob sets (within KnobSpec)
2. Mutational hill climb from best patch

But provides no details on how diversity is measured or how mutations work.

**Resolution:**
- **Diverse sampling:** Generate N random patch proposals (within KnobSpec ranges), maximizing Euclidean distance in normalized knob space. Use simple Latin Hypercube Sampling or random sampling with a minimum distance threshold.
- **Mutational hill climb:** Take the best-scoring patch. For each knob, perturb by +/- 10-20% of its range. Generate M mutations, evaluate, keep the best.
- **Diversity metric:** Normalized L2 distance between knob vectors. If two branches have distance < threshold, prune the lower-scoring one.

**Status:** Phase 5 (P5.3).

---

### Gap 7: Orchestrator Crash Recovery / Resumability

**What the spec says:** "replay" mode replays LLM calls (line 1009) but there's no mention of recovering from an orchestrator crash mid-run.

**Resolution:** Implement checkpoint-based recovery:
- After each successful attempt, write a `checkpoint.json` to the branch directory with: current stage, last successful attempt, branch tip reference
- On startup, `agenticlane run --resume <run_id>` checks for `checkpoint.json` and resumes from the last successful stage/attempt
- The run manifest records whether the run was resumed

**Status:** Phase 5 (P5.4), as part of full flow orchestrator.

---

### Gap 8: LLM Call Logging Schema

**What the spec says:** "Every LLM call must be recorded (jsonl): model, provider, parameters, prompt hash, response hash" (lines 1014-1016) but no JSONL schema is defined.

**Resolution:**
```json
{
  "timestamp": "2025-01-15T10:30:00Z",
  "call_id": "uuid",
  "model": "qwen/qwen3-coder-30b",
  "provider": "litellm",
  "role": "worker",
  "stage": "PLACE_GLOBAL",
  "attempt": 2,
  "branch": "B0",
  "parameters": {
    "temperature": 0.0,
    "seed": 42,
    "max_tokens": 4096,
    "response_model": "Patch"
  },
  "prompt_hash": "sha256:abc123...",
  "response_hash": "sha256:def456...",
  "latency_ms": 3200,
  "tokens_in": 1500,
  "tokens_out": 800,
  "structured_output_valid": true,
  "retries": 0,
  "error": null
}
```

Full prompt/response stored only in debug mode (under `attempt_dir/llm_calls_debug/`).

**Status:** Phase 3 (P3.3).

---

### Gap 9: EvidencePack Schema

**What the spec says:** The term "EvidencePack" is used throughout but Appendix A only defines Patch, PatchRejected, MetricsPayload, and ConstraintDigest. No schema for EvidencePack.

**Resolution:** Define based on spec references:
```json
{
  "schema_version": 1,
  "stage": "ROUTE_DETAILED",
  "attempt": 3,
  "execution_status": "success",
  "errors": [
    {"source": "OpenROAD.DetailedRouting", "severity": "error", "message": "...", "count": 5}
  ],
  "warnings": [
    {"source": "Checker.TrDRC", "severity": "warning", "message": "...", "count": 12}
  ],
  "spatial_hotspots": [
    {
      "type": "congestion",
      "grid_bin": {"x": 0, "y": 1},
      "region_label": "NE",
      "severity": 0.85,
      "nearby_macros": ["U_SRAM_0", "U_SRAM_1"]
    }
  ],
  "crash_info": null,
  "missing_reports": [],
  "stderr_tail": null,
  "bounded_snippets": [
    {"source": "timing_report", "content": "...(first 50 lines)..."}
  ]
}
```

**Status:** Phase 1 (P1.3).

---

### Gap 10: `agenticlane init` Behavior

**What the spec says:** CLI command listed (line 1022) but no details on what it creates.

**Resolution:**
```bash
agenticlane init --design my_block --pdk sky130A
```
Creates:
```
my_block/
├── agentic_config.yaml    # From safe profile template, design name filled in
├── design/
│   └── config.yaml        # LibreLane config template
└── src/
    └── (placeholder README)
```

**Status:** Phase 1 (P1.12).

---

## Minor Gaps

### Gap 11: Docker Image Build (Dockerfile)

**What the spec says:** Docker supported (R3) but no Dockerfile specified.

**Resolution:** Defer Dockerfile to Phase 5. Use LibreLane's built-in `--containerized` mode for now, which handles its own container setup.

---

### Gap 12: PDK Override File Location

**What the spec says:** KnobSpec has `pdk_overrides` field but doesn't say where PDK-specific range data lives.

**Resolution:** Ship PDK overrides as YAML files in `agenticlane/config/pdk_overrides/`:
- `sky130A.yaml` -- knob range overrides for sky130
- `gf180mcu.yaml` -- knob range overrides for gf180
- Config loader merges these when PDK is specified

---

### Gap 13: Dashboard Technology

**What the spec says:** "Must work offline, reading run folder JSON files" and lists features (lines 1043-1050) but no framework specified.

**Resolution:** FastAPI + Jinja2 templates + vanilla JS. No React/Vue/heavy framework. Reads JSON from the run directory, renders interactive HTML pages. Served locally on a configurable port (default 8080).

---

### Gap 14: Signoff Hard Gates

**What the spec says:** `signoff_hard_gates: ["drc_clean", "lvs_pass"]` (lines 489-490) but doesn't specify whether these apply only at SIGNOFF stage or at any stage.

**Resolution:** Signoff hard gates apply only when `stage == "SIGNOFF"`. At other stages, only `hard_gates` (execution_success, metrics_parse_valid) apply.

---

### Gap 15: Multiple STAMidPNR Steps with Same ID

**What the spec says:** The Classic flow has multiple steps with the same base name `OpenROAD.STAMidPNR` appearing in different stages (CTS, ROUTE_GLOBAL).

**Resolution:** LibreLane uses step indices internally. When specifying `--from`/`--to`, we may need to use step indices or fully qualified IDs. Investigate LibreLane's internal step numbering. If step IDs are not unique, use index-based addressing or the step substitution mechanism for disambiguation.

**Status:** Investigate during Phase 1 (P1.4) when building the stage graph.
