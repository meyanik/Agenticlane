/** Stage names, colors, and descriptions for the 10-stage RTL-to-GDS pipeline. */

export const STAGE_ORDER = [
  'SYNTH',
  'FLOORPLAN',
  'PDN',
  'PLACE_GLOBAL',
  'PLACE_DETAILED',
  'CTS',
  'ROUTE_GLOBAL',
  'ROUTE_DETAILED',
  'FINISH',
  'SIGNOFF',
] as const;

export type StageName = (typeof STAGE_ORDER)[number];

export const STAGE_LABELS: Record<string, string> = {
  SYNTH: 'Synthesis',
  FLOORPLAN: 'Floorplan',
  PDN: 'PDN',
  PLACE_GLOBAL: 'Global Place',
  PLACE_DETAILED: 'Detail Place',
  CTS: 'CTS',
  ROUTE_GLOBAL: 'Global Route',
  ROUTE_DETAILED: 'Detail Route',
  FINISH: 'Finish',
  SIGNOFF: 'Signoff',
};

/** Educational descriptions for VLSI beginners. */
export const STAGE_DESCRIPTIONS: Record<string, string> = {
  SYNTH: 'Converts your Verilog HDL code into a gate-level netlist using logic cells from the PDK library.',
  FLOORPLAN: 'Defines the chip\'s physical boundaries (die area), I/O pin placement, and initial macro positions.',
  PDN: 'Creates the power delivery network (VDD/VSS) with metal straps and power rings to supply all cells.',
  PLACE_GLOBAL: 'Roughly positions all standard cells across the die to minimize total wirelength.',
  PLACE_DETAILED: 'Refines cell positions to fix overlaps, align to rows, and optimize local routing congestion.',
  CTS: 'Builds a balanced clock tree to distribute the clock signal to all flip-flops with minimal skew.',
  ROUTE_GLOBAL: 'Plans approximate routing paths for all signal nets across the chip\'s routing grid.',
  ROUTE_DETAILED: 'Assigns exact metal tracks and vias for every net, resolving DRC violations.',
  FINISH: 'Adds filler cells, generates the final DEF, and prepares layout data for signoff checks.',
  SIGNOFF: 'Runs DRC, LVS, antenna checks and generates the final GDSII layout file for fabrication.',
};

/** Status colors (CSS variable names). */
export const STATUS_COLORS: Record<string, string> = {
  pending: 'var(--text-dim)',
  running: 'var(--accent)',
  passed: 'var(--green)',
  executed: 'var(--green)',
  failed: 'var(--red)',
  rollback: 'var(--purple)',
  retrying: 'var(--yellow)',
};

/** Status icons (Unicode). */
export const STATUS_ICONS: Record<string, string> = {
  pending: '\u2014',  // em dash
  running: '\u25CF',  // filled circle
  passed: '\u2713',   // check mark
  executed: '\u2713',  // check mark (EDA tool succeeded)
  failed: '\u2717',   // cross mark
  rollback: '\u21BA',  // anticlockwise arrow
  retrying: '\u21BB',  // clockwise arrow
};

/** Agent role colors for the activity log. */
export const AGENT_COLORS: Record<string, string> = {
  worker: '#58a6ff',
  judge: '#d29922',
  master: '#bc8cff',
  rag: '#3fb9a0',
  execution: '#8b949e',
  guard: '#3fb950',
  error: '#f85149',
  rollback: '#bc8cff',
};

/** Short labels for agent roles (used in log badges). */
export const AGENT_ROLE_LABELS: Record<string, string> = {
  worker: 'Worker',
  judge: 'Judge',
  master: 'Master',
  rag: 'RAG',
  execution: 'Exec',
};

/** Unicode icons for agent roles. */
export const AGENT_ROLE_ICONS: Record<string, string> = {
  worker: '\u2699',    // gear
  judge: '\u2696',     // scales
  master: '\u2605',    // star
  rag: '\u{1F4DA}',   // books
  execution: '\u25B6', // play
};

/** VLSI glossary for the educational panel. */
export const GLOSSARY: Record<string, string> = {
  'WNS': 'Worst Negative Slack - how much the design misses timing. Negative values mean violations.',
  'TNS': 'Total Negative Slack - sum of all negative slack across all paths.',
  'DRC': 'Design Rule Check - verifies the layout meets fabrication rules (spacing, width, etc.).',
  'LVS': 'Layout vs Schematic - verifies the physical layout matches the logical design.',
  'PDK': 'Process Design Kit - technology-specific files (cell libraries, design rules) from the foundry.',
  'DEF': 'Design Exchange Format - standard file format describing physical chip layout.',
  'GDSII': 'Graphic Database System II - the final binary layout file sent to the foundry.',
  'Netlist': 'A description of the circuit as a list of components and their connections.',
  'Utilization': 'Percentage of the die area occupied by standard cells.',
  'Congestion': 'How crowded the routing channels are - high congestion causes DRC violations.',
  'Slack': 'Time margin between when a signal arrives and when it\'s needed. Positive is good.',
  'Antenna': 'Charge buildup during fabrication that can damage transistor gates.',
  'LEF': 'Library Exchange Format - describes cell physical dimensions and pin locations.',
  'CTS': 'Clock Tree Synthesis - building a balanced tree to distribute the clock signal.',
  'Macro': 'A pre-designed block (memory, IP core) placed as a unit in the floorplan.',
};

/** Deep help text for every config field — shown in (i) info popovers. */
export const CONFIG_HELP: Record<string, { title: string; content: string }> = {
  // Presets
  'presets': {
    title: 'Preset Profiles',
    content: 'Presets pre-fill all settings with tested defaults. "Safe" is conservative with fewer attempts and strict constraints — great for first-time users. "Balanced" is the recommended middle ground with RAG enabled and automatic deadlock relaxation. "Aggressive" maximizes parallelism and attempts for designs that need heavy optimization. You can always customize individual settings after selecting a preset.',
  },
  // Project
  'project.name': {
    title: 'Project Name',
    content: 'A human-readable label for this run. It appears in the dashboard run list, log files, and output directories. Use something descriptive like "counter_timing_fix" or "picosoc_v2". The name does not affect the design — it is purely organizational.',
  },
  'project.run_id': {
    title: 'Run ID',
    content: 'A unique identifier for this run. When set to "auto", AgenticLane generates a random 8-character hex ID (e.g., "run_5c99af29"). You can also specify a custom ID. Each run gets its own output directory named by this ID, so it must be unique within a project.',
  },
  // Design
  'design.librelane_config_path': {
    title: 'LibreLane Config Path',
    content: 'Path to the LibreLane (OpenLane 2) configuration YAML file that describes your design. This file contains settings like Verilog source files, clock period, die area, and target density. AgenticLane wraps LibreLane and uses this config as the starting point for each stage execution.',
  },
  'design.pdk': {
    title: 'Process Design Kit (PDK)',
    content: 'The semiconductor foundry process to target. sky130A is the open-source SkyWater 130nm process — the most common choice for open-source designs. The PDK determines which cell libraries, design rules, and metal layers are available. Other options include gf180mcuD (GlobalFoundries 180nm).',
  },
  'design.flow_mode': {
    title: 'Flow Mode',
    content: 'Determines how multi-module designs are handled. "Flat" synthesizes the entire design as one unit — simpler but slower for large designs. "Hierarchical" hardens sub-modules independently (each gets its own RTL-to-GDS flow), then integrates them as pre-built macros in the parent — faster and better for complex SoCs. "Auto" lets AgenticLane decide based on the design.',
  },
  'design.example': {
    title: 'Example Design',
    content: 'Pre-configured example designs included with AgenticLane. Each example comes with Verilog source files, a LibreLane config, and PDK settings. Great for learning the system or testing configurations before running on your own design.',
  },
  'design.verilog_files': {
    title: 'Verilog Source Files',
    content: 'Comma-separated paths to your Verilog/SystemVerilog source files (e.g., "src/top.v, src/alu.v"). These define the digital logic that will go through the RTL-to-GDS flow. If your LibreLane config already specifies VERILOG_FILES, you can leave this blank. Files listed here override the LibreLane config setting.',
  },
  'design.clock_period': {
    title: 'Clock Period (ns)',
    content: 'Target clock period in nanoseconds. This defines the speed your chip must run at — a 10ns period means a 100MHz clock. Tighter (smaller) clock periods are harder to meet and require more optimization effort. The agents will work to achieve timing closure at this frequency. If your LibreLane config already sets CLOCK_PERIOD, this overrides it.',
  },
  'design.clock_strategy': {
    title: 'Clock Strategy',
    content: '"Lock Period" keeps CLOCK_PERIOD fixed — agents optimize the design to meet your target frequency but cannot change it. This is the safe default. "Let Agents Optimize" removes CLOCK_PERIOD from the locked variables list, allowing agents to push for a faster clock if the design allows it. For example, if you set 10ns (100MHz) as the starting point, aggressive agents might achieve 5ns (200MHz) if the logic is fast enough. This is powerful for exploring a design\'s true performance limits, but the agents may also relax the clock if they can\'t meet timing, so use with caution.',
  },
  // Intent
  'intent.prompt': {
    title: 'Optimization Prompt',
    content: 'This is the most important setting. The AI agents read this prompt verbatim at every stage of the flow. Write clear instructions about what you want optimized — e.g., "Minimize timing violations, target WNS > -0.1ns" or "Prioritize area reduction, allow timing slack up to -0.5ns". Be specific about your priorities. The agents use this to decide which config knobs to tune and how aggressively to optimize.',
  },
  'intent.weights_hint.timing': {
    title: 'Timing vs Area Weight',
    content: 'Controls the relative importance of timing closure versus area optimization. At 100% timing, agents focus on meeting clock constraints (reducing WNS/TNS) even if it means using more chip area. At 100% area, agents minimize die utilization even if timing degrades. The recommended starting point is 70% timing / 30% area, since timing violations are typically harder to fix.',
  },
  // Initialization
  'initialization.zero_shot.enabled': {
    title: 'Zero-Shot Initialization',
    content: 'When enabled, the LLM generates an initial set of config knob values before the first attempt, using its knowledge of the design and PDK. This gives the optimization a better starting point than default LibreLane values. Disable this if you want to start from LibreLane defaults or have already tuned your initial config.',
  },
  // Flow Control
  'flow_control.budgets.physical_attempts_per_stage': {
    title: 'Attempts per Stage',
    content: 'Maximum number of LibreLane execution attempts allowed per pipeline stage. Each attempt runs the actual EDA tools (synthesis, placement, routing, etc.) with agent-proposed config changes. More attempts give the agents more chances to fix issues but increase total runtime. 3 is safe for testing, 5-6 is good for production, 12 is aggressive. Each attempt takes 1-15 minutes depending on design size and stage.',
  },
  'flow_control.budgets.cognitive_retries_per_attempt': {
    title: 'Cognitive Retries per Attempt',
    content: 'Number of times the LLM can re-think its approach for a single attempt before actually running the EDA tools. If the judge rejects a proposed patch, the worker gets this many retries to revise it. This is "thinking time" — no tools are executed. Higher values use more LLM tokens but can produce better patches. 2-3 is typical.',
  },
  'flow_control.deadlock_policy': {
    title: 'Deadlock Policy',
    content: 'What happens when the agents cannot make progress (e.g., stuck in a loop of failed attempts). "auto_relax" automatically loosens hard constraints (like DRC count thresholds) to let the pipeline continue — recommended for most runs. "ask_human" pauses and asks you to intervene via the dashboard. "stop" halts the entire run immediately. Auto-relax is safest for unattended runs.',
  },
  'flow_control.plateau_detection.enabled': {
    title: 'Plateau Detection',
    content: 'Detects when scores stop improving across attempts and automatically advances to the next stage. Without this, agents might waste all their attempts making tiny improvements. When the composite score changes less than the min_delta over the detection window, the stage is considered "plateaued" and the best attempt is accepted.',
  },
  'flow_control.plateau_detection.window': {
    title: 'Plateau Window',
    content: 'Number of consecutive attempts to look back when checking for score plateaus. A window of 3 means "if the last 3 attempts all improved less than min_delta, stop trying." Smaller windows detect plateaus faster but might stop too early. Larger windows are more patient.',
  },
  'flow_control.plateau_detection.min_delta_score': {
    title: 'Plateau Min Delta',
    content: 'Minimum score improvement required between attempts to avoid triggering plateau detection. Scores range from 0.0 to 1.0, so 0.01 means "less than 1% improvement triggers plateau." Lower values make the system more patient; higher values trigger earlier stage advancement.',
  },
  'flow_control.ask_human.enabled': {
    title: 'Human-in-the-Loop',
    content: 'When enabled, the system can pause and ask for human approval at critical decision points — like before relaxing constraints or when a stage fails all attempts. You will see prompts in the dashboard. This is useful for production tapeouts where you want final say, but slows down unattended runs.',
  },
  // Parallel
  'parallel.enabled': {
    title: 'Parallel Branches',
    content: 'Enables exploring multiple optimization strategies simultaneously. Instead of trying one approach at a time, the system forks into parallel branches — each branch tries a different set of config knobs. The best branch wins. This significantly improves result quality but uses more compute resources (CPU, memory, LLM tokens). Requires a multi-core machine.',
  },
  'parallel.max_parallel_branches': {
    title: 'Max Parallel Branches',
    content: 'Maximum number of concurrent optimization branches. Each branch independently runs EDA tools with different config strategies. More branches explore a wider solution space but use proportionally more compute. 2-3 branches work well for most designs. Very large designs may need to limit to 2 due to memory.',
  },
  'parallel.max_parallel_jobs': {
    title: 'Max Parallel Jobs',
    content: 'Maximum number of EDA tool executions that can run simultaneously across all branches. Must be less than or equal to max_parallel_branches. Limiting this prevents overloading the machine — each LibreLane execution uses significant CPU and RAM. Set to 1 for sequential execution even with multiple branches.',
  },
  'parallel.branch_policy': {
    title: 'Branch Policy',
    content: '"best_of_n" picks the single branch with the highest composite score — simple and effective. "pareto" considers multi-objective trade-offs (timing vs area vs power) and may keep branches that are best along different axes. Use "best_of_n" unless you need Pareto-optimal exploration.',
  },
  'parallel.prune.enabled': {
    title: 'Branch Pruning',
    content: 'Automatically kills underperforming branches early to save compute. If a branch falls behind the leader by more than prune_delta_score for prune_patience_attempts consecutive attempts, it is terminated. This prevents wasting resources on hopeless strategies.',
  },
  // Knowledge / RAG
  'knowledge.enabled': {
    title: 'RAG Knowledge Base',
    content: 'Enables Retrieval-Augmented Generation using a curated database of chip design knowledge (PDK docs, OpenROAD documentation, design guidelines). When enabled, the system retrieves relevant knowledge chunks and injects them into the agent prompts. This helps agents make better decisions, especially for complex stages like CTS and routing. Requires the ChromaDB knowledge base to be built.',
  },
  'knowledge.top_k': {
    title: 'RAG Top-K Results',
    content: 'Number of knowledge chunks retrieved from the database for each query. Higher values provide more context but increase prompt length and LLM token usage. 5 is a good balance. For very specific stages, 3 may suffice. For complex stages like routing, 8-10 can help.',
  },
  'knowledge.score_threshold': {
    title: 'RAG Score Threshold',
    content: 'Minimum similarity score (0.0 to 1.0) for a knowledge chunk to be included. Chunks below this threshold are discarded even if they are in the top-K. Higher thresholds mean only highly relevant results are used. 0.35 is the default — increase to 0.5 if you see irrelevant context, decrease to 0.2 for broader coverage.',
  },
  // Action Space
  'action_space.permissions.config_vars': {
    title: 'Config Variables Permission',
    content: 'When enabled, agents can modify LibreLane configuration variables like core utilization, target density, clock period, synthesis strategy, etc. This is the primary mechanism for optimization. Disable only if you want agents to provide analysis without making changes.',
  },
  'action_space.permissions.sdc': {
    title: 'SDC Constraints Permission',
    content: 'When enabled, agents can write or modify Synopsys Design Constraints (.sdc) files that define timing constraints, clock definitions, and input/output delays. SDC changes are powerful but risky — incorrect constraints can mask real timing violations.',
  },
  'action_space.permissions.tcl': {
    title: 'Tcl Hooks Permission',
    content: 'When enabled, agents can write Tcl scripts that hook into specific points of the LibreLane flow (pre-synthesis, post-placement, etc.). Tcl hooks provide fine-grained control but are advanced — use with caution.',
  },
  'action_space.permissions.macro_placements': {
    title: 'Macro Placement Permission',
    content: 'When enabled, agents can modify the physical placement of macro blocks (memories, IP cores) on the chip floorplan. Macro placement heavily impacts routing congestion and timing. Only relevant for designs that contain macros.',
  },
  'action_space.sdc.mode': {
    title: 'SDC Mode',
    content: '"templated" generates SDC from safe templates with fill-in-the-blank values — safest option. "restricted_freeform" allows the agent to write SDC commands but blocks dangerous ones (like removing constraints). "expert_freeform" gives full SDC authoring freedom — only for experienced users who trust the LLM.',
  },
  'action_space.tcl.mode': {
    title: 'Tcl Mode',
    content: 'Controls how much freedom agents have when writing Tcl hooks. "templated" uses pre-defined templates. "restricted" allows custom Tcl but blocks dangerous commands. This prevents agents from accidentally modifying the flow in harmful ways.',
  },
  // Constraints
  'constraints.locked_vars': {
    title: 'Locked Variables',
    content: 'A list of config variable names that agents are NOT allowed to change. Use this to protect critical settings like clock period (CLOCK_PERIOD), die area, or any design-specific values you do not want the AI to modify. Example: ["CLOCK_PERIOD", "DIE_AREA"]. The agent will see these values but cannot propose changes to them.',
  },
  'constraints.allow_relaxation': {
    title: 'Allow Constraint Relaxation',
    content: 'When enabled, the auto_relax deadlock policy can loosen hard constraints (like maximum DRC violations) to let the pipeline continue. When disabled, constraints are strictly enforced even if it means the run gets stuck. Enable for exploration; disable for production tapeouts where quality gates must hold.',
  },
  'constraints.max_relaxation_pct': {
    title: 'Max Relaxation Percent',
    content: 'Maximum percentage by which hard constraints can be relaxed during auto_relax. For example, 50% means a DRC hard gate of 0 violations could be relaxed to allow up to 50% more than the baseline. This prevents runaway relaxation from producing unusable results.',
  },
  // LLM
  'llm.mode': {
    title: 'LLM Mode',
    content: '"api" uses cloud-hosted models via API keys (Gemini, OpenAI, Anthropic, etc.) — best quality and fastest. "local" connects to a locally-running model server (LM Studio, Ollama, vLLM) at the specified API base URL. Local mode is free but quality depends on your hardware and model size. 32B+ parameter models are recommended for local use.',
  },
  'llm.api_base': {
    title: 'API Base URL',
    content: 'The base URL of your local LLM server, typically "http://127.0.0.1:1234/v1" for LM Studio or "http://127.0.0.1:11434/v1" for Ollama. Only used when LLM Mode is "local". The server must be running and serving an OpenAI-compatible chat completions endpoint.',
  },
  'llm.models.worker': {
    title: 'Worker Model',
    content: 'The LLM used by Worker agents that analyze design metrics, propose config changes, and write patches. Workers do the heavy lifting of optimization. Use your best/largest model here. For API: "gemini/gemini-2.5-pro" or "claude-sonnet-4-20250514" work well. For local: use your largest model (32B+).',
  },
  'llm.models.judge': {
    title: 'Judge Model',
    content: 'The LLM used by Judge agents that evaluate worker proposals. Judges vote PASS or FAIL with confidence scores and blocking issues. Can be the same model as the worker or a different one. Using a different model provides diversity of opinion. Multiple judges can be specified for ensemble voting.',
  },
  'llm.models.stage_overrides': {
    title: 'Per-Stage Model Overrides',
    content: 'Override the default worker and/or judge model for specific pipeline stages. For example, you might use a larger, more expensive model for the critical CTS and routing stages while using a smaller model for synthesis. Leave blank to use the default models for all stages.',
  },
  'llm.temperature': {
    title: 'Temperature',
    content: 'Controls LLM response randomness. 0.0 produces deterministic, consistent responses — best for reproducibility. Higher values (0.3-0.7) add creativity and exploration, which can help discover novel optimization strategies. For production runs, 0.0 is recommended. For exploration, try 0.3.',
  },
  'llm.seed': {
    title: 'Random Seed',
    content: 'Seed value for reproducible LLM outputs. When temperature is 0.0 and the same seed is used, the LLM should produce identical responses. Set to 42 by default. Change to a different number to get a different deterministic trajectory.',
  },
  // Judging
  'judging.ensemble.vote': {
    title: 'Vote Strategy',
    content: '"majority" passes if more than half of judges vote PASS — more lenient, lets borderline improvements through. "unanimous" requires ALL judges to vote PASS — stricter, ensures high confidence in each advancement. Use "majority" for exploration and "unanimous" for production quality.',
  },
  'judging.ensemble.tie_breaker': {
    title: 'Tie Breaker',
    content: 'What happens when judges are evenly split (e.g., 1 PASS, 1 FAIL). "fail" rejects the proposal and retries — safer, avoids accepting marginal improvements. "pass" accepts the proposal — more optimistic, moves faster through stages.',
  },
  'judging.strictness.hard_gates': {
    title: 'Hard Gates',
    content: 'Absolute thresholds that must be met for a judge to vote PASS. For example, {"drc_count": 0} means zero DRC violations are required. Hard gates are checked before qualitative judgment. If any hard gate fails, the vote is automatically FAIL regardless of other improvements. Set appropriate gates for your design quality requirements.',
  },
  // Scoring
  'scoring.normalization.method': {
    title: 'Score Normalization',
    content: '"percent_over_baseline" scores improvements as percentage better than the first attempt — intuitive but sensitive to baseline quality. "absolute_scaled" uses fixed reference values — more stable across runs. The composite score (0.0-1.0) combines timing, area, and DRC metrics using your intent weights.',
  },
  // Execution
  'execution.mode': {
    title: 'Execution Mode',
    content: '"local" runs EDA tools directly on your machine — requires Nix shell with OpenROAD, Yosys, etc. installed. "docker" runs tools inside a container with all dependencies pre-installed — easier setup but slightly slower due to container overhead. Use "local" with Nix for best performance.',
  },
  'execution.tool_timeout_seconds': {
    title: 'Tool Timeout',
    content: 'Maximum time (in seconds) to wait for a single EDA tool execution to complete. Synthesis typically takes 1-5 minutes, but detailed routing on large designs can take 30+ minutes. Default is 21600 (6 hours). Set lower for faster failure detection on small designs.',
  },
  // Artifact GC
  'artifact_gc.enabled': {
    title: 'Artifact Garbage Collection',
    content: 'Automatically cleans up intermediate files from failed attempts to save disk space. Each LibreLane run generates hundreds of MB of temporary files. With GC enabled, only the best attempt artifacts are kept. Disable if you need to debug failed attempts.',
  },
  'artifact_gc.policy': {
    title: 'GC Policy',
    content: '"keep_pass_and_tips" keeps artifacts from passed attempts and the best failed attempt (the "tip") — good balance. "keep_all" keeps everything — uses the most disk but allows full debugging. "keep_none" deletes all intermediate artifacts — most aggressive disk savings.',
  },
  'artifact_gc.max_run_disk_gb': {
    title: 'Max Disk Usage (GB)',
    content: 'Maximum total disk space a single run can use. When exceeded, the GC policy kicks in to free space. Default is 40 GB. Reduce for machines with limited storage. A typical 10-stage run with 5 attempts per stage uses 5-20 GB depending on design size.',
  },
  'artifact_gc.compress_pass_artifacts': {
    title: 'Compress Artifacts',
    content: 'When enabled, artifacts from passed attempts are compressed to save disk space. Uses zstd compression by default (fast and efficient). Compressed artifacts can still be inspected but take slightly longer to access.',
  },
};

/** Preset configuration profiles. */
export interface PresetProfile {
  name: string;
  description: string;
  tag: string;
  tagColor: string;
  values: Record<string, unknown>;
}

export const PRESET_PROFILES: PresetProfile[] = [
  {
    name: 'Safe',
    description: 'Conservative settings for first-time users. Fewer attempts, no parallelism, strict constraints.',
    tag: 'Beginner',
    tagColor: 'var(--green)',
    values: {
      attemptsPerStage: 3,
      cognitiveRetries: 2,
      deadlockPolicy: 'stop',
      plateauEnabled: true,
      plateauWindow: 3,
      plateauMinDelta: 0.01,
      humanInTheLoop: false,
      parallelEnabled: false,
      maxBranches: 1,
      maxJobs: 1,
      branchPolicy: 'best_of_n',
      pruneEnabled: false,
      ragEnabled: true,
      ragTopK: 5,
      ragThreshold: 0.35,
      permConfigVars: true,
      permSdc: false,
      permTcl: false,
      permMacro: false,
      sdcMode: 'templated',
      tclMode: 'restricted_freeform',
      allowRelaxation: false,
      maxRelaxationPct: 0,
      voteStrategy: 'unanimous',
      tieBreaker: 'fail',
      gcEnabled: true,
      gcPolicy: 'keep_pass_and_tips',
      maxDiskGb: 40,
      compressArtifacts: true,
      temperature: 0.0,
      executionMode: 'local',
      toolTimeout: 21600,
      zeroShotEnabled: true,
    },
  },
  {
    name: 'Balanced',
    description: 'Recommended defaults. Moderate attempts, RAG knowledge, auto-relaxation for smooth runs.',
    tag: 'Recommended',
    tagColor: 'var(--accent)',
    values: {
      attemptsPerStage: 5,
      cognitiveRetries: 3,
      deadlockPolicy: 'auto_relax',
      plateauEnabled: true,
      plateauWindow: 3,
      plateauMinDelta: 0.01,
      humanInTheLoop: false,
      parallelEnabled: false,
      maxBranches: 2,
      maxJobs: 2,
      branchPolicy: 'best_of_n',
      pruneEnabled: true,
      ragEnabled: true,
      ragTopK: 5,
      ragThreshold: 0.35,
      permConfigVars: true,
      permSdc: true,
      permTcl: false,
      permMacro: true,
      sdcMode: 'restricted_freeform',
      tclMode: 'restricted_freeform',
      allowRelaxation: true,
      maxRelaxationPct: 50,
      voteStrategy: 'majority',
      tieBreaker: 'fail',
      gcEnabled: true,
      gcPolicy: 'keep_pass_and_tips',
      maxDiskGb: 40,
      compressArtifacts: true,
      temperature: 0.0,
      executionMode: 'local',
      toolTimeout: 21600,
      zeroShotEnabled: true,
    },
  },
  {
    name: 'Aggressive',
    description: 'Maximum optimization. More attempts, parallel branches, freeform SDC, relaxation allowed.',
    tag: 'Power User',
    tagColor: 'var(--yellow)',
    values: {
      attemptsPerStage: 12,
      cognitiveRetries: 3,
      deadlockPolicy: 'auto_relax',
      plateauEnabled: true,
      plateauWindow: 4,
      plateauMinDelta: 0.005,
      humanInTheLoop: false,
      parallelEnabled: true,
      maxBranches: 3,
      maxJobs: 2,
      branchPolicy: 'best_of_n',
      pruneEnabled: true,
      ragEnabled: true,
      ragTopK: 8,
      ragThreshold: 0.3,
      permConfigVars: true,
      permSdc: true,
      permTcl: true,
      permMacro: true,
      sdcMode: 'expert_freeform',
      tclMode: 'restricted_freeform',
      allowRelaxation: true,
      maxRelaxationPct: 75,
      voteStrategy: 'majority',
      tieBreaker: 'pass',
      gcEnabled: true,
      gcPolicy: 'keep_pass_and_tips',
      maxDiskGb: 80,
      compressArtifacts: true,
      temperature: 0.3,
      executionMode: 'local',
      toolTimeout: 21600,
      zeroShotEnabled: true,
    },
  },
];
