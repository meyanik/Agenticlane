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

## Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/user/agenticlane.git
cd agenticlane

# Install in development mode
pip install -e ".[dev]"

# Verify installation
agenticlane --help
```

### Initialize a project

```bash
agenticlane init --design my_chip --pdk sky130A
```

### Run with cloud LLM (Gemini)

```bash
export GOOGLE_API_KEY="your-key-here"
agenticlane run agentic_config.yaml
```

### Run with local LLM (LM Studio)

```yaml
# agentic_config.yaml
llm:
  mode: "local"
  provider: "litellm"
  api_base: "http://127.0.0.1:1234/v1"
  models:
    master: "qwen/qwen3-32b"
    worker: "qwen/qwen3-32b"
    judge:
      - "qwen/qwen3-32b"
  temperature: 0.0
  seed: 42
```

```bash
agenticlane run agentic_config.yaml
```

### Hierarchical flow (multi-module SoC)

```yaml
design:
  flow_mode: "hierarchical"
  modules:
    picorv32:
      librelane_config_path: "./modules/picorv32/config.yaml"
    spimemio:
      librelane_config_path: "./modules/spimemio/config.yaml"
```

## E2E Results

| Design | PDK | Cells | GDS Size | DRC | Runtime | LLM |
|--------|-----|-------|----------|-----|---------|-----|
| Counter (8-bit) | sky130A | ~200 | 241 KB | Clean | ~15 min | Gemini 2.5 Pro |
| PicoSoC (RISC-V) | sky130A | 43K | 133 MB | Clean | ~3.4 hrs | Gemini 2.5 Pro |
| PicoSoC Hierarchical | sky130A | 43K | 127 MB | Clean | ~3 hrs | Qwen3-32B (local) |

## EDA Tool Requirements

AgenticLane requires LibreLane and its EDA tool dependencies:
- **Yosys** — synthesis
- **OpenROAD** — floorplanning, placement, CTS, routing
- **Magic** — DRC, GDS streaming
- **KLayout** — DRC, GDS streaming
- **Netgen** — LVS
- **Verilator** — linting

These are available via the LibreLane Nix flake:
```bash
cd librelane && nix develop
```

## Project Structure

```
agenticlane/
  cli/          — Typer CLI (init, run, report, dashboard, replay)
  config/       — Pydantic v2 config models, profiles, knob registry
  orchestration/ — Core async loop, scheduler, policies, ConstraintGuard
  agents/       — LLM provider, workers, specialists, prompt templates
  judge/        — Ensemble voting, scoring, anti-cheat
  distill/      — Metric extractors (timing, area, route, DRC, LVS, power)
  execution/    — LibreLane adapters (local, Docker), workspaces, state baton
  schemas/      — Pydantic schemas (Patch, MetricsPayload, EvidencePack)
  reporting/    — Report generation, dashboard
```

## Configuration Profiles

| Profile | SDC Mode | Tcl | Parallel Branches | Use Case |
|---------|----------|-----|-------------------|----------|
| safe | templated | disabled | 3 | Default, conservative |
| balanced | restricted_freeform | restricted | 3 | Moderate exploration |
| aggressive | expert_freeform | expert | 4 | Maximum exploration |

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

**Test count:** 984+ unit tests across 53 test files.

## Documentation

- **Build Spec**: `docs/spec/AgenticLane_Build_Spec_v0.6_FINAL.md`
- **Architecture**: `docs/architecture/ARCHITECTURE.md`
- **LibreLane Integration**: `docs/integration/LIBRELANE_INTEGRATION.md`
- **Master Plan**: `docs/planning/master_plan.md`

## License

See LICENSE file.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Run `ruff check`, `mypy`, and `pytest` before submitting
4. Open a pull request with a clear description

## Acknowledgments

- [LibreLane](https://github.com/librelane/librelane) — RTL-to-GDS execution engine
- [OpenROAD](https://github.com/The-OpenROAD-Project/OpenROAD) — Physical design tools
- [LiteLLM](https://github.com/BerriAI/litellm) — LLM provider routing
