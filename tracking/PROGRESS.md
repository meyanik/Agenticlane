# AgenticLane Progress Tracker

## Current State
- **Phase:** Dashboard v2 Complete
- **Sub-task:** N/A
- **Status:** COMPLETE
- **Summary:** All phases (0-6), post-phase enhancements, and Dashboard v2 done. Dashboard v2: React 19 + TypeScript + Vite frontend, FastAPI backend with REST + SSE, per-stage model assignment, real-time run monitoring, subprocess-based run launcher. 46 new dashboard tests added.
- **Test count:** 1200 unit tests passing, 6 skipped
- **Code quality:** ruff clean, mypy clean (96 source files)

---

## Phase 0: Project Bootstrap

- [x] **P0.1** Create all directories and `__init__.py` files for package structure `[20 tests]`
- [x] **P0.2** Write `pyproject.toml` with full dependency list `[tested]`
- [x] **P0.3** Write CLI skeleton (`agenticlane/cli/main.py`) with Typer stubs: init, run, report, dashboard, replay `[tested]`
- [x] **P0.4** Write config files (`.gitignore`, `ruff.toml`, `mypy.ini`) `[tested]`
- [x] **P0.5** Write `tests/conftest.py` with basic fixtures `[tested]`
- [x] **P0.6** Verify: `pip install -e ".[dev]"`, `agenticlane --help`, `pytest`, `ruff check`, `mypy` `[tested]`

## Phase 1: Deterministic Backbone (No LLM)

- [x] **P1.1** Config Models (`agenticlane/config/models.py`) -- Full Pydantic v2 config skeleton with validators `[tested]`
- [x] **P1.2** Config Loader (`agenticlane/config/loader.py`) -- Merge chain: profile -> user -> CLI -> env; default profiles `[21 tests]`
- [x] **P1.3** Canonical Schemas (`agenticlane/schemas/`) -- All Appendix A schemas as Pydantic models `[25 tests]`
- [x] **P1.4** Stage/Knob Registries -- STAGE_GRAPH, StageSpec, KNOB_REGISTRY, KnobSpec `[33 tests]`
- [x] **P1.5** Execution Adapter ABC (`agenticlane/execution/adapter.py`) -- Abstract run_stage interface `[3 tests]`
- [x] **P1.6** Mock Execution Adapter (`tests/mocks/mock_adapter.py`) -- Configurable, deterministic mock `[43 tests]`
- [x] **P1.7** Workspace Manager (`agenticlane/execution/workspaces.py`) -- Attempt dir creation, hardlink cloning `[8 tests]`
- [x] **P1.8** State Baton (`agenticlane/execution/state_handoff.py` + `state_rebase.py`) -- Tokenize/detokenize, rebase map `[10 tests]`
- [x] **P1.9** Distillation Layer (`agenticlane/distill/`) -- Extractor registry, all extractors, EvidencePack assembly `[71 tests]`
- [x] **P1.10** Artifact GC (`agenticlane/orchestration/gc.py`) -- File classification, GC policies, filesystem locks `[32 tests]`
- [x] **P1.11** Orchestrator Sequential (`agenticlane/orchestration/orchestrator.py`) -- Async main loop, stage iteration, gating `[19 tests]`
- [x] **P1.12** CLI Phase 1 (`agenticlane/cli/main.py`) -- Flesh out init, run, report commands `[16 tests]`

## Phase 2: ConstraintGuard + Cognitive Retry

- [x] **P2.1** ConstraintGuard Validator (`agenticlane/orchestration/constraint_guard.py`) -- locked_vars, SDC/Tcl dialect, PatchRejected `[18 tests]`
- [x] **P2.2** Line Continuation Preprocessing -- Join backslash lines, max limit, unterminated rejection `[18 tests]`
- [x] **P2.3** SDC Scanner (`agenticlane/orchestration/sdc_scanner.py`) -- Deny-list commands, bracket parsing, forbidden tokens `[20 tests]`
- [x] **P2.4** Tcl Scanner (`agenticlane/orchestration/tcl_scanner.py`) -- Restricted Tcl dialect, read_sdc loophole rejection `[16 tests]`
- [x] **P2.5** Cognitive Retry Loop (`agenticlane/orchestration/cognitive_retry.py`) -- Free retries, proposal recording `[13 tests]`
- [x] **P2.6** Patch Materialization Pipeline (`agenticlane/execution/patch_materialize.py`) -- 10-step mandatory order `[15 tests]`

## Phase 3: Single-Stage Agent Loop

- [x] **P3.1** LLM Provider Stack (`agenticlane/agents/llm_provider.py`) -- Async LLM interface, structured output, retry logic `[36 tests]`
- [x] **P3.2** LLM Call Logging (`agenticlane/agents/llm_provider.py`) -- JSONL schema, response hashing, call records `[included in P3.1]`
- [x] **P3.3** Worker Agent (`agenticlane/agents/workers/`) -- Base class + stage-specific workers `[17 tests]`
- [x] **P3.4** Judge Ensemble (`agenticlane/judge/ensemble.py`) -- Majority voting, tie-breaking, deterministic gates `[21 tests]`
- [x] **P3.5** Scoring Formula (`agenticlane/judge/scoring.py`) -- Composite score, normalization, anti-cheat `[19 tests]`
- [x] **P3.6** Prompt Templates (`agenticlane/agents/prompts/`) -- Jinja2 templates for all agent roles `[14 tests]`
- [x] **P3.7** History Compaction (`agenticlane/orchestration/compaction.py`) -- lessons_learned table, sliding window `[16 tests]`
- [x] **P3.8** Single-Stage Flow (`agenticlane/orchestration/agent_loop.py`) -- Full agent loop integration `[11 tests]`

## Phase 4: Rollback + Spatial Actuator

- [x] **P4.1** Rollback Engine -- Cross-stage rollback, master decides retry vs rollback, checkpoint selection `[27 tests]`
- [x] **P4.2** Spatial Hotspot Extraction -- Congestion hotspot grid bins, coordinates, severity, nearby macros `[18 tests]`
- [x] **P4.3** Macro Placement Worker -- macro_placements[] in patch, grid snap, collision detection `[60 tests]`
- [x] **P4.4** MACRO_PLACEMENT_CFG Materialization -- Convert patch to LibreLane config format, PatchMaterializer steps 4+5 `[19 tests]`

## Phase 5: Full Flow + Parallel Branches

- [x] **P5.1** Scheduler + Branch Manager (`agenticlane/orchestration/scheduler.py`) -- Branch IDs, status tracking, divergence strategies `[34 tests]`
- [x] **P5.2** Parallel Job Scheduling -- asyncio.Semaphore, isolated workspaces per branch `[9 tests]`
- [x] **P5.3** Pruning + Selection -- Score-based pruning, best branch selection `[12 tests]`
- [x] **P5.4** Zero-Shot Initialization -- IntentProfile -> global_init_patch.json for all branches `[12 tests]`
- [x] **P5.5** Plateau Detection -- Sliding window scoring, specialist agent triggering `[8 tests]`
- [x] **P5.6** Cycle Detection -- Patch hash dedup, cycle event logging `[7 tests]`
- [x] **P5.7** Deadlock Policy -- ask_human / auto_relax / stop enum and enforcement `[10 tests]`
- [x] **P5.8** Reproducibility + Manifest (`runs/<run_id>/manifest.json`) -- Full provenance, replay mode `[14 tests]`
- [x] **P5.9** Report Generation (`agenticlane report`) -- Rich terminal tables, JSON report `[8 tests]`
- [x] **P5.10** Dashboard (`agenticlane dashboard`) -- FastAPI + Jinja2, metrics plots, readonly inspector `[24 tests]`
- [x] **P5.11** Checkpoint + Resume -- checkpoint.json per attempt, `--resume` flag `[11 tests]`
- [x] **P5.12** Full Integration Test -- E2E: 3 branches, 10 stages, parallel, pruning, manifest, report `[12 tests]`

## Phase 6: Real Execution + End-to-End

- [x] **P6.1** LibreLane Local Adapter (`agenticlane/execution/librelane_adapter.py`) -- Config.load, Classic.start, asyncio.to_thread, artifact collection `[19 tests]`
- [x] **P6.2** LiteLLM Provider (`agenticlane/agents/litellm_provider.py`) -- litellm.acompletion, model prefix routing, structured output, local LLM support `[24 tests]`
- [x] **P6.3** Example Design Bundle (`examples/counter_sky130/`, `examples/counter_gf180/`) -- 8-bit counter, sky130+gf180 configs `[22 tests]`
- [x] **P6.4** Report Parser Adaptation -- Real OpenROAD/Magic/Netgen formats added to all extractors `[22 tests]`
- [x] **P6.5** CLI Wiring (`agenticlane/cli/main.py`) -- LibreLaneLocalAdapter + LiteLLMProvider in non-mock path `[2 tests]`
- [x] **P6.6** E2E Integration Test (`tests/integration/test_e2e_real.py`) -- 5 e2e tests (skip if no LibreLane/PDK/key) `[5 tests, skipped]`

---

## Blocked / Issues

_None currently._

---

## Post-Phase: Agent-Driven Physical Parameters + Flow Mode

- [x] **PP.1** Add `flow_mode` to `DesignConfig` (flat/hierarchical/auto) `[6 tests]`
- [x] **PP.2** Add `--flow-mode` CLI flag + interactive prompt when auto `[tested]`
- [x] **PP.3** Record `flow_mode` in manifest `[3 tests]`
- [x] **PP.4** Add `DIE_AREA` knob to knob registry + list-type validation `[8 tests]`
- [x] **PP.5** Add `SynthesisMetrics` to `MetricsPayload` `[4 tests]`
- [x] **PP.6** Create `SynthExtractor` for yosys log parsing `[5 tests]`
- [x] **PP.7** Register `SynthExtractor` and wire into evidence assembly `[tested]`
- [x] **PP.8** Add `refine_after_synth()` to `ZeroShotInitializer` `[9 tests]`
- [x] **PP.9** Wire orchestrator: store synth metrics, call post-synth refinement `[tested]`
- [x] **PP.10** Pass synth stats to worker agents + update floorplan prompt `[tested]`
- [x] **PP.11** Update `init` command template with auto-sizing comments `[tested]`

---

## Post-Phase: Hierarchical Flow Mode

- [x] **PH.1** Add `ModuleConfig` + `modules` field to `DesignConfig` with validator `[8 tests]`
- [x] **PH.2** Create `HierarchicalConfigPatcher` for MACROS injection `[6 tests]`
- [x] **PH.3** Add `_run_hierarchical()`, `_build_module_config()`, `_collect_module_artifacts()` to orchestrator `[11 tests]`
- [x] **PH.4** Add `module_results` + `record_module()` to manifest `[4 tests]`
- [x] **PH.5** Add `module_context` param to worker/agent_loop + hierarchical prompt blocks `[8 tests]`
- [x] **PH.6** Update CLI: remove stub, add hierarchical validation `[tested]`
- [x] **PH.7** Add `create_module_dir()` to WorkspaceManager `[2 tests]`
- [x] **PH.8** Mock adapter: LEF/GDS generation for signoff `[3 tests]`
- [x] **PH.9** PicoSoC hierarchical example configs `[tested]`
- [x] **PH.10** Integration test: 2-module hierarchical flow + flat regression `[2 tests]`

---

## Post-Phase: Local LLM Integration

- [x] **PL.1** Add `api_base` field to `LLMConfig` for custom endpoints `[tested]`
- [x] **PL.2** Local mode in LiteLLMProvider: api_base, api_key, response_format handling `[10 tests]`
- [x] **PL.3** Think tag stripping for Qwen3/DeepSeek-R1 chain-of-thought `[5 tests]`
- [x] **PL.4** Model prefix routing for local servers (openai/ prefix) `[tested]`
- [x] **PL.5** Local hierarchical example config `[tested]`
- [x] **PL.6** E2E hierarchical PicoSoC with local LLMs (run_239134ef) `[verified]`

---

## Post-Phase: Overnight Hardening Session

- [x] **OH.1** Wire SDC/Tcl scanners into ConstraintGuard `[17 tests]`
- [x] **OH.2** Connect SDC injection to LibreLane adapter `[tested]`
- [x] **OH.3** Docker adapter implementation `[25 tests]`
- [x] **OH.4** Specialist agents (timing, routability, DRC) `[28 tests]`
- [x] **OH.5** Master agent template (master.j2) `[13 tests]`
- [x] **OH.6** Replay command implementation `[9 tests]`
- [x] **OH.7** Power metrics end-to-end fix `[8 tests]`
- [x] **OH.8** Remove instructor dependency `[tested]`
- [x] **OH.9** Dashboard improvements (full HTML, dark theme, all spec views) `[17 tests]`
- [x] **OH.10** PDK override YAML files `[tested]`
- [x] **OH.11** Clean up empty scaffolding `[tested]`
- [x] **OH.12** Integration test conversion `[tested]`
- [x] **OH.13** MockLLMProvider consolidation `[tested]`
- [x] **OH.14** Golden schema files + roundtrip tests `[17 tests]`
- [x] **OH.15** README rewrite `[tested]`
- [x] **OH.16** Structured agent logging `[tested]`

---

## Post-Phase: Deferred Error Handling + RAG Observability

- [x] **PD.1** Fix LibreLane deferred DRC/LVS errors classified as `tool_crash` → now `success` when flow completes `[tested]`
- [x] **PD.2** RAG logging upgraded from DEBUG to WARNING level for console visibility `[tested]`
- [x] **PD.3** Counter flat flow E2E with local LLM + RAG: 10/10 stages, all signoff clean `[verified]`
- [x] **PD.4** Local LLM counter config (`examples/counter_sky130/agentic_config_local.yaml`) `[tested]`

---

## Post-Phase: Dashboard v2

- [x] **D1** Per-stage model override config + LLM provider resolution `[15 tests]`
- [x] **D2** Backend API refactoring — 20+ REST endpoints in `dashboard_api.py` `[12 tests]`
- [x] **D3** SSE event bus + file watcher (`dashboard_events.py`) `[8 tests]`
- [x] **D4** Subprocess run manager (`dashboard_runner.py`) `[11 tests]`
- [x] **D5** React project setup + SVG Pipeline component `[build verified]`
- [x] **D6** HomePage + RunDetailPage `[build verified]`
- [x] **D7** LiveRunPage + SSE integration `[build verified]`
- [x] **D8** NewRunPage + per-stage model assignment UI `[build verified]`
- [x] **D9** StageDetailPage + educational features (glossary, tooltips) `[build verified]`
- [x] **D10** Tests + integration + build pipeline `[46 new tests, 1200 total]`

---

## Next Up

Project complete. All phases (0-6), post-phase enhancements, and Dashboard v2 done. All E2E runs verified.

Nice-to-haves (not blocking):
- Re-run hierarchical PicoSoC with deferred errors fix (should pass all 10 parent stages now)
- Improve `_basic_distill()` to extract DRC/LVS/timing into MetricsPayload (better judge quality)
- Vitest + React Testing Library for frontend component tests
- pixel-agents integration (shared dashboard shell)
