# LibreLane Integration Reference

> **Purpose:** Complete reference for how AgenticLane interfaces with LibreLane. Covers the Python API, CLI, configuration system, state management, step definitions, output artifacts, and hook mechanisms.
>
> **LibreLane version:** 2.4.13 (successor to OpenLane 2, maintained by FOSSi Foundation)
> **Repository:** https://github.com/librelane/librelane
> **Docs:** https://librelane.readthedocs.io/en/latest/
> **PyPI:** `pip install librelane`

---

## What LibreLane Is

LibreLane is the direct continuation/rebrand of **OpenLane 2** (originally by Efabless Corporation), now under the **FOSSi Foundation**. It is a Python-based ASIC infrastructure library that orchestrates open-source EDA tools to provide a complete RTL-to-GDSII flow.

Key properties:
- Orchestrates OpenROAD, Yosys, Magic, Netgen, KLayout, CVC, Verilator
- Python 3.8+ package with CLI and Python API
- Immutable state management between steps
- Step-based flow architecture with substitution/plugin support
- Docker/Podman container support built-in
- Backward-compatible with OpenLane 2 (`openlane` CLI alias)

---

## Python API

### Basic Usage

```python
from librelane.flows import Classic
from librelane.config import Config

# Load configuration
config, design_dir = Config.load(
    ["./designs/spm/config.yaml"],
    pdk_root="/path/to/pdk",
    pdk="sky130A",
    scl="sky130_fd_sc_hd",
)

# Create and run flow
flow = Classic(config=config, design_dir=design_dir)
flow.start(
    frm=None,     # start step (None = beginning)
    to=None,      # end step (None = end)
    skip=[],      # steps to skip
    tag="run1",   # run tag
)
```

### Per-Stage Execution (Critical for AgenticLane)

```python
# Run only FLOORPLAN stage steps
flow.start(
    frm="OpenROAD.Floorplan",
    to="OpenROAD.TapEndcapInsertion",
    tag="floorplan_attempt_001"
)

# Run only PLACE_GLOBAL stage steps
flow.start(
    frm="OpenROAD.GlobalPlacementSkipIO",
    to="Odb.ManualGlobalPlacement",
    tag="place_global_attempt_003"
)
```

The `frm` and `to` parameters support fuzzy matching on step IDs via `rapidfuzz`.

### Config Patching (Maps to AgenticLane Patches)

```python
# Apply knob changes via Config.with_increment()
patched_config = config.with_increment({
    "FP_CORE_UTIL": 55,
    "PL_TARGET_DENSITY_PCT": 65,
})

# Create flow with patched config
flow = Classic(config=patched_config, design_dir=design_dir)
```

### Interactive Mode (for Jupyter)

```python
config = Config.interactive(
    "./designs/spm/config.yaml",
    pdk_root="/path/to/pdk",
    pdk="sky130A",
)
# Interactive configs are mutable, relaxed validation
```

---

## CLI Reference

### Main Command

```bash
librelane [OPTIONS] CONFIG_FILES...
```

### Key Options

| Flag | Description | AgenticLane Use |
|------|-------------|-----------------|
| `--from STEP` | Start from this step | Per-stage execution |
| `--to STEP` | Stop after this step | Per-stage execution |
| `--skip STEP` | Skip specific steps | Selective execution |
| `--tag TAG` | Tag the run | Attempt identification |
| `--last-run` | Resume from last run | State continuation |
| `--overwrite` | Overwrite existing output | Re-runs |
| `--reproducible` | Enable reproducible mode | Deterministic execution |
| `--pdk-root PATH` | PDK installation root | PDK configuration |
| `--pdk NAME` | PDK name (e.g., sky130A) | PDK selection |
| `--scl NAME` | Standard cell library | SCL selection |
| `--containerized` | Run in Docker/Podman | Docker execution mode |
| `--container-mount SRC:DST` | Mount additional dirs | Docker mounts |
| `--save-views-to DIR` | Export final views | Artifact collection |

### Sub-Commands

| Command | Purpose |
|---------|---------|
| `librelane.steps` | Inspect available steps and their configs |
| `librelane.config` | Configuration utilities |
| `librelane.state` | State inspection and manipulation |
| `librelane.env_info` | Environment information |

---

## Configuration System

### Supported Formats

LibreLane supports JSON, YAML (preferred), and Tcl (deprecated) config files. Multiple files can be provided and are merged in order.

### Example Config (YAML)

```yaml
DESIGN_NAME: spm
VERILOG_FILES: "dir::src/*.v"
CLOCK_PERIOD: 10
CLOCK_PORT: clk
PNR_SDC_FILE: "dir::src/impl.sdc"
SIGNOFF_SDC_FILE: "dir::src/signoff.sdc"

FP_CORE_UTIL: 45
FP_PDN_VOFFSET: 5
FP_PDN_HOFFSET: 5
FP_PDN_VWIDTH: 2
FP_PDN_HWIDTH: 2
FP_PDN_VPITCH: 30
FP_PDN_HPITCH: 30
FP_PDN_SKIPTRIM: true

FP_PIN_ORDER_CFG: "dir::pin_order.cfg"

# PDK-conditional overrides
pdk::sky130*:
  FP_CORE_UTIL: 45
  CLOCK_PERIOD: 10.0
  scl::sky130_fd_sc_hs:
    CLOCK_PERIOD: 8

pdk::gf180mcu*:
  CLOCK_PERIOD: 24.0
  FP_CORE_UTIL: 40
```

### Config Prefixes (Special Syntax)

| Prefix | Meaning | Example |
|--------|---------|---------|
| `dir::` | Path relative to design directory | `"dir::src/*.v"` |
| `pdk::` | Conditional on PDK name | `pdk::sky130*:` |
| `scl::` | Conditional on standard cell library | `scl::sky130_fd_sc_hd:` |
| `ref::` | Reference another variable | `"ref::$CLOCK_PERIOD"` |
| `expr::` | Evaluate expression | `"expr::$CLOCK_PERIOD * 0.5"` |

### Meta Section

```yaml
meta:
  version: 2
  flow: Classic        # Flow class to use
  step: null           # For step-only runs
```

### Key Configuration Variables for AgenticLane

These are the knobs that AgenticLane agents can tune:

**Synthesis:**
| Variable | Type | Description | Typical Range |
|----------|------|-------------|---------------|
| `SYNTH_STRATEGY` | str | Synthesis optimization strategy | AREA/DELAY |
| `SYNTH_MAX_FANOUT` | int | Maximum fanout constraint | 5-20 |
| `SYNTH_BUFFERING` | bool | Enable output buffering | true/false |
| `SYNTH_SIZING` | bool | Enable cell sizing | true/false |

**Floorplan:**
| Variable | Type | Description | Typical Range |
|----------|------|-------------|---------------|
| `FP_CORE_UTIL` | int | Core area utilization (%) | 20-80 |
| `FP_ASPECT_RATIO` | float | Die aspect ratio | 0.5-2.0 |
| `FP_SIZING` | str | Floorplan sizing mode | absolute/relative |
| `DIE_AREA` | list | Die area coordinates [x0,y0,x1,y1] | design-dependent |
| `FP_PDN_VPITCH` | float | Vertical PDN pitch | design-dependent |
| `FP_PDN_HPITCH` | float | Horizontal PDN pitch | design-dependent |

**Placement:**
| Variable | Type | Description | Typical Range |
|----------|------|-------------|---------------|
| `PL_TARGET_DENSITY_PCT` | int | Placement target density (%) | 20-95 |
| `PL_ROUTABILITY_DRIVEN` | bool | Routability-driven placement | true/false |
| `PL_RESIZER_DESIGN_OPTIMIZATIONS` | bool | Post-placement optimization | true/false |

**CTS:**
| Variable | Type | Description | Typical Range |
|----------|------|-------------|---------------|
| `CTS_CLK_MAX_WIRE_LENGTH` | float | Max CTS wire length | design-dependent |
| `CTS_SINK_CLUSTERING_SIZE` | int | Sink clustering size | 10-50 |
| `CTS_DISTANCE` | float | CTS distance parameter | design-dependent |

**Routing:**
| Variable | Type | Description | Typical Range |
|----------|------|-------------|---------------|
| `GRT_ADJUSTMENT` | float | Global routing adjustment | 0.0-1.0 |
| `GRT_OVERFLOW_ITERS` | int | Overflow iteration limit | 20-100 |
| `DRT_OPT_ITERS` | int | Detailed routing iterations | 10-64 |

**Constraint (LOCKED by default):**
| Variable | Type | Description | LOCKED |
|----------|------|-------------|--------|
| `CLOCK_PERIOD` | float | Clock period (ns) | YES |
| `CLOCK_PORT` | str | Clock port name | YES |
| `PNR_SDC_FILE` | path | PnR SDC file | YES |
| `SIGNOFF_SDC_FILE` | path | Signoff SDC file | YES |

---

## State Management

### State Class

LibreLane's `State` extends `GenericImmutableDict[str, StateElement]`:
- **Immutable**: each step creates a new State, never modifies input
- **Two parts**: Design format views (file paths) + Metrics (design statistics)
- **JSON serializable**: `state_in.json` and `state_out.json` per step directory

### State Flow Between Steps

```
State_0 (initial)
  --> Step_1.run(state_in=State_0) --> State_1
    --> Step_2.run(state_in=State_1) --> State_2
      --> ...
        --> Step_N.run(state_in=State_{N-1}) --> State_N (final)
```

Each step receives `state_in` and returns `(ViewsUpdate, MetricsUpdate)` tuples. The `start()` method merges updates into a new immutable `State`.

### DesignFormat Enum (24 formats in state)

| Format | Extension | Description |
|--------|-----------|-------------|
| `NETLIST` | `.nl.v` | Verilog netlist |
| `POWERED_NETLIST` | `.pnl.v` | Power-connected netlist |
| `DEF` | `.def` | Design Exchange Format |
| `LEF` | `.lef` | Library Exchange Format |
| `ODB` | `.odb` | OpenDB database |
| `SDC` | `.sdc` | Design constraints |
| `SDF` | `.sdf` | Standard delay (multi-file) |
| `SPEF` | `.spef` | Parasitic extraction (multi-corner) |
| `LIB` | `.lib` | Timing library (multi-variant) |
| `SPICE` | `.spice` | SPICE netlist |
| `GDS` | `.gds` | GDSII stream |
| `MAG_GDS` | `.magic.gds` | Magic-generated GDS |
| `KLAYOUT_GDS` | `.klayout.gds` | KLayout-generated GDS |
| `JSON_HEADER` | `.h.json` | JSON header/metadata |
| `VERILOG_HEADER` | `.vh` | Verilog header |

### AgenticLane State Baton Mapping

AgenticLane's state baton wraps LibreLane's State:
```json
{
  "agenticlane_version": "0.1.0",
  "librelane_state_path": "{{RUN_ROOT}}/branches/B0/stages/FLOORPLAN/attempt_001/state_out.json",
  "stage": "FLOORPLAN",
  "attempt": 1,
  "branch": "B0",
  "checkpoint": true
}
```

Path rebasing uses `{{RUN_ROOT}}` tokens resolved at runtime to the actual run root (local) or Docker mount root.

---

## Step-to-Stage Mapping (Complete)

### SYNTH (Steps 1-9)
| # | Step ID | Description |
|---|---------|-------------|
| 1 | `Verilator.Lint` | RTL linting |
| 2 | `Checker.LintTimingConstructs` | Check timing constructs |
| 3 | `Checker.LintErrors` | Check lint errors |
| 4 | `Checker.LintWarnings` | Check lint warnings |
| 5 | `Yosys.JsonHeader` | Generate JSON header |
| 6 | `Yosys.Synthesis` | **Core synthesis** |
| 7 | `Checker.YosysUnmappedCells` | Check unmapped cells |
| 8 | `Checker.YosysSynthChecks` | Synthesis checks |
| 9 | `Checker.NetlistAssignStatements` | Check assign statements |

**`--from`:** `Verilator.Lint`
**`--to`:** `Checker.NetlistAssignStatements`
**Key output:** `NETLIST` (`.nl.v`)

### FLOORPLAN (Steps 10-18)
| # | Step ID | Description |
|---|---------|-------------|
| 10 | `OpenROAD.CheckSDCFiles` | Validate SDC files |
| 11 | `OpenROAD.CheckMacroInstances` | Validate macro instances |
| 12 | `OpenROAD.STAPrePNR` | Pre-PnR static timing |
| 13 | `OpenROAD.Floorplan` | **Core floorplanning** |
| 14 | `Odb.CheckMacroAntennaProperties` | Antenna property check |
| 15 | `Odb.SetPowerConnections` | Set power nets |
| 16 | `Odb.ManualMacroPlacement` | Place macros |
| 17 | `OpenROAD.CutRows` | Cut placement rows |
| 18 | `OpenROAD.TapEndcapInsertion` | Insert tap/endcap cells |

**`--from`:** `OpenROAD.CheckSDCFiles`
**`--to`:** `OpenROAD.TapEndcapInsertion`
**Key output:** `ODB` with floorplan, `DEF`

### PDN (Steps 19-22)
| # | Step ID | Description |
|---|---------|-------------|
| 19 | `Odb.AddPDNObstructions` | Add PDN obstructions |
| 20 | `OpenROAD.GeneratePDN` | **Generate PDN** |
| 21 | `Odb.RemovePDNObstructions` | Remove PDN obstructions |
| 22 | `Odb.AddRoutingObstructions` | Add routing obstructions |

**`--from`:** `Odb.AddPDNObstructions`
**`--to`:** `Odb.AddRoutingObstructions`
**Key output:** `ODB` with PDN

### PLACE_GLOBAL (Steps 23-32)
| # | Step ID | Description |
|---|---------|-------------|
| 23 | `OpenROAD.GlobalPlacementSkipIO` | Initial global placement (skip IO) |
| 24 | `OpenROAD.IOPlacement` | I/O pin placement |
| 25 | `Odb.CustomIOPlacement` | Custom I/O placement |
| 26 | `Odb.ApplyDEFTemplate` | Apply DEF template |
| 27 | `OpenROAD.GlobalPlacement` | **Core global placement** |
| 28 | `Odb.WriteVerilogHeader` | Write Verilog header |
| 29 | `Checker.PowerGridViolations` | Check power grid |
| 30 | `OpenROAD.STAMidPNR` | Mid-PnR STA |
| 31 | `OpenROAD.RepairDesignPostGPL` | Repair design post-GPL |
| 32 | `Odb.ManualGlobalPlacement` | Manual global placement |

**`--from`:** `OpenROAD.GlobalPlacementSkipIO`
**`--to`:** `Odb.ManualGlobalPlacement`
**Key output:** `ODB` with placed cells

### PLACE_DETAILED (Step 33)
| # | Step ID | Description |
|---|---------|-------------|
| 33 | `OpenROAD.DetailedPlacement` | **Legalize placement** |

**`--from`:** `OpenROAD.DetailedPlacement`
**`--to`:** `OpenROAD.DetailedPlacement`
**Key output:** `ODB` with legalized placement

### CTS (Steps 34-37)
| # | Step ID | Description |
|---|---------|-------------|
| 34 | `OpenROAD.CTS` | **Clock tree synthesis** |
| 35 | `OpenROAD.STAMidPNR` | Post-CTS timing |
| 36 | `OpenROAD.ResizerTimingPostCTS` | Post-CTS timing repair |
| 37 | `OpenROAD.STAMidPNR` | Post-repair timing |

**`--from`:** `OpenROAD.CTS`
**`--to`:** (last STAMidPNR in CTS group -- use step index or exact ID)
**Key output:** `ODB` with clock tree

### ROUTE_GLOBAL (Steps 38-45)
| # | Step ID | Description |
|---|---------|-------------|
| 38 | `OpenROAD.GlobalRouting` | **Global routing** |
| 39 | `OpenROAD.CheckAntennas` | Antenna check |
| 40 | `OpenROAD.RepairDesignPostGRT` | Post-GRT repair |
| 41 | `Odb.DiodesOnPorts` | Port diode insertion |
| 42 | `Odb.HeuristicDiodeInsertion` | Heuristic diodes |
| 43 | `OpenROAD.RepairAntennas` | Antenna repair |
| 44 | `OpenROAD.ResizerTimingPostGRT` | Post-GRT timing repair |
| 45 | `OpenROAD.STAMidPNR` | Post-GRT timing |

**`--from`:** `OpenROAD.GlobalRouting`
**`--to`:** (last STAMidPNR in GRT group)
**Key output:** Routing guides

### ROUTE_DETAILED (Steps 46-53)
| # | Step ID | Description |
|---|---------|-------------|
| 46 | `OpenROAD.DetailedRouting` | **Detailed routing** |
| 47 | `Odb.RemoveRoutingObstructions` | Remove obstructions |
| 48 | `OpenROAD.CheckAntennas` | Post-route antenna check |
| 49 | `Checker.TrDRC` | DRC check |
| 50 | `Odb.ReportDisconnectedPins` | Disconnected pins |
| 51 | `Checker.DisconnectedPins` | Disconnected pins check |
| 52 | `Odb.ReportWireLength` | Wire length report |
| 53 | `Checker.WireLength` | Wire length check |

**`--from`:** `OpenROAD.DetailedRouting`
**`--to`:** `Checker.WireLength`
**Key output:** `ODB` with routes, `DEF` with routes

### FINISH (Steps 54-58)
| # | Step ID | Description |
|---|---------|-------------|
| 54 | `OpenROAD.FillInsertion` | **Fill cell insertion** |
| 55 | `Odb.CellFrequencyTables` | Cell frequency report |
| 56 | `OpenROAD.RCX` | **Parasitic extraction** |
| 57 | `OpenROAD.STAPostPNR` | **Post-PnR STA** |
| 58 | `OpenROAD.IRDropReport` | IR drop analysis |

**`--from`:** `OpenROAD.FillInsertion`
**`--to`:** `OpenROAD.IRDropReport`
**Key output:** `SPEF`, final timing reports

### SIGNOFF (Steps 59-78)
| # | Step ID | Description |
|---|---------|-------------|
| 59 | `Magic.StreamOut` | GDS (Magic) |
| 60 | `KLayout.StreamOut` | GDS (KLayout) |
| 61 | `Magic.WriteLEF` | LEF generation |
| 62 | `Odb.CheckDesignAntennaProperties` | Antenna check |
| 63 | `KLayout.XOR` | GDS XOR check |
| 64 | `Checker.XOR` | XOR violation check |
| 65 | `Magic.DRC` | DRC (Magic) |
| 66 | `KLayout.DRC` | DRC (KLayout) |
| 67 | `Checker.MagicDRC` | Magic DRC violations |
| 68 | `Checker.KLayoutDRC` | KLayout DRC violations |
| 69 | `Magic.SpiceExtraction` | SPICE extraction |
| 70 | `Checker.IllegalOverlap` | Illegal overlap check |
| 71 | `Netgen.LVS` | Layout vs. Schematic |
| 72 | `Checker.LVS` | LVS violations |
| 73 | `Yosys.EQY` | Equivalence checking |
| 74 | `Checker.SetupViolations` | Setup timing |
| 75 | `Checker.HoldViolations` | Hold timing |
| 76 | `Checker.MaxSlewViolations` | Slew violations |
| 77 | `Checker.MaxCapViolations` | Cap violations |
| 78 | `Misc.ReportManufacturability` | Manufacturability |

**`--from`:** `Magic.StreamOut`
**`--to`:** `Misc.ReportManufacturability`
**Key output:** `GDS`, DRC/LVS reports

---

## Hook/Plugin System

### Step Substitution (Primary Hook Mechanism)

LibreLane's `SequentialFlow` supports step substitution via config `meta.substituting_steps`:

| Operation | Syntax | Effect |
|-----------|--------|--------|
| Replace | `"StepID": "MyCustomStep"` | Replace step entirely |
| Prepend | `"-StepID": "MyPreStep"` | Insert before step |
| Append | `"+StepID": "MyPostStep"` | Insert after step |

Supports `fnmatch` wildcards on step IDs.

**AgenticLane use:** Inject custom pre/post steps for SDC fragment loading, Tcl hook execution, or custom metric collection.

### Custom Step Definition

```python
from librelane.steps import Step
from librelane.state import State, DesignFormat

class AgenticLaneSDCInjector(Step):
    """Injects agent-generated SDC fragments before PnR stages."""
    id = "AgenticLane.SDCInjector"
    inputs = [DesignFormat.SDC]
    outputs = [DesignFormat.SDC]

    def run(self, state_in: State, **kwargs):
        # Read agent SDC fragments from attempt_dir/constraints/
        # Concatenate with baseline SDC
        # Write combined SDC to output path
        views_update = {DesignFormat.SDC: combined_sdc_path}
        return views_update, {}
```

### TclStep Environment Variables

TCL-based steps receive:
- `CURRENT_<FORMAT>` -- path to current view (e.g., `CURRENT_ODB`)
- `SAVE_<FORMAT>` -- path where step should write output (e.g., `SAVE_ODB`)

### SDC Injection Strategy for AgenticLane

**Recommended approach (no custom step needed):**
1. Write agent SDC fragments to `attempt_dir/constraints/agenticlane_<stage>_<attempt>.sdc`
2. Create a combined SDC file that sources baseline + user + agent fragments in order
3. Override `PNR_SDC_FILE` in the patched config to point to the combined file

**Alternative (custom step):**
1. Create `AgenticLaneSDCInjector` step
2. Prepend it before the first step that uses SDC (e.g., `OpenROAD.CheckSDCFiles`)
3. The injector reads agent fragments and updates the SDC view in state

---

## Output Artifacts

### Per-Step Directory Contents

Each step creates a directory containing:
- `state_in.json` -- input state snapshot
- `state_out.json` -- output state snapshot
- `config.json` -- step-specific configuration
- Design format files (`.odb`, `.def`, `.nl.v`, `.sdc`, etc.)
- Report files (`*.rpt`)
- Tool log files

### Report Types for Distillation

| Report | Source Step | Metrics to Extract |
|--------|-----------|-------------------|
| STA timing report | `OpenROAD.STAPrePNR/MidPNR/PostPNR` | setup_wns_ns, hold_wns, tns |
| Area report | State metrics | core_area_um2, utilization_pct |
| Congestion report | `OpenROAD.GlobalRouting` | congestion_overflow_pct |
| Wire length report | `Odb.ReportWireLength` | total_wire_length |
| DRC report | `Magic.DRC`, `KLayout.DRC` | drc_count, drc_violations |
| LVS report | `Netgen.LVS` | lvs_pass |
| IR drop report | `OpenROAD.IRDropReport` | max_ir_drop |
| Cell frequency | `Odb.CellFrequencyTables` | cell_count_by_type |
| Manufacturability | `Misc.ReportManufacturability` | antenna_violations |

### Metrics Available in State

LibreLane's `State.metrics` includes design statistics computed by steps. These are accessible in the `state_out.json` metrics section. Key metrics:
- Cell count
- Wire length
- Area
- Timing violations (from checker steps)
- DRC violations
- LVS result

---

## Docker/Container Support

### Built-in Container Mode

```bash
# Run with Docker/Podman
librelane --containerized --pdk-root $HOME/.ciel ./config.yaml

# Additional mounts
librelane --containerized --container-mount /data:/data ./config.yaml
```

### Container Details
- Registry: `ghcr.io` (GitHub Container Registry) + Docker Hub
- Supports Docker (>= 25.0.5) and Podman (>= 4.1.0)
- Auto-mounts: home directory, PDK root, CWD
- X11 forwarding on Linux for GUI tools

### AgenticLane Docker Strategy

For `execution.mode: docker`:
1. Use LibreLane's `--containerized` flag
2. Mount run_root as read-only at `docker.mount_root`
3. Mount attempt_dir as read-write at `docker.attempt_root`
4. Use path rebasing mode `rebase_to_mount_root` for Docker paths

---

## Dependencies

### Python Dependencies (for AgenticLane to know about)

| Package | Version | Purpose |
|---------|---------|---------|
| `click` | >= 8 | CLI framework (LibreLane uses this) |
| `pyyaml` | >= 5, < 7 | YAML parsing |
| `rich` | >= 12, < 15 | Terminal formatting |
| `ciel` | >= 2.0.3 | PDK management |
| `psutil` | >= 5.9.0 | Process management |
| `klayout` | >= 0.29.0 | KLayout bindings |

### External EDA Tools

| Tool | Purpose | Required for Stages |
|------|---------|-------------------|
| **OpenROAD** | Physical design | FLOORPLAN through FINISH |
| **Yosys** | Synthesis | SYNTH |
| **Magic** | Layout, DRC, SPICE | SIGNOFF |
| **KLayout** | Layout, DRC, GDS | SIGNOFF |
| **Netgen** | LVS | SIGNOFF |
| **CVC** | Circuit verification | SIGNOFF |
| **Verilator** | RTL linting | SYNTH |

---

## Integration Checklist

When building the `LibreLaneLocalAdapter`:

- [x] Can load LibreLane config via `Flow.factory.get("Classic")` constructor
- [x] Can apply config patches via `config_override_strings` (KEY=VALUE format)
- [x] Can create `Classic` flow instance via factory
- [x] Can run partial flow with `frm`/`to` step IDs via `flow.start()`
- [x] Can capture `state_out.json` from step directories
- [x] Can handle tool crashes (catch exceptions, capture stderr)
- [x] Can handle timeouts (use `asyncio.wait_for`)
- [x] Can parse STA timing reports for metrics extraction (real OpenSTA format)
- [x] Can parse DRC/LVS reports for signoff checking (Magic/Netgen/KLayout)
- [ ] SDC injection works via config override or custom step
- [ ] State baton handoff preserves all DesignFormat paths
- [ ] Path rebasing correctly tokenizes/detokenizes paths
