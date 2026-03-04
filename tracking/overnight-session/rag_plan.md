# Plan: RAG Knowledge System for AgenticLane

## Context

Agents currently operate with hardcoded prompt knowledge (Jinja2 templates with static tips) and short-term memory (lessons_learned from last 5 attempts). They have no access to:
- Prior run experience ("last time DRC violations near macros were fixed by CELL_PAD=4")
- EDA tool documentation ("what does GRT_ADJUSTMENT actually control?")
- PDK-specific design guides ("sky130 CTS needs expanded buffer lists above 30k cells")
- Human-curated engineering notes

The goal is to add a RAG (Retrieval-Augmented Generation) knowledge system that retrieves relevant context per-stage and injects it into agent prompts, improving patch quality — especially on first attempts and plateau situations.

---

## Pre-requisite: Wire specialist advice to workers (10 min fix)

**Before RAG**, fix the existing gap where specialist advice is generated but never reaches the worker.

**File:** `agenticlane/orchestration/orchestrator.py`
- In `_run_agentic_stage_for_branch()` (~line 338), pass `bstate.get("specialist_advice")` to `agent_loop.run_stage()`

**File:** `agenticlane/orchestration/agent_loop.py`
- Add `specialist_advice` param to `run_stage()`, pass it to `worker.propose_patch()`

**File:** `agenticlane/agents/workers/base.py`
- Add `specialist_advice` param to `propose_patch()`, add to `_build_context()` dict

**File:** `agenticlane/agents/prompts/worker_base.j2`
- Add `{% if specialist_advice %}` block rendering advice summary

This establishes the same wiring pattern RAG will follow.

---

## Step 1: Knowledge Config + Schema

**File:** `agenticlane/config/models.py` — add after `LLMConfig` (line 554)

```python
class KnowledgeCollections(BaseModel):
    """Which knowledge collections to query."""
    eda_docs: bool = True         # OpenROAD/Yosys/Magic documentation
    prior_runs: bool = True       # Lessons from previous runs
    pdk_guides: bool = True       # PDK-specific design guides
    engineering_notes: bool = True # Human-curated per-stage notes

class KnowledgeConfig(BaseModel):
    """RAG knowledge retrieval configuration."""
    enabled: bool = False
    backend: Literal["chromadb"] = "chromadb"
    db_path: Optional[Path] = None  # Defaults to <project>/.agenticlane/knowledge/
    embedding_model: str = "all-MiniLM-L6-v2"
    top_k: int = Field(default=5, ge=1, le=20)
    score_threshold: float = Field(default=0.3, ge=0.0, le=1.0)
    collections: KnowledgeCollections = Field(default_factory=KnowledgeCollections)
```

Add to `AgenticLaneConfig` (line 585): `knowledge: KnowledgeConfig = Field(default_factory=KnowledgeConfig)`

**File:** `agenticlane/schemas/knowledge.py` (NEW)

```python
class KnowledgeChunk(BaseModel):
    content: str                           # The retrieved text
    source: str                            # "openroad_docs", "run_abc123", "sky130_guide"
    collection: str                        # "eda_docs" | "prior_runs" | "pdk_guides" | "engineering_notes"
    stage: str                             # Stage relevance ("SYNTH", "CTS", "*")
    relevance_score: float                 # Cosine similarity 0.0-1.0
    metadata: dict[str, Any] = {}

class KnowledgeContext(BaseModel):
    chunks: list[KnowledgeChunk] = []
    query_used: str = ""
    retrieval_ms: float = 0.0
```

---

## Step 2: Knowledge Backend (ChromaDB Adapter)

**File:** `agenticlane/knowledge/retriever.py` (NEW) — abstract interface

```python
class KnowledgeRetriever(ABC):
    @abstractmethod
    async def retrieve(self, query: str, stage: str, top_k: int, filters: dict) -> list[KnowledgeChunk]: ...
    @abstractmethod
    async def ingest(self, chunks: list[KnowledgeChunk]) -> int: ...
    @abstractmethod
    async def collection_stats(self) -> dict[str, int]: ...
```

**File:** `agenticlane/knowledge/chroma_adapter.py` (NEW) — ChromaDB implementation

- 4 collections: `eda_docs`, `prior_runs`, `pdk_guides`, `engineering_notes`
- Uses `chromadb.PersistentClient` with sentence-transformer embeddings
- `retrieve()`: queries enabled collections with stage filter, merges results by score
- `ingest()`: adds chunks to appropriate collection, ChromaDB handles dedup by ID

### Collections overview

| Collection | Content | Example chunk |
|---|---|---|
| `eda_docs` | OpenROAD, Yosys, Magic docs | "GRT_ADJUSTMENT (float): Global routing adjustment. Higher values reduce congestion but increase wirelength." |
| `prior_runs` | Auto-extracted from completed runs | "Run run_47a5: PLACE_GLOBAL attempt 3: reduced PL_TARGET_DENSITY 0.6→0.45, congestion 92%→61%, score 0.32→0.71" |
| `pdk_guides` | PDK design rules, constraints | "sky130 hd: min metal1 pitch 0.46um, recommended CELL_PAD >= 4 for DRC-clean routing" |
| `engineering_notes` | Human-curated markdown per stage | "For CTS on designs >30k cells, expand CTS_CLK_BUFFER_LIST to include clkbuf_8 and _16" |

---

## Step 3: Query Builder

**File:** `agenticlane/knowledge/query_builder.py` (NEW)

Builds retrieval queries from current agent context (stage + metrics + errors):

```python
class QueryBuilder:
    def build_query(self, stage, metrics, evidence, plateau_info=None) -> str:
        parts = [f"ASIC {stage} stage optimization"]
        # Append problem-specific terms from metrics:
        #   timing violations → "setup timing violation WNS=-0.15ns"
        #   DRC violations → "DRC violations count=12"
        #   congestion → "routing congestion 85%"
        # Append top 3 error messages from evidence
        # If plateau → "optimization plateau, need alternative strategy"
        return ". ".join(parts)
```

---

## Step 4: Ingestors (Populate the Knowledge DB)

**File:** `agenticlane/knowledge/ingestors/docs_ingestor.py` (NEW)
- Parses markdown/RST EDA docs → chunks by `##` headers (~500 tokens each)
- Maps doc sections to stages (e.g., "Clock Tree Synthesis" → CTS)
- Metadata: `{tool, section, doc_path}`

**File:** `agenticlane/knowledge/ingestors/run_ingestor.py` (NEW)
- Reads `manifest.json` + evidence packs from completed runs
- For each stage decision: extracts what was tried, what worked, score changes
- Accepted patches → "what worked" chunks; rejected-then-fixed → "what to avoid" chunks
- Metadata: `{run_id, stage, attempt, score, pdk, design_name}`

**File:** `agenticlane/knowledge/ingestors/notes_ingestor.py` (NEW)
- Reads markdown files with YAML frontmatter (`stage:`, `pdk:`, `tags:`)
- Chunks by sections, preserves stage tags

---

## Step 5: Wire RAG into Agent Pipeline

### 5a. Orchestrator retrieves knowledge
**File:** `agenticlane/orchestration/orchestrator.py`

In `_run_agentic_stage_for_branch()`, before `agent_loop.run_stage()`:
- Build query from current metrics + evidence + stage
- Call `retriever.retrieve()` → `list[KnowledgeChunk]`
- Pass as `rag_context` parameter

### 5b. Agent loop passes to worker
**File:** `agenticlane/orchestration/agent_loop.py`

Add `rag_context: list[KnowledgeChunk] | None = None` to `run_stage()`. Pass to `worker.propose_patch()`.

### 5c. Worker adds to prompt context
**File:** `agenticlane/agents/workers/base.py`

Add `rag_context` to `propose_patch()` and `_build_context()`. Format chunks as markdown:
```python
def _format_rag_context(self, chunks):
    return "\n".join(f"- [{c.collection}/{c.source}] {c.content}" for c in chunks)
```

### 5d. Update prompt templates
**File:** `agenticlane/agents/prompts/worker_base.j2`

```jinja2
{% if rag_context %}
## Domain Knowledge (Retrieved)
{{ rag_context }}
{% endif %}
```

Also update `specialist_base.j2`.

---

## Step 6: CLI Commands

**File:** `agenticlane/cli/main.py`

```
agenticlane knowledge ingest-docs <docs_dir> --tool openroad
agenticlane knowledge ingest-run <run_dir>
agenticlane knowledge ingest-notes <notes_dir>
agenticlane knowledge stats
```

---

## Step 7: Auto-ingest after runs

**File:** `agenticlane/orchestration/orchestrator.py`

At end of `run_flow()`, after manifest write, if `knowledge.enabled` and `collections.prior_runs`:
- Call `RunIngestor().ingest_run(run_dir, retriever)`
- Each run automatically feeds back into the knowledge base

---

## Step 8: Tests (~40 tests)

| Test file | What it covers |
|---|---|
| `tests/knowledge/test_retriever.py` | ChromaRetriever init, ingest, retrieve, score filtering, stage filter |
| `tests/knowledge/test_query_builder.py` | Query generation from various metrics/evidence combinations |
| `tests/knowledge/test_ingestors.py` | DocsIngestor, RunIngestor, NotesIngestor with sample data |
| `tests/knowledge/test_integration.py` | Full pipeline: ingest → retrieve → format → inject into prompt |
| `tests/knowledge/test_config.py` | KnowledgeConfig validation, defaults, YAML roundtrip |

---

## File Summary

| # | File | Change |
|---|------|--------|
| 0 | `agenticlane/orchestration/orchestrator.py` | Pre-req: wire specialist advice to workers |
| 0 | `agenticlane/orchestration/agent_loop.py` | Pre-req: pass specialist advice through |
| 0 | `agenticlane/agents/workers/base.py` | Pre-req: add specialist_advice to context |
| 0 | `agenticlane/agents/prompts/worker_base.j2` | Pre-req: specialist_advice template block |
| 1 | `agenticlane/config/models.py` | `KnowledgeConfig` + `KnowledgeCollections` |
| 2 | `agenticlane/schemas/knowledge.py` | NEW: `KnowledgeChunk`, `KnowledgeContext` |
| 3 | `agenticlane/knowledge/__init__.py` | Exports |
| 4 | `agenticlane/knowledge/retriever.py` | NEW: `KnowledgeRetriever` ABC |
| 5 | `agenticlane/knowledge/chroma_adapter.py` | NEW: `ChromaRetriever` |
| 6 | `agenticlane/knowledge/query_builder.py` | NEW: `QueryBuilder` |
| 7 | `agenticlane/knowledge/ingestors/docs_ingestor.py` | NEW |
| 8 | `agenticlane/knowledge/ingestors/run_ingestor.py` | NEW |
| 9 | `agenticlane/knowledge/ingestors/notes_ingestor.py` | NEW |
| 10 | `agenticlane/orchestration/orchestrator.py` | RAG retrieval + auto-ingest |
| 11 | `agenticlane/orchestration/agent_loop.py` | Pass `rag_context` |
| 12 | `agenticlane/agents/workers/base.py` | `rag_context` in `_build_context()` |
| 13 | `agenticlane/agents/prompts/worker_base.j2` | RAG context template block |
| 14 | `agenticlane/agents/prompts/specialist_base.j2` | RAG context template block |
| 15 | `agenticlane/cli/main.py` | `knowledge` command group |
| 16 | `pyproject.toml` | Add `sentence-transformers` to knowledge extras |
| 17 | `tests/knowledge/test_*.py` | NEW: ~40 tests |

---

## Implementation Order

1. Pre-req: Wire specialist advice to workers (10 min)
2. Step 1: Config + schema
3. Step 2: ChromaDB adapter
4. Step 3: Query builder
5. Step 4: Ingestors
6. Step 5: Wire into agent pipeline
7. Step 6: CLI commands
8. Step 7: Auto-ingest
9. Step 8: Tests throughout

---

## YAML Config Example

```yaml
knowledge:
  enabled: true
  backend: chromadb
  db_path: .agenticlane/knowledge
  embedding_model: all-MiniLM-L6-v2
  top_k: 5
  score_threshold: 0.3
  collections:
    eda_docs: true
    prior_runs: true
    pdk_guides: true
    engineering_notes: true
```

---

## Verification

1. `pytest tests/knowledge/ -v` — all knowledge tests pass
2. `pytest tests/ -x -q --ignore=tests/integration/` — no regressions
3. `ruff check agenticlane/` + `mypy agenticlane/` — clean
4. `agenticlane knowledge ingest-notes examples/knowledge/` → ingests sample notes
5. `agenticlane knowledge ingest-run runs/<run_id>/` → ingests run data
6. `agenticlane knowledge stats` → shows collection sizes
7. E2E: run with `knowledge.enabled: true` → agents receive RAG context in prompts
