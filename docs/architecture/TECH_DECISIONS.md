# AgenticLane Technical Decisions

> **Purpose:** Record key technical decisions made during planning, with rationale and alternatives considered. These decisions should be followed during implementation.

---

## Decision 1: Async from Start (asyncio)

**Decision:** Design the orchestrator with `async/await` from Phase 1, even though parallel branches aren't needed until Phase 5.

**Rationale:**
- Phase 5 parallel branch exploration requires concurrent EDA executions with semaphore-based scheduling
- Retrofitting async onto a synchronous codebase is a painful, error-prone refactor
- Modern Python async is mature and well-supported by the dependency stack (LiteLLM, httpx, aiofiles)
- In Phases 1-4, the async loop runs sequentially (one branch, one job at a time) -- the overhead is minimal

**Alternatives considered:**
- *Start synchronous, refactor later:* Simpler initially but creates technical debt. Risk of subtle bugs during refactor.
- *Sync + multiprocessing:* Heavier isolation (separate processes), more complex state sharing, harder to debug. Better for CPU-bound work, but EDA tools are subprocess-based so asyncio subprocess management is natural.

**Implementation notes:**
- Use `asyncio.run()` as the top-level entry from CLI
- Use `asyncio.create_subprocess_exec()` for running LibreLane/EDA tools
- Use `asyncio.Semaphore(max_parallel_jobs)` for concurrency control
- Use `asyncio.wait_for()` for tool timeouts
- Use `aiofiles` for async file I/O where needed
- Tests use `pytest-asyncio`

---

## Decision 2: instructor + LiteLLM for LLM Provider

**Decision:** Use the `instructor` library on top of `litellm` for structured output enforcement.

**Rationale:**
- **LiteLLM** abstracts 100+ LLM providers (LM Studio, Ollama, OpenAI, Anthropic, etc.) behind a single API. Users don't need to configure provider-specific code.
- **instructor** adds Pydantic model validation on top of LiteLLM responses. It automatically retries when the LLM output doesn't match the schema. This directly satisfies spec requirement R11 (structured LLM output enforcement).
- User specifically wants maximum user-friendliness. This stack requires minimal configuration: just set `OPENAI_API_BASE=http://localhost:1234/v1` for LM Studio and it works.

**Alternatives considered:**
- *LiteLLM only:* Would require building custom JSON schema validation, retry logic, and extraction fallbacks from scratch. Duplicates what instructor already does.
- *Custom provider layer:* Maximum control but significant implementation effort. No benefit over LiteLLM for standard providers.

**Configuration for common setups:**

```yaml
# LM Studio (local)
llm:
  mode: local
  provider: litellm
  models:
    worker: "openai/local-model"
    judge: ["openai/local-model"]
# Set env: OPENAI_API_BASE=http://localhost:1234/v1

# Ollama (local)
llm:
  mode: local
  provider: litellm
  models:
    worker: "ollama/qwen2.5-coder:32b"
    judge: ["ollama/qwen2.5-coder:32b"]

# OpenAI API
llm:
  mode: api
  provider: litellm
  models:
    worker: "gpt-4o"
    judge: ["gpt-4o", "gpt-4o-mini", "gpt-4o"]
# Set env: OPENAI_API_KEY=sk-...

# Anthropic API
llm:
  mode: api
  provider: litellm
  models:
    worker: "claude-sonnet-4-20250514"
    judge: ["claude-sonnet-4-20250514"]
# Set env: ANTHROPIC_API_KEY=sk-...
```

**Fallback chain for structured output:**
1. `instructor` with `response_model=PydanticModel` -- handles schema enforcement and automatic retries
2. If provider doesn't support structured output: extract JSON from response using regex (look for ```json blocks or raw JSON objects)
3. If extraction fails after `max_retries`: log error, return None (triggers cognitive retry)

---

## Decision 3: Phase-by-Phase Build

**Decision:** Build each phase completely (with tests and acceptance criteria) before starting the next.

**Rationale:**
- Each phase builds on the previous. Phase 2 (ConstraintGuard) depends on Phase 1 (schemas, config, execution). Phase 3 (agents) depends on Phase 2 (cognitive retry).
- Testing incrementally catches integration issues early. A "scaffold everything" approach defers integration testing.
- Each phase has clear acceptance criteria from the spec. Passing them provides confidence before adding complexity.
- Prevents the "everything is half-built, nothing works" problem.

**Phase order and dependencies:**
```
Phase 0 (Bootstrap) --> Phase 1 (Backbone) --> Phase 2 (ConstraintGuard)
                                            --> Phase 3 (Agent Loop)
                                            --> Phase 4 (Rollback)
                                            --> Phase 5 (Full Flow + Parallel)
```

---

## Decision 4: Mock-First Testing Strategy

**Decision:** Build `MockExecutionAdapter` and `MockLLMProvider` as first-class testing infrastructure. All development and testing proceeds against mocks until real LibreLane integration.

**Rationale:**
- LibreLane + EDA tools require significant setup (PDK installation, tool compilation, disk space). Not feasible for CI or rapid development.
- Mocks allow testing the entire orchestration, distillation, and agent stack without EDA tools
- Mock adapter can be configured to simulate realistic behavior: gradual improvement, specific failure modes, PDK-specific metric ranges
- Mock LLM provider enables deterministic testing of the agent loop

**Mock design principles:**
- `MockExecutionAdapter` is deterministic: same inputs -> same outputs (with configurable noise)
- It responds to knob changes: e.g., lowering `FP_CORE_UTIL` increases area but reduces congestion
- It can inject failure modes: crash at specific stages, timeout, OOM
- It produces realistic directory structures with synthetic files
- `MockLLMProvider` returns pre-recorded responses keyed by prompt hash
- Both mocks are reusable across all test types (unit, integration, E2E)

---

## Decision 5: Pydantic v2 for All Data Models

**Decision:** Use Pydantic v2 `BaseModel` for all schemas (Patch, MetricsPayload, EvidencePack, etc.) and `BaseSettings` for configuration.

**Rationale:**
- Spec requires schema validation (R11) and JSON serialization -- Pydantic does both
- Pydantic v2 is significantly faster than v1 (Rust-based core)
- `BaseSettings` integrates YAML loading, env var override, and CLI integration
- instructor library requires Pydantic models for structured output enforcement
- Type safety with mypy integration

**Implementation notes:**
- All schemas have `schema_version` field for forward compatibility
- Use `model_dump(mode="json")` for serialization
- Use `model_validate_json()` for deserialization
- Custom validators for domain-specific constraints (e.g., knob ranges, path formats)

---

## Decision 6: Typer for CLI

**Decision:** Use Typer (built on Click) for the CLI framework.

**Rationale:**
- Typer provides automatic help generation, type-based argument parsing, and Rich integration
- It's built on Click, which LibreLane also uses -- consistent ecosystem
- Rich integration gives us formatted tables and progress bars for free
- Simple to add commands incrementally as phases progress

**Note:** LibreLane uses Click directly. AgenticLane uses Typer (which wraps Click). There's no conflict -- AgenticLane's CLI is separate from LibreLane's CLI.

---

## Decision 7: Jinja2 for Prompt Templates

**Decision:** Store LLM prompts as Jinja2 templates (`.j2` files) in `agenticlane/agents/prompts/`.

**Rationale:**
- Prompts need variable substitution (metrics, knobs, history) -- Jinja2 is the standard
- Templates are version-controlled and diffable
- Supports conditionals and loops (e.g., variable-length metrics tables)
- Jinja2 is already a dependency (used by FastAPI/Jinja2 for dashboard)
- Templates can be overridden by users for customization

**Template structure:**
```
prompts/
  worker_base.j2          # Shared worker system prompt components
  worker_synth.j2         # Synthesis-specific worker prompt
  worker_floorplan.j2     # Floorplan-specific worker prompt
  worker_placement.j2     # Placement-specific worker prompt
  worker_cts.j2           # CTS-specific worker prompt
  worker_routing.j2       # Routing-specific worker prompt
  judge.j2                # Judge evaluation prompt
  master.j2               # Master decision prompt
  specialist_timing.j2    # Timing specialist prompt
  specialist_routability.j2 # Routability specialist prompt
  specialist_drc.j2       # DRC specialist prompt
```

---

## Decision 8: ZSTD for Artifact Compression

**Decision:** Use Zstandard (zstd) for compressing heavy artifacts, as specified in the spec.

**Rationale:**
- Better compression ratio than gzip for binary EDA artifacts (ODB, DEF, GDS)
- Faster compression/decompression than gzip or bzip2
- Python `zstandard` library is mature and well-maintained
- Spec explicitly requires it (`compression: "zstd"`)

---

## Decision 9: Start with sky130 PDK

**Decision:** Target sky130 as the primary PDK for development and testing. Add gf180 support second.

**Rationale:**
- sky130 is the most widely used open-source PDK
- Best documented with most community support
- LibreLane's examples (SPM) use sky130
- KnobSpec ranges and PDK overrides will be validated against sky130 first
- gf180 support is CI-required (per spec "Certified CI set") but can come after core functionality works

---

## Decision 10: No Separate Database -- JSON Files Only

**Decision:** Use JSON files in the run directory as the sole data store. No SQLite, no external database.

**Rationale:**
- Spec requires offline/local-first operation
- Run directories are self-contained and portable
- JSON files are human-readable and debuggable
- The dashboard reads from JSON files directly
- No additional dependency or setup required
- Reproducibility: the entire run state is in the filesystem

**Trade-offs:**
- Querying across runs requires scanning directories (acceptable for expected run counts)
- No concurrent write safety (mitigated by per-attempt directory isolation)
- Large runs produce many small files (mitigated by GC and compression)

---

## Decision 11: FastAPI + Jinja2 for Dashboard

**Decision:** Use FastAPI with Jinja2 templates and vanilla JavaScript for the local dashboard.

**Rationale:**
- Lightweight -- no Node.js build chain, no React/Vue bundling
- FastAPI is async-native (matches our architecture)
- Jinja2 templates for server-rendered HTML
- Vanilla JS for client-side interactivity (chart rendering, filtering)
- Dashboard reads JSON from run directory -- no database or API server needed
- Can be run as `agenticlane dashboard <run_id>` with a single command

**Alternative considered:**
- *Static HTML generator:* Even simpler but no interactivity. Fine for reports but not for exploratory dashboard.
- *React SPA:* Overkill for a local tool. Adds build complexity and Node.js dependency.

---

## Decision 12: Tokenized Path Rebasing (Default)

**Decision:** Use `tokenized` mode as the default path rebasing strategy, as recommended by the spec.

**Rationale:**
- Portable across local and Docker execution modes
- `{{RUN_ROOT}}/relative/path` is human-readable and debuggable
- Simple token replacement at runtime
- `state_rebase_map.json` provides an audit trail

**Implementation:**
```python
def tokenize_path(abs_path: str, run_root: str) -> str:
    rel = os.path.relpath(abs_path, run_root)
    return f"{{{{RUN_ROOT}}}}/{rel}"

def detokenize_path(tokenized: str, run_root: str) -> str:
    return tokenized.replace("{{RUN_ROOT}}", run_root)
```

For Docker mode, `detokenize_path` uses the Docker mount root instead of the local run root.

---

## Decision Summary Table

| # | Decision | Choice | Phase |
|---|----------|--------|-------|
| 1 | Concurrency model | asyncio from start | P0 |
| 2 | LLM provider stack | instructor + LiteLLM | P3 |
| 3 | Build approach | Phase-by-phase | All |
| 4 | Testing strategy | Mock-first | P0 |
| 5 | Data models | Pydantic v2 | P0 |
| 6 | CLI framework | Typer | P0 |
| 7 | Prompt templates | Jinja2 (.j2 files) | P3 |
| 8 | Artifact compression | Zstandard (zstd) | P1 |
| 9 | Primary PDK | sky130 first, then gf180 | P1 |
| 10 | Data storage | JSON files in run directory | P1 |
| 11 | Dashboard | FastAPI + Jinja2 + vanilla JS | P5 |
| 12 | Path rebasing | Tokenized ({{RUN_ROOT}}) | P1 |
