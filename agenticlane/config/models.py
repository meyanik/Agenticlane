"""AgenticLane configuration models.

Full Pydantic v2 config skeleton implementing every section from the
AgenticLane Build Spec v0.6 FINAL (lines 328-527).  All fields carry
safe defaults so that ``AgenticLaneConfig()`` validates out of the box
with the most conservative ("safe") settings.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------


class ProjectConfig(BaseModel):
    """Top-level project identity."""

    name: str = "my_block"
    run_id: str = "auto"
    output_dir: Path = Path("./runs")


# ---------------------------------------------------------------------------
# Design
# ---------------------------------------------------------------------------


class ModuleConfig(BaseModel):
    """Configuration for a sub-module to be hardened independently.

    Used in hierarchical flow mode: each module runs the full
    SYNTH-to-SIGNOFF pipeline, producing LEF/GDS that get integrated
    as macros in the parent design.
    """

    librelane_config_path: Path
    verilog_files: list[str] = Field(default_factory=list)
    pdk: Optional[str] = None
    intent: Optional[IntentConfig] = None
    flow_control: Optional[FlowControlConfig] = None
    parallel: Optional[ParallelConfig] = None


class DesignConfig(BaseModel):
    """Pointer to the LibreLane design configuration and target PDK."""

    librelane_config_path: Path = Path("./design.json")
    pdk: str = "sky130A"
    flow_mode: Literal["flat", "hierarchical", "auto"] = "auto"
    modules: dict[str, ModuleConfig] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_hierarchical_modules(self) -> DesignConfig:
        if self.flow_mode == "hierarchical" and not self.modules:
            raise ValueError(
                "flow_mode='hierarchical' requires at least one entry in 'modules'"
            )
        return self


# ---------------------------------------------------------------------------
# Workspace / Docker / Execution
# ---------------------------------------------------------------------------


class WorkspaceConfig(BaseModel):
    """Per-attempt workspace isolation settings."""

    isolation: Literal["per_attempt"] = "per_attempt"
    base_clone_strategy: Literal[
        "reflink_or_hardlink", "hardlink", "copy"
    ] = "reflink_or_hardlink"


class DockerConfig(BaseModel):
    """Docker execution settings (only required when mode='docker')."""

    image: str = "agenticlane:latest"
    mount_root: str = "/run_root"
    attempt_root: str = "/attempt"


class ExecutionConfig(BaseModel):
    """Execution plane configuration."""

    mode: Literal["local", "docker"] = "local"
    tool_timeout_seconds: int = Field(default=21600, ge=1)
    env: dict[str, str] = Field(default_factory=dict)
    workspace: WorkspaceConfig = Field(default_factory=WorkspaceConfig)
    docker: Optional[DockerConfig] = None


# ---------------------------------------------------------------------------
# Intent
# ---------------------------------------------------------------------------


class IntentConfig(BaseModel):
    """User intent for the optimisation run."""

    prompt: str = ""
    weights_hint: dict[str, float] = Field(
        default_factory=lambda: {"timing": 0.7, "area": 0.3}
    )


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class ZeroShotConfig(BaseModel):
    """Zero-shot (Attempt 0) initialization settings."""

    enabled: bool = True
    apply_to_branches: Literal["all", "master_only", "none"] = "all"


class InitializationConfig(BaseModel):
    """Initialization strategy."""

    zero_shot: ZeroShotConfig = Field(default_factory=ZeroShotConfig)


# ---------------------------------------------------------------------------
# Budgets / Plateau / Flow-control
# ---------------------------------------------------------------------------


class BudgetConfig(BaseModel):
    """Per-stage attempt and cognitive-retry budgets."""

    physical_attempts_per_stage: int = Field(default=12, ge=1)
    cognitive_retries_per_attempt: int = Field(default=3, ge=0)
    cognitive_fail_counts_as_physical_attempt: bool = True
    max_total_cognitive_retries_per_stage: int = Field(default=30, ge=0)


class PlateauConfig(BaseModel):
    """Plateau detection parameters."""

    enabled: bool = True
    window: int = Field(default=3, ge=1)
    min_delta_score: float = Field(default=0.01, ge=0.0)


class AskHumanConfig(BaseModel):
    """Interactive human-in-the-loop policy."""

    enabled: bool = False


class FlowControlConfig(BaseModel):
    """Orchestration flow control settings."""

    stage_granularity: Literal["major", "step"] = "major"
    budgets: BudgetConfig = Field(default_factory=BudgetConfig)
    plateau_detection: PlateauConfig = Field(default_factory=PlateauConfig)
    deadlock_policy: Literal["ask_human", "auto_relax", "stop"] = "auto_relax"
    ask_human: AskHumanConfig = Field(default_factory=AskHumanConfig)


# ---------------------------------------------------------------------------
# Parallel
# ---------------------------------------------------------------------------


class PruneConfig(BaseModel):
    """Branch pruning policy."""

    enabled: bool = True
    prune_delta_score: float = 0.05
    prune_patience_attempts: int = Field(default=2, ge=1)


class ParallelConfig(BaseModel):
    """Parallel branch exploration settings."""

    enabled: bool = True
    max_parallel_branches: int = Field(default=3, ge=1)
    max_parallel_jobs: int = Field(default=2, ge=1)
    branch_policy: Literal["best_of_n", "pareto"] = "best_of_n"
    branch_budget_per_stage: int = Field(default=4, ge=1)
    prune: PruneConfig = Field(default_factory=PruneConfig)

    @model_validator(mode="after")
    def _jobs_lte_branches(self) -> ParallelConfig:
        if self.max_parallel_jobs > self.max_parallel_branches:
            raise ValueError(
                f"max_parallel_jobs ({self.max_parallel_jobs}) must be "
                f"<= max_parallel_branches ({self.max_parallel_branches})"
            )
        return self


# ---------------------------------------------------------------------------
# Action space: SDC / Tcl / Macro placements / Permissions
# ---------------------------------------------------------------------------


class SDCConfig(BaseModel):
    """SDC fragment generation mode."""

    mode: Literal["templated", "restricted_freeform", "expert_freeform"] = "templated"


class TclConfig(BaseModel):
    """Tcl hook injection settings."""

    enabled: bool = False
    mode: Literal["restricted_freeform", "expert_freeform"] = "restricted_freeform"
    hooks_allowed: list[str] = Field(
        default_factory=lambda: ["pre_step", "post_step"]
    )
    tools_allowed: list[str] = Field(default_factory=lambda: ["openroad"])


class SnapConfig(BaseModel):
    """Macro placement grid-snap settings."""

    enabled: bool = True
    rounding: Literal["nearest", "floor", "ceil"] = "nearest"
    max_iterations: int = Field(default=5, ge=1)


class MacroPlacementConfig(BaseModel):
    """Macro placement actuator settings."""

    snap: SnapConfig = Field(default_factory=SnapConfig)


class PermissionsConfig(BaseModel):
    """Action-space permissions (what channels the agent may use)."""

    config_vars: bool = True
    macro_placements: bool = True
    sdc: bool = True
    tcl: bool = False
    rtl_eco: bool = False


class ActionSpaceConfig(BaseModel):
    """Defines what the agent is allowed to modify."""

    permissions: PermissionsConfig = Field(default_factory=PermissionsConfig)
    sdc: SDCConfig = Field(default_factory=SDCConfig)
    tcl: TclConfig = Field(default_factory=TclConfig)
    macro_placements: MacroPlacementConfig = Field(
        default_factory=MacroPlacementConfig
    )


# ---------------------------------------------------------------------------
# ConstraintGuard (Guard sub-models)
# ---------------------------------------------------------------------------


class GuardPreprocessConfig(BaseModel):
    """Line-continuation preprocessing for SDC/Tcl scanning."""

    join_line_continuations: bool = True
    max_joined_lines: int = Field(default=32, ge=1)
    reject_unterminated_continuation: bool = True


class SDCGuardConfig(BaseModel):
    """SDC restricted-dialect scanner settings."""

    mode: Literal["templated", "restricted_freeform", "expert_freeform"] = "templated"
    deny_commands: list[str] = Field(default_factory=list)
    allow_commands: list[str] = Field(default_factory=list)
    allow_bracket_cmds: list[str] = Field(
        default_factory=lambda: [
            "get_ports",
            "get_pins",
            "get_nets",
            "get_cells",
            "get_clocks",
            "all_inputs",
            "all_outputs",
            "all_clocks",
        ]
    )
    forbid_tokens: list[str] = Field(
        default_factory=lambda: [
            "eval",
            "source",
            "exec",
            "open",
            "puts",
            "file",
            "glob",
        ]
    )
    reject_semicolons: bool = True
    ignore_comment_lines: bool = True
    reject_inline_comments: bool = True


class TclGuardConfig(BaseModel):
    """Tcl restricted-dialect scanner settings."""

    mode: Literal["restricted_freeform", "expert_freeform"] = "restricted_freeform"
    deny_commands: list[str] = Field(default_factory=list)
    forbid_tokens: list[str] = Field(
        default_factory=lambda: [
            "eval",
            "source",
            "exec",
            "open",
            "puts",
            "file",
            "glob",
        ]
    )
    reject_semicolons: bool = True
    ignore_comment_lines: bool = True


class GuardConfig(BaseModel):
    """ConstraintGuard master switch and scanner configs."""

    enabled: bool = True
    preprocess: GuardPreprocessConfig = Field(
        default_factory=GuardPreprocessConfig
    )
    sdc: SDCGuardConfig = Field(default_factory=SDCGuardConfig)
    tcl: TclGuardConfig = Field(default_factory=TclGuardConfig)


# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------


class ConstraintsConfig(BaseModel):
    """Constraint locking / relaxation policy."""

    locked_vars: list[str] = Field(default_factory=lambda: ["CLOCK_PERIOD"])
    allow_relaxation: bool = False
    max_relaxation_pct: float = Field(default=0.0, ge=0.0)
    locked_aspects: list[str] = Field(
        default_factory=lambda: [
            "clock_period",
            "timing_exceptions",
            "max_min_delay",
            "clock_uncertainty",
        ]
    )
    guard: GuardConfig = Field(default_factory=GuardConfig)


# ---------------------------------------------------------------------------
# Distillation
# ---------------------------------------------------------------------------


class CrashHandlingConfig(BaseModel):
    """Crash/timeout/OOM distillation settings."""

    stderr_tail_lines: int = Field(default=200, ge=1)
    missing_report_policy: Literal[
        "record_and_continue", "fail"
    ] = "record_and_continue"


class SpatialConfig(BaseModel):
    """Spatial hotspot extraction settings."""

    enabled: bool = True
    grid_bins_x: int = Field(default=2, ge=1)
    grid_bins_y: int = Field(default=2, ge=1)
    max_hotspots: int = Field(default=12, ge=1)
    macro_nearby_radius_um: float = Field(default=50.0, gt=0)


class ConstraintsDigestConfig(BaseModel):
    """ConstraintDigest extractor settings."""

    enabled: bool = True
    sources: list[str] = Field(
        default_factory=lambda: ["baseline", "user", "agent_fragments"]
    )


class DistillConfig(BaseModel):
    """Distillation layer settings."""

    crash_handling: CrashHandlingConfig = Field(
        default_factory=CrashHandlingConfig
    )
    spatial: SpatialConfig = Field(default_factory=SpatialConfig)
    constraints_digest: ConstraintsDigestConfig = Field(
        default_factory=ConstraintsDigestConfig
    )


# ---------------------------------------------------------------------------
# Judging
# ---------------------------------------------------------------------------


class JudgeStrictnessConfig(BaseModel):
    """Deterministic hard-gate requirements for judge passes."""

    hard_gates: list[str] = Field(
        default_factory=lambda: ["execution_success", "metrics_parse_valid"]
    )
    signoff_hard_gates: list[str] = Field(
        default_factory=lambda: ["drc_clean", "lvs_pass"]
    )


class JudgeEnsembleConfig(BaseModel):
    """Judge ensemble voting configuration."""

    models: list[str] = Field(
        default_factory=lambda: [
            "judge_model_a",
            "judge_model_b",
            "judge_model_c",
        ]
    )
    vote: Literal["majority", "unanimous"] = "majority"
    tie_breaker: Literal["fail", "pass"] = "fail"


class JudgingConfig(BaseModel):
    """Judge layer settings."""

    ensemble: JudgeEnsembleConfig = Field(
        default_factory=JudgeEnsembleConfig
    )
    strictness: JudgeStrictnessConfig = Field(
        default_factory=JudgeStrictnessConfig
    )


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


class NormalizationConfig(BaseModel):
    """Score normalization parameters."""

    method: Literal[
        "percent_over_baseline", "absolute_scaled"
    ] = "percent_over_baseline"
    epsilon: float = Field(default=1e-6, gt=0)
    clamp: float = Field(default=1.0, gt=0)


class EffectiveClockConfig(BaseModel):
    """Anti-cheat effective-clock scoring."""

    enabled: bool = True
    reducer: Literal["worst_corner", "best_corner", "average"] = "worst_corner"


class TimingScoringConfig(BaseModel):
    """Timing-specific scoring options."""

    effective_clock: EffectiveClockConfig = Field(
        default_factory=EffectiveClockConfig
    )


class ScoringConfig(BaseModel):
    """Scoring formula configuration."""

    normalization: NormalizationConfig = Field(
        default_factory=NormalizationConfig
    )
    timing: TimingScoringConfig = Field(default_factory=TimingScoringConfig)


# ---------------------------------------------------------------------------
# Artifact GC
# ---------------------------------------------------------------------------


class ArtifactGCConfig(BaseModel):
    """Artifact garbage-collection policy."""

    enabled: bool = True
    policy: Literal[
        "keep_pass_and_tips", "keep_all", "keep_none"
    ] = "keep_pass_and_tips"
    max_run_disk_gb: float = Field(default=40.0, gt=0)
    keep_failed_attempt_artifacts: int = Field(default=1, ge=0)
    keep_branch_tips: bool = True
    compress_pass_artifacts: bool = True
    compression: Literal["zstd", "gzip", "none"] = "zstd"
    on_exceed: Literal[
        "prune_then_warn", "warn_only", "fail"
    ] = "prune_then_warn"


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------


class StageModelOverride(BaseModel):
    """Per-stage LLM model override.

    Allows assigning different models to specific pipeline stages.
    ``None`` fields fall back to the global defaults.
    """

    worker: Optional[str] = None
    judge: Optional[list[str]] = None


class LLMModelsConfig(BaseModel):
    """Model selection for each agent role."""

    master: str = "model_master"
    worker: str = "model_worker"
    judge: list[str] = Field(
        default_factory=lambda: ["model_j1", "model_j2", "model_j3"]
    )
    stage_overrides: dict[str, StageModelOverride] = Field(
        default_factory=dict,
        description=(
            "Per-stage model overrides.  Keys are stage names "
            "(e.g. ROUTE_DETAILED, SIGNOFF).  Values override the "
            "default worker/judge models for that stage only."
        ),
    )


class StructuredOutputConfig(BaseModel):
    """LLM structured-output enforcement settings."""

    enabled: bool = True
    strategy: Literal[
        "json_schema", "function_call", "constrained_decoding"
    ] = "json_schema"
    strict: bool = True
    max_retries: int = Field(default=2, ge=0)
    json_extraction_fallback: bool = True


class KnowledgeConfig(BaseModel):
    """RAG knowledge base configuration."""

    enabled: bool = False
    db_path: Optional[Path] = Field(
        default=None,
        description="Path to ChromaDB directory. Defaults to bundled DB.",
    )
    embedding_model: str = "all-MiniLM-L6-v2"
    collection_name: str = "chip_design_knowledge"
    top_k: int = Field(default=5, ge=1, le=20)
    score_threshold: float = Field(default=0.35, ge=0.0, le=1.0)


class LLMConfig(BaseModel):
    """LLM provider and parameter configuration."""

    mode: Literal["local", "api"] = "local"
    provider: str = "litellm"
    models: LLMModelsConfig = Field(default_factory=LLMModelsConfig)
    structured_output: StructuredOutputConfig = Field(
        default_factory=StructuredOutputConfig
    )
    temperature: float = Field(default=0.0, ge=0.0)
    seed: int = 42
    reproducibility_mode: Literal[
        "replay", "deterministic", "stochastic"
    ] = "deterministic"
    api_base: Optional[str] = Field(
        default=None,
        description=(
            "Custom API base URL for OpenAI-compatible local servers "
            "(e.g. http://127.0.0.1:1234/v1 for LM Studio)."
        ),
    )


# ---------------------------------------------------------------------------
# Root config
# ---------------------------------------------------------------------------


class AgenticLaneConfig(BaseModel):
    """Root configuration model.

    Every section has safe defaults so that ``AgenticLaneConfig()``
    validates without any user input.  The defaults correspond to the
    "safe" profile: SDC templated, Tcl disabled, constraints locked,
    parallel exploration on with conservative budgets.
    """

    project: ProjectConfig = Field(default_factory=ProjectConfig)
    design: DesignConfig = Field(default_factory=DesignConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    intent: IntentConfig = Field(default_factory=IntentConfig)
    initialization: InitializationConfig = Field(
        default_factory=InitializationConfig
    )
    flow_control: FlowControlConfig = Field(default_factory=FlowControlConfig)
    parallel: ParallelConfig = Field(default_factory=ParallelConfig)
    action_space: ActionSpaceConfig = Field(default_factory=ActionSpaceConfig)
    constraints: ConstraintsConfig = Field(default_factory=ConstraintsConfig)
    distill: DistillConfig = Field(default_factory=DistillConfig)
    judging: JudgingConfig = Field(default_factory=JudgingConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    artifact_gc: ArtifactGCConfig = Field(default_factory=ArtifactGCConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    knowledge: KnowledgeConfig = Field(default_factory=KnowledgeConfig)
