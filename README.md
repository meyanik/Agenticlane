# AgenticLane

Multi-agent orchestration layer for [LibreLane](https://github.com/librelane/librelane) RTL-to-GDS flows. AgenticLane adds an agentic control plane that iterates, backtracks, and uses LLM-powered judge-driven evaluation to improve chip design quality — while preventing constraint cheating and maintaining full reproducibility.

**Disclaimer:** Research/open-source only; no tapeout guarantees; users assume full responsibility for any use of generated designs.

## Features

- **10-stage ASIC pipeline**: SYNTH, FLOORPLAN, PDN, PLACE_GLOBAL, PLACE_DETAILED, CTS, ROUTE_GLOBAL, ROUTE_DETAILED, FINISH, SIGNOFF
- **Hierarchical flow mode**: Harden sub-modules independently, integrate as macros in parent design
- **Parallel branch exploration**: Multiple optimization strategies run concurrently with score-based pruning
- **ConstraintGuard**: Prevents LLM agents from cheating by relaxing design constraints (SDC/Tcl dialect scanning, locked variables)
- **Judge ensemble**: Majority-vote evaluation with deterministic hard gates (DRC clean, LVS pass)
- **Anti-cheat scoring**: Effective clock period detection prevents trivial timing improvements
- **Rollback engine**: Cross-stage rollback when optimization gets stuck
- **Plateau detection**: Specialist agents (timing, routability, DRC) activated on score plateaus
- **RAG knowledge base**: 14,000+ chunks from chip design literature for context-aware agent decisions
- **Real-time dashboard**: React + TypeScript UI for launching, monitoring, and analyzing runs
- **Local LLM support**: Run entirely on local models via LM Studio, Ollama, or vLLM (zero API cost)
- **Cloud LLM support**: Gemini, Claude, GPT-4 via LiteLLM routing
- **Full reproducibility**: Manifest with seeds, configs, and all decisions for deterministic replay

## Architecture

```
Cognition Plane (LLM-powered)
  Master Agent    Worker Agents    Specialist Agents    Judge Ensemble
       |               |                  |                  |
       +-------+-------+------------------+------------------+
               |
  ONLY: MetricsPayload, EvidencePack, ConstraintDigest, lessons_learned
               |
Distillation Plane (deterministic)
  Timing | Area | Route | DRC | LVS | Power | Spatial Hotspots
               |
Execution Plane (deterministic)
  LibreLane Local Adapter | Docker Adapter
  Per-attempt isolated workspace
  LibreLane + EDA Tools (OpenROAD, Yosys, Magic, KLayout, Netgen)
```

## E2E Results

| Design | PDK | Cells | GDS Size | DRC | Runtime | LLM |
|--------|-----|-------|----------|-----|---------|-----|
| Counter (8-bit) | sky130A | ~200 | 241 KB | Clean | ~15 min | Gemini 2.5 Pro |
| PicoSoC (RISC-V) | sky130A | 43K | 133 MB | Clean | ~3.4 hrs | Gemini 2.5 Pro |
| PicoSoC Hierarchical | sky130A | 43K | 127 MB | Clean | ~3 hrs | Qwen3-32B (local) |

---

## Getting Started

### Prerequisites

1. **Python 3.10+**
2. **LibreLane + EDA tools** — Available via Nix flake (provides Yosys, OpenROAD, Magic, KLayout, Netgen, Verilator):
   ```bash
   # Clone LibreLane alongside AgenticLane
   git clone https://github.com/librelane/librelane.git
   cd librelane && nix develop
   ```
3. **A SkyWater 130nm PDK** — Installed automatically by LibreLane on first run, or install manually:
   ```bash
   # Inside nix develop shell
   ciel install sky130
   ```
4. **An LLM** — Either a cloud API key (Gemini, OpenAI, Anthropic) or a local model server (LM Studio, Ollama, vLLM)

### Installation

```bash
# Clone the repository
git clone https://github.com/meyanik/Agenticlane.git
cd Agenticlane

# Install in development mode with all extras
pip install -e ".[dev,dashboard,knowledge]"

# Or minimal install (no dashboard, no RAG)
pip install -e .

# Verify installation
agenticlane --help
```

### Option A: Run from the Dashboard (Recommended)

The dashboard provides a visual interface for launching, monitoring, and analyzing runs.

```bash
# Start the dashboard (backend API + serves the frontend)
# Run from inside the nix develop shell so EDA tools are available
cd librelane && nix develop --command bash -c \
  'cd ../Agenticlane && agenticlane dashboard --dev --port 8000'
```

Then in a separate terminal, start the frontend dev server:

```bash
cd Agenticlane/dashboard-ui
npm install
npm run dev
```

Open **http://localhost:5173** in your browser. From here you can:

- **Launch a new run** — Click "+ New Run", pick a preset (Safe / Balanced / Aggressive), choose an example design or point to your own, select your LLM, and hit Launch
- **Monitor live runs** — Watch the 10-stage pipeline progress in real-time with SSE streaming
- **Analyze completed runs** — Click any run to see pipeline visualization, stage results, metrics, judge decisions, and agent activity logs
- **View agent logs** — Full terminal-style log viewer with filters by role (Worker/Judge/Master), stage, and search

#### Dashboard Features

- **Preset profiles**: Safe (conservative, 3 attempts), Balanced (recommended, 5 attempts), Aggressive (12 attempts, parallel branches)
- **Per-stage model assignment**: Use a bigger model for critical stages (CTS, routing) and a smaller one for others
- **Live pipeline visualization**: SVG pipeline with animated stage nodes and color-coded outcomes
- **Agent activity narrative**: Human-readable explanations of every agent decision, grouped by stage
- **Educational tooltips**: Every config field, metric, and stage has explanations written for VLSI beginners

### Option B: Run from the CLI

```bash
# Enter the nix develop shell (provides EDA tools)
cd librelane && nix develop

# Activate your Python venv
source ../.venv/bin/activate

# Run the counter example with a cloud LLM
export GOOGLE_API_KEY="your-key-here"
cd ../Agenticlane/examples/counter_sky130
agenticlane run agentic_config_e2e.yaml

# Or run with a local LLM (no API key needed)
agenticlane run agentic_config_local.yaml
```

### Option C: Initialize a New Project

```bash
agenticlane init --design my_chip --pdk sky130A
```

This creates a project directory with a starter `agentic_config.yaml`. Edit it to point to your Verilog sources and LibreLane config, then run:

```bash
agenticlane run agentic_config.yaml
```

---

## Configuration

### Using Cloud LLMs (Gemini, Claude, GPT-4)

```yaml
# agentic_config.yaml
llm:
  mode: "api"
  provider: "litellm"
  models:
    master: "gemini/gemini-2.5-pro"
    worker: "gemini/gemini-2.5-pro"
    judge:
      - "gemini/gemini-2.5-pro"
  temperature: 0.0
  seed: 42
```

Set the appropriate environment variable for your provider:
```bash
export GOOGLE_API_KEY="..."     # Gemini
export OPENAI_API_KEY="..."     # GPT-4
export ANTHROPIC_API_KEY="..."  # Claude
```

### Using Local LLMs (LM Studio, Ollama, vLLM)

Start your local model server, then:

```yaml
# agentic_config.yaml
llm:
  mode: "local"
  provider: "litellm"
  api_base: "http://127.0.0.1:1234/v1"   # LM Studio default
  models:
    master: "qwen/qwen3-32b"
    worker: "qwen/qwen3-32b"
    judge:
      - "qwen/qwen3-32b"
  temperature: 0.0
  seed: 42
```

> **Tip:** 32B+ parameter models are recommended for local use. Smaller models (7B) can run the EDA tools successfully but struggle with structured output for the judge/worker agents.

### Hierarchical Flow (Multi-Module SoC)

```yaml
design:
  flow_mode: "hierarchical"
  modules:
    picorv32:
      librelane_config_path: "./modules/picorv32/config.yaml"
    spimemio:
      librelane_config_path: "./modules/spimemio/config.yaml"
```

Each sub-module gets its own independent RTL-to-GDS flow, then they're integrated as pre-hardened macros in the parent design.

### Configuration Profiles

| Profile | Attempts/Stage | Parallel | SDC Mode | Deadlock Policy | Best For |
|---------|---------------|----------|----------|----------------|----------|
| Safe | 3 | Off | Templated | Stop | First-time users, testing |
| Balanced | 5 | Off | Restricted | Auto-relax | Most designs (recommended) |
| Aggressive | 12 | 3 branches | Expert | Auto-relax | Large designs, max optimization |

---

## Example Designs

Three ready-to-run examples are included:

| Example | Description | Config |
|---------|-------------|--------|
| `examples/counter_sky130/` | 8-bit counter — simplest possible design, great for testing | `agentic_config_e2e.yaml` (cloud) / `agentic_config_local.yaml` (local) |
| `examples/picosoc_sky130/` | PicoSoC RISC-V SoC with UART, SPI, GPIO — real-world complexity | `agentic_config_hierarchical.yaml` |
| `examples/counter_gf180/` | Counter on GlobalFoundries 180nm — different PDK | `agentic_config.yaml` |

---

## EDA Tool Requirements

AgenticLane requires LibreLane and its EDA tool dependencies:
- **Yosys** — synthesis
- **OpenROAD** — floorplanning, placement, CTS, routing
- **Magic** — DRC, GDS streaming
- **KLayout** — DRC, GDS streaming
- **Netgen** — LVS
- **Verilator** — linting

All of these are provided by the LibreLane Nix flake:
```bash
cd librelane && nix develop
```

> **Note:** You need [Nix](https://nixos.org/download/) installed with flakes enabled. If you don't have Nix, you can install the EDA tools individually or use a Docker image.

---

## Project Structure

```
agenticlane/
  cli/            — Typer CLI (init, run, report, dashboard, replay)
  config/         — Pydantic v2 config models, profiles, knob registry
  orchestration/  — Core async loop, scheduler, policies, ConstraintGuard
  agents/         — LLM provider, workers, specialists, prompt templates
  judge/          — Ensemble voting, scoring, anti-cheat
  distill/        — Metric extractors (timing, area, route, DRC, LVS, power)
  execution/      — LibreLane adapters (local, Docker), workspaces, state baton
  schemas/        — Pydantic schemas (Patch, MetricsPayload, EvidencePack)
  reporting/      — Report generation, dashboard API
  knowledge/      — RAG knowledge base (ChromaDB + sentence-transformers)

dashboard-ui/     — React 19 + TypeScript + Vite frontend
  src/components/ — Pipeline, StageNode, ScoreChart, AgentLog, MetricsCard, etc.
  src/pages/      — HomePage, NewRunPage, LiveRunPage, RunDetailPage, AgentLogsPage
  src/hooks/      — useApi, useSSE, useAgentLogs

examples/         — Ready-to-run example designs with configs
```

## Testing

```bash
# Run all unit tests
pytest tests/ -x -q --ignore=tests/integration/

# Run with coverage
pytest tests/ --cov=agenticlane --cov-report=term-missing

# Run E2E tests (requires LibreLane + PDK)
pytest tests/integration/test_e2e_real.py -m e2e

# Lint and type check
ruff check agenticlane/
mypy agenticlane/
```

**Test count:** 1200+ unit tests + 5 agentic integration tests.

## License

MIT — See [LICENSE](LICENSE) file.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Run `ruff check`, `mypy`, and `pytest` before submitting
4. Open a pull request with a clear description

## Acknowledgments

- [LibreLane](https://github.com/librelane/librelane) — RTL-to-GDS execution engine
- [OpenROAD](https://github.com/The-OpenROAD-Project/OpenROAD) — Physical design tools
- [SkyWater PDK](https://github.com/google/skywater-pdk) — Open-source 130nm process
- [LiteLLM](https://github.com/BerriAI/litellm) — LLM provider routing
- [ChromaDB](https://github.com/chroma-core/chroma) — Vector store for RAG knowledge base
