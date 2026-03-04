# Overnight Session TODO — 2026-03-01

## Status Key
- [ ] Not started
- [~] In progress
- [x] Complete
- [!] Blocked / needs review

---

## HIGH Priority (Functional correctness)

- [x] **H1**: Wire SDC/Tcl scanners into ConstraintGuard
  - Wired `SDCScanner` and `TclScanner` into `_check_sdc_edits()` / `_check_tcl_edits()`
  - 17 new tests (10 SDC + 7 Tcl), all 35 total pass

- [x] **H2**: Connect SDC injection to LibreLane adapter
  - Added `_materialize_sdc_fragments()` to `LibreLaneLocalAdapter`
  - SDC fragments written to `workspace/constraints/` and injected via `PNR_SDC_FILE`

- [x] **H3**: Docker adapter implementation
  - Full `DockerAdapter` class with Docker execution support
  - 25 tests covering all paths (success, timeout, OOM, config error)
  - CLI updated to route `mode=docker` to Docker adapter

## MEDIUM Priority (Missing features from spec)

- [x] **M1**: Implement specialist agents (timing, routability, DRC)
  - `BaseSpecialist` abstract class with shared analysis pipeline
  - `TimingSpecialist`, `RoutabilitySpecialist`, `DRCSpecialist` implementations
  - 4 Jinja2 templates: `specialist_base.j2`, `specialist_timing.j2`, `specialist_routability.j2`, `specialist_drc.j2`
  - 28 tests, wired into orchestrator for plateau detection

- [x] **M2**: Implement master agent + `master.j2` template
  - Created `master.j2` with flow progress, dilemma, rollback targets, evidence, lessons
  - 13 new tests for template rendering

- [x] **M3**: Implement `agenticlane replay` command
  - Full replay implementation: loads manifest, shows summary, optional `--rerun`
  - 9 new tests

- [x] **M4**: Fix power metrics end-to-end
  - Added `PowerMetrics` schema to `MetricsPayload`
  - Rewrote `PowerExtractor` with OpenROAD 3-col/4-col format parsing
  - Wired into evidence assembly and scoring
  - 8 new tests across extractors, scoring, assembly, schemas

- [x] **M5**: Remove dead `instructor` dependency
  - Removed from pyproject.toml dependencies and mypy overrides

- [x] **M6**: Dashboard improvements
  - Self-contained HTML with embedded CSS (dark theme, offline-capable)
  - Run list page with summary stats
  - Run detail page: overview stats, branch timelines, score progression, judge votes,
    PatchRejected events, spatial hotspots with severity bars, evidence summary, hierarchical modules
  - API endpoints: /api/runs, /api/runs/{id}/manifest, /branches, /metrics, /evidence, /rejections
  - 17 tests for all rendering and data functions

## LOW Priority (Polish, docs, cleanup)

- [x] **L1**: Create PDK override YAML files
  - `sky130A.yaml` and `gf180mcu.yaml` with PDK-specific knob ranges

- [x] **L2**: Clean up empty scaffolding
  - Removed empty `cli/commands/` directory
  - `knowledge/` intentionally kept for future RAG work

- [x] **L3**: Fix `test_adapter_pipeline.py` (script -> test)
  - Converted to proper pytest test with `@pytest.mark.integration`
  - Added `@pytest.mark.skipif` for EDA tool availability
  - Replaced `print()` with proper assertions
  - Created `conftest.py` for integration tests

- [x] **L4**: Consolidate MockLLMProvider implementations
  - `tests/mocks/mock_llm.py` now extends `LLMProvider` (proper subclass)
  - Keeps rich test API (call_log, add_response, stage-based lookup)
  - Both mocks work correctly with their consumers

- [x] **L5**: Populate `tests/golden/schemas/` with golden JSON files
  - 6 golden files + 17 roundtrip tests

- [x] **L6**: Write README with install instructions, usage, architecture

- [x] **L7**: Add proper logging to all agents for trackability
  - Worker: start/end with stage, attempt, patch summary, latency
  - Judge: start/end with vote counts, hard gates, confidence, latency
  - Specialists: start/end with domain context, recommendations, latency
  - Agent loop: patch rejection, cognitive retry, stage pass/fail
  - Orchestrator: flow lifecycle, branches, plateau, deadlock, hierarchical events

---

## Final Results
- **1118 tests passing** (up from 984)
- **ruff**: All checks passed
- **mypy**: No issues found in 88 source files
- **ALL 16 items complete** (3 HIGH + 6 MEDIUM + 7 LOW)

---

## Next: RAG Knowledge System

Full implementation plan saved at: **`tracking/overnight-session/rag_plan.md`**

Key items:
- [ ] Pre-req: Wire specialist advice to workers (currently generated but not passed)
- [ ] Step 1: KnowledgeConfig + KnowledgeChunk schema
- [ ] Step 2: ChromaDB adapter (retriever.py + chroma_adapter.py)
- [ ] Step 3: Query builder (stage + metrics + errors → retrieval query)
- [ ] Step 4: Ingestors (EDA docs, prior runs, PDK guides, engineering notes)
- [ ] Step 5: Wire RAG into agent pipeline (orchestrator → agent_loop → worker → template)
- [ ] Step 6: CLI commands (agenticlane knowledge ingest-docs/ingest-run/ingest-notes/stats)
- [ ] Step 7: Auto-ingest after runs (feedback loop)
- [ ] Step 8: Tests (~40 new tests)
