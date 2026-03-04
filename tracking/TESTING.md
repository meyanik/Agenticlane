# AgenticLane Test Strategies

Per-feature test plans organized by phase and sub-task. Every sub-task has concrete test cases written **before** implementation begins.

---

## Phase 0: Project Bootstrap

### P0 -- Verify Build & Tooling

- **What to test:** Package installs, CLI responds, test suite runs, linter/type-checker pass
- **Test type:** Smoke / CLI
- **Test file path:** `tests/test_smoke.py`
- **Key test cases:**
  - `test_pip_install_editable` -- `pip install -e ".[dev]"` exits 0
  - `test_cli_help` -- `agenticlane --help` prints usage and exits 0
  - `test_cli_version` -- `agenticlane --version` prints version string
  - `test_pytest_runs` -- `pytest` exits 0 with no collection errors
  - `test_ruff_check` -- `ruff check agenticlane/` exits 0
  - `test_mypy_check` -- `mypy agenticlane/` exits 0
- **Fixtures/mocks needed:** None
- **Pass criteria:** All commands exit 0; CLI outputs expected strings

---

## Phase 1: Deterministic Backbone

### P1.1 -- Config Models

- **What to test:** Schema validation, defaults, merge behavior, invalid value rejection
- **Test type:** Unit
- **Test file path:** `tests/config/test_models.py`
- **Key test cases:**
  - `test_default_config_valid` -- AgenticLaneConfig() with all defaults passes validation
  - `test_clock_period_must_be_positive` -- CLOCK_PERIOD <= 0 raises ValidationError
  - `test_max_parallel_jobs_lte_branches` -- max_parallel_jobs > max_parallel_branches raises ValidationError
  - `test_physical_attempts_gte_one` -- physical_attempts_per_stage < 1 raises ValidationError
  - `test_epsilon_must_be_positive` -- epsilon <= 0 raises ValidationError
  - `test_constraint_mode_consistency` -- sdc_allowed=False with locked_aspects=[] warns or errors
  - `test_config_roundtrip_yaml` -- Serialize to YAML and deserialize produces identical config
  - `test_config_partial_override` -- Partial dict merged onto defaults produces correct result
- **Fixtures/mocks needed:** `sample_config` fixture with known values
- **Pass criteria:** All validators fire correctly; roundtrip preserves values

### P1.2 -- Config Loader

- **What to test:** Profile loading, merge chain order, missing file handling, env var overrides
- **Test type:** Unit
- **Test file path:** `tests/config/test_loader.py`
- **Key test cases:**
  - `test_load_safe_profile` -- safe.yaml loads with conservative values
  - `test_load_balanced_profile` -- balanced.yaml loads with moderate values
  - `test_load_aggressive_profile` -- aggressive.yaml loads with aggressive values
  - `test_merge_chain_order` -- CLI overrides user overrides profile
  - `test_missing_user_config_uses_profile` -- No user config falls back to profile defaults
  - `test_env_var_override` -- AGENTICLANE_CLOCK_PERIOD=2.0 overrides config value
  - `test_invalid_profile_name_errors` -- Unknown profile name raises clear error
  - `test_missing_profile_file_errors` -- Profile file not found raises FileNotFoundError
- **Fixtures/mocks needed:** `tmp_path` with sample YAML files, monkeypatched env vars
- **Pass criteria:** Merge chain produces expected config; errors are clear

### P1.3 -- Canonical Schemas

- **What to test:** Roundtrip serialization, version field presence, required field enforcement
- **Test type:** Unit + Golden
- **Test file path:** `tests/schemas/test_schemas.py`
- **Key test cases:**
  - `test_patch_v5_roundtrip` -- Patch serializes/deserializes with all optional fields
  - `test_patch_v5_version_field` -- Patch.schema_version == "5"
  - `test_metrics_payload_v3_roundtrip` -- MetricsPayload with all sub-metrics
  - `test_evidence_pack_roundtrip` -- EvidencePack with spatial hotspots and constraint digest
  - `test_judge_vote_roundtrip` -- JudgeVote serializes correctly
  - `test_patch_rejected_v1` -- PatchRejected includes offending_channel and remediation_hint
  - `test_execution_result_success` -- ExecutionResult with status=success
  - `test_execution_result_failure` -- ExecutionResult with status=failure and error details
  - `test_llm_call_record` -- LLMCallRecord with all fields
  - `test_constraint_digest_v1` -- ConstraintDigest with clock definitions and exception counts
- **Fixtures/mocks needed:** `golden/schemas/` directory with known-good JSON files
- **Pass criteria:** All schemas roundtrip; golden files match; version fields correct

### P1.4 -- Stage/Knob Registries

- **What to test:** Graph traversal, rollback paths, knob range validation, stage ordering
- **Test type:** Unit
- **Test file path:** `tests/test_registries.py`
- **Key test cases:**
  - `test_stage_graph_has_10_stages` -- STAGE_GRAPH has exactly 10 entries
  - `test_stage_order_is_correct` -- STAGE_ORDER matches SYNTH -> ... -> SIGNOFF
  - `test_every_stage_has_rollback_targets` -- Each StageSpec.rollback_targets is non-empty or explicitly None
  - `test_knob_registry_has_all_knobs` -- All expected knobs present (FP_CORE_UTIL, PL_TARGET_DENSITY_PCT, etc.)
  - `test_knob_range_validation` -- Knob value outside min/max raises error
  - `test_knob_type_validation` -- Knob with wrong type (str for int knob) raises error
  - `test_stage_spec_required_outputs` -- Each stage lists its required output files
  - `test_rollback_path_from_route_to_floorplan` -- ROUTE_DETAILED can roll back to FLOORPLAN
- **Fixtures/mocks needed:** None (registries are static)
- **Pass criteria:** Graph is consistent; knob ranges enforced; rollback paths valid

### P1.5 -- Execution Adapter ABC

- **What to test:** ABC contract enforcement, method signatures, return type
- **Test type:** Unit
- **Test file path:** `tests/execution/test_adapter.py`
- **Key test cases:**
  - `test_adapter_is_abstract` -- Cannot instantiate ExecutionAdapter directly
  - `test_adapter_requires_run_stage` -- Subclass without run_stage raises TypeError
  - `test_adapter_run_stage_signature` -- Method accepts correct parameters
  - `test_adapter_returns_execution_result` -- Return type annotation is ExecutionResult
- **Fixtures/mocks needed:** Minimal concrete subclass for testing
- **Pass criteria:** ABC prevents instantiation without implementation

### P1.6 -- Mock Execution Adapter

- **What to test:** Deterministic output, knob responsiveness, failure injection, directory structure
- **Test type:** Unit + Integration
- **Test file path:** `tests/mocks/test_mock_adapter.py`
- **Key test cases:**
  - `test_mock_produces_execution_result` -- run_stage returns valid ExecutionResult
  - `test_mock_deterministic` -- Same inputs produce same metrics
  - `test_mock_responds_to_knob_changes` -- Changing FP_CORE_UTIL changes area metrics
  - `test_mock_failure_injection` -- Setting failure_probability=1.0 always fails
  - `test_mock_creates_directory_structure` -- attempt_dir contains expected files (.odb, .def, logs)
  - `test_mock_stage_specific_metrics` -- SYNTH produces timing metrics, ROUTE produces congestion
  - `test_mock_success_probability` -- With p=0.5, roughly half of 100 runs succeed
- **Fixtures/mocks needed:** `tmp_path` for attempt directories
- **Pass criteria:** Mock is deterministic, configurable, produces realistic structure

### P1.7 -- Workspace Manager

- **What to test:** Directory creation, hardlink cloning, isolation, cleanup
- **Test type:** Unit
- **Test file path:** `tests/execution/test_workspaces.py`
- **Key test cases:**
  - `test_create_attempt_dir` -- Creates `attempt_001/` with correct structure
  - `test_attempt_dir_numbering` -- Sequential attempts get incrementing numbers
  - `test_hardlink_clone` -- Cloned files share inode (os.stat)
  - `test_hardlink_fallback_to_copy` -- On unsupported FS, falls back to shutil.copytree
  - `test_isolation_between_attempts` -- Modifying one attempt dir doesn't affect another
  - `test_atomic_creation` -- Interrupted creation doesn't leave partial directory
- **Fixtures/mocks needed:** `tmp_path` with source files for cloning
- **Pass criteria:** Directories isolated; hardlinks used when available

### P1.8 -- State Baton

- **What to test:** Tokenize/detokenize roundtrip, Docker path rebasing, rebase map logging
- **Test type:** Unit + Property-based
- **Test file path:** `tests/execution/test_state_baton.py`
- **Key test cases:**
  - `test_tokenize_absolute_paths` -- `/home/user/run/file.odb` -> `{{RUN_ROOT}}/file.odb`
  - `test_detokenize_restores_paths` -- Roundtrip: tokenize then detokenize == original
  - `test_rebase_to_new_root` -- Tokens resolve to new run_root directory
  - `test_rebase_map_logged` -- state_rebase_map.json records all transformations
  - `test_docker_rebase` -- Paths rebase from host to container mount point
  - `test_property_tokenize_detokenize_roundtrip` -- hypothesis: for any path under run_root, roundtrip is identity
- **Fixtures/mocks needed:** Sample state JSON with embedded paths
- **Pass criteria:** Roundtrip preserves all paths; rebase map is complete

### P1.9 -- Distillation Layer

- **What to test:** Each extractor independently, EvidencePack assembly, crash resilience
- **Test type:** Unit + Golden
- **Test file path:** `tests/distill/test_extractors.py`, `tests/distill/test_assembly.py`
- **Key test cases:**
  - `test_timing_extractor` -- STA report -> setup_wns_ns, hold_wns_ns, tns_ns
  - `test_area_extractor` -- Area report -> total_area_um2, utilization_pct
  - `test_route_extractor` -- Route report -> congestion metrics, overflow count
  - `test_drc_extractor` -- DRC report -> violation_count, violation_types
  - `test_lvs_extractor` -- LVS report -> clean/dirty status
  - `test_power_extractor` -- Power report -> total_power_mw, leakage_pct
  - `test_runtime_extractor` -- Runtime metrics from log timestamps
  - `test_crash_extractor_never_crashes` -- Given garbage input, returns error evidence (no exception)
  - `test_spatial_extractor` -- Congestion map -> SpatialHotspot list with coordinates
  - `test_constraint_extractor` -- SDC file -> ConstraintDigest with clocks and exceptions
  - `test_evidence_pack_assembly` -- All extractors combine into valid EvidencePack
  - `test_golden_timing_report` -- Known STA report produces exact expected TimingMetrics
  - `test_golden_drc_report` -- Known DRC report produces exact expected DRC metrics
- **Fixtures/mocks needed:** `golden/reports/` directory with sample EDA tool output files
- **Pass criteria:** Extractors produce correct metrics; crash extractor never raises

### P1.10 -- Artifact GC

- **What to test:** File classification, pruning logic, tip preservation, disk limit, locking
- **Test type:** Unit
- **Test file path:** `tests/orchestration/test_gc.py`
- **Key test cases:**
  - `test_classify_ledger_files` -- .json, .jsonl, .md classified as Ledger (never GC'd)
  - `test_classify_medium_files` -- .rpt, .log classified as Medium
  - `test_classify_heavy_files` -- .odb, .def, .spef, .gds, .spice classified as Heavy
  - `test_gc_prunes_heavy_only` -- After GC, heavy files gone, ledger/medium remain
  - `test_gc_preserves_tips` -- Branch tip attempt directories never pruned
  - `test_gc_respects_disk_limit` -- GC triggers when total > disk_limit_gb
  - `test_gc_locks_prevent_concurrent` -- Two GC runs don't conflict via filesystem lock
  - `test_gc_dry_run` -- dry_run=True reports what would be deleted without deleting
- **Fixtures/mocks needed:** `tmp_path` with simulated run directory tree
- **Pass criteria:** Only heavy files pruned; tips preserved; limits respected

### P1.11 -- Orchestrator (Sequential)

- **What to test:** Full stage run with mock adapter, gate checking, budget exhaustion, checkpointing
- **Test type:** Integration
- **Test file path:** `tests/orchestration/test_orchestrator.py`
- **Key test cases:**
  - `test_single_stage_pass` -- One stage with mock adapter succeeds, checkpoint written
  - `test_single_stage_fail_retry` -- Stage fails, retries up to budget, then moves to next
  - `test_multi_stage_sequence` -- 3 stages in order, all pass
  - `test_gate_blocks_on_drc_violations` -- Stage with DRC violations fails gate check
  - `test_budget_exhaustion_policy_continue` -- After budget exhausted, continues to next stage
  - `test_budget_exhaustion_policy_stop` -- After budget exhausted, stops entire run
  - `test_checkpoint_written_on_pass` -- Successful stage writes checkpoint to branch tip
  - `test_distillation_called_per_attempt` -- Each attempt triggers distillation pipeline
- **Fixtures/mocks needed:** `mock_adapter` fixture, `sample_config` with short budgets
- **Pass criteria:** Stage sequence correct; gates enforced; checkpoints created

### P1.12 -- CLI (Phase 1)

- **What to test:** Command smoke tests, init project creation, run invocation, report output
- **Test type:** CLI Smoke
- **Test file path:** `tests/cli/test_cli.py`
- **Key test cases:**
  - `test_init_creates_project` -- `agenticlane init --design spm --pdk sky130` creates directory structure
  - `test_init_creates_config` -- Init writes agentic_config.yaml with correct design name
  - `test_run_requires_config` -- `agenticlane run` without config file errors clearly
  - `test_report_requires_run_id` -- `agenticlane report` without run_id errors clearly
  - `test_cli_help_all_commands` -- Each command's --help works
- **Fixtures/mocks needed:** `tmp_path` as working directory, CliRunner from Typer
- **Pass criteria:** CLI commands respond correctly; init creates valid structure

---

## Phase 2: ConstraintGuard + Cognitive Retry

### P2.1 -- ConstraintGuard Validator

- **What to test:** Locked vars rejection, SDC restricted dialect, Tcl restricted dialect, 3-channel separation
- **Test type:** Unit + Property-based
- **Test file path:** `tests/orchestration/test_constraint_guard.py`
- **Key test cases:**
  - `test_locked_var_override_rejected` -- Patch overriding CLOCK_PERIOD when locked returns PatchRejected
  - `test_unlocked_var_allowed` -- Patch changing FP_CORE_UTIL when unlocked passes
  - `test_sdc_channel_validates` -- SDC edits go through SDC scanner
  - `test_tcl_channel_validates` -- Tcl edits go through Tcl scanner
  - `test_knob_channel_validates` -- Knob overrides checked against locked_vars
  - `test_patch_rejected_has_remediation` -- PatchRejected includes remediation_hint string
  - `test_empty_patch_passes` -- Patch with no changes passes validation
  - `test_property_fuzz_sdc` -- hypothesis: random SDC strings never cause crash (only pass/reject)
- **Fixtures/mocks needed:** Sample patches with locked/unlocked configs
- **Pass criteria:** All constraint violations caught; no false positives on valid patches

### P2.2 -- Line Continuation Preprocessing

- **What to test:** Join behavior, max limit enforcement, unterminated handling
- **Test type:** Unit
- **Test file path:** `tests/orchestration/test_line_continuation.py`
- **Key test cases:**
  - `test_join_simple_continuation` -- `"set x \\\n5"` -> `"set x 5"`
  - `test_join_multiple_continuations` -- Three continued lines join correctly
  - `test_max_joined_lines_limit` -- Exceeding max_joined_lines raises error
  - `test_unterminated_continuation_reject` -- Backslash at EOF rejected if configured
  - `test_no_continuation_passthrough` -- Lines without backslash unchanged
  - `test_bypass_attempt_blocked` -- `"cre\\\nate_clock"` joins to `"create_clock"` (then SDC scanner catches it)
- **Fixtures/mocks needed:** None
- **Pass criteria:** All continuations joined before scanning; bypass attempts blocked

### P2.3 -- SDC Scanner

- **What to test:** Deny-list commands, bracket parsing, forbidden tokens, semicolons
- **Test type:** Unit + Property-based
- **Test file path:** `tests/orchestration/test_sdc_scanner.py`
- **Key test cases:**
  - `test_allowed_sdc_command_passes` -- `"set_false_path -from [get_ports clk]"` passes
  - `test_denied_command_rejected` -- `"create_clock -period 5"` rejected when timing locked
  - `test_semicolon_rejected` -- `"set_false_path ; create_clock"` rejected
  - `test_inline_comment_rejected` -- `"set_false_path # comment"` rejected
  - `test_allowed_brackets` -- `[get_ports ...]`, `[get_pins ...]` allowed
  - `test_nested_brackets_rejected` -- `[get_ports [get_nets x]]` rejected
  - `test_forbidden_token_eval` -- `"eval ..."` rejected
  - `test_forbidden_token_source` -- `"source ..."` rejected
  - `test_forbidden_token_exec` -- `"exec ..."` rejected
  - `test_empty_line_skipped` -- Blank lines pass through
  - `test_comment_line_skipped` -- `"# comment"` lines pass through
  - `test_property_random_sdc_no_crash` -- hypothesis: no input crashes the scanner
- **Fixtures/mocks needed:** Locked aspects config for deny-list derivation
- **Pass criteria:** All deny-list commands caught; bracket safety enforced

### P2.4 -- Tcl Scanner

- **What to test:** Restricted Tcl mode, read_sdc loophole, unsafe commands
- **Test type:** Unit
- **Test file path:** `tests/orchestration/test_tcl_scanner.py`
- **Key test cases:**
  - `test_read_sdc_rejected` -- `"read_sdc constraints.sdc"` rejected when constraints locked
  - `test_safe_tcl_command_passes` -- `"puts $var"` passes in restricted mode
  - `test_file_write_rejected` -- `"open file.txt w"` rejected
  - `test_exec_rejected` -- `"exec rm -rf /"` rejected
  - `test_source_rejected` -- `"source external.tcl"` rejected
- **Fixtures/mocks needed:** Tcl restriction config
- **Pass criteria:** read_sdc loophole closed; unsafe Tcl commands blocked

### P2.5 -- Cognitive Retry Loop

- **What to test:** Budget tracking, proposal storage, exhaustion behavior, feedback passing
- **Test type:** Unit + Integration
- **Test file path:** `tests/orchestration/test_cognitive_retry.py`
- **Key test cases:**
  - `test_valid_patch_accepted_first_try` -- Valid patch passes all checks, returned immediately
  - `test_invalid_patch_retried` -- Invalid patch triggers retry with feedback
  - `test_budget_tracking` -- cognitive_budget decremented per retry
  - `test_budget_exhaustion` -- After max retries, raises CognitiveBudgetExhausted
  - `test_proposal_stored` -- Each proposal saved in `attempt_dir/proposals/try_001/`
  - `test_proposal_includes_rejection_reason` -- Rejected proposals have rejection.json
  - `test_feedback_passed_to_next_attempt` -- Rejection reason included in next prompt context
- **Fixtures/mocks needed:** Mock agent that returns configurable patches, `tmp_path`
- **Pass criteria:** Free retries work; proposals recorded; budget enforced

### P2.6 -- Patch Materialization Pipeline

- **What to test:** 10-step order enforcement, early rejection, SDC fragment generation
- **Test type:** Unit + Integration
- **Test file path:** `tests/execution/test_patch_materialize.py`
- **Key test cases:**
  - `test_step_order_enforced` -- Steps execute in exact 1-10 order
  - `test_schema_validation_first` -- Invalid schema rejected at step 1 (before anything else)
  - `test_knob_range_validation_second` -- Out-of-range knob rejected at step 2
  - `test_constraint_guard_third` -- Locked var rejected at step 3 (before EDA execution)
  - `test_macro_resolution_fourth` -- Macro names resolved to instances
  - `test_grid_snap_fifth` -- Coordinates snapped to placement grid
  - `test_sdc_materialization_sixth` -- SDC edits written to fragment files
  - `test_tcl_materialization_seventh` -- Tcl edits written to hook files
  - `test_config_overrides_eighth` -- Knob overrides applied to LibreLane config
  - `test_early_rejection_no_eda` -- Steps 1-3 rejection means LibreLane never called
  - `test_full_pipeline_success` -- All 10 steps complete, execution result returned
- **Fixtures/mocks needed:** Mock adapter, sample patches (valid and invalid), `tmp_path`
- **Pass criteria:** Order is strict; early rejection saves EDA budget

---

## Phase 3: Single-Stage Agent Loop

### P3.1 -- LLM Provider Stack

- **What to test:** Connection, structured output, retry, fallback, provider switching
- **Test type:** Unit + Integration
- **Test file path:** `tests/agents/test_llm_provider.py`
- **Key test cases:**
  - `test_provider_returns_structured_output` -- Response parsed into Pydantic model
  - `test_response_hash_deterministic` -- Same response produces same SHA256 hash
  - `test_retry_on_transient_error` -- Connection timeout retried up to max_retries
  - `test_fallback_provider` -- Primary failure triggers fallback provider
  - `test_call_logged_to_jsonl` -- Each call appended to llm_calls.jsonl
  - `test_reproducibility_mode` -- temperature=0 + seed produces consistent output
  - `test_invalid_structured_output_retried` -- Malformed JSON triggers retry
- **Fixtures/mocks needed:** `MockLLMProvider` with pre-recorded responses
- **Pass criteria:** Structured output works; retries/fallback function; calls logged

### P3.2 -- LLM Call Logging

- **What to test:** JSONL format, all required fields present, hash determinism, debug mode
- **Test type:** Unit
- **Test file path:** `tests/agents/test_logging.py`
- **Key test cases:**
  - `test_log_entry_jsonl_format` -- Each line is valid JSON
  - `test_log_entry_has_required_fields` -- timestamp, call_id, model, provider, stage, attempt all present
  - `test_prompt_hash_deterministic` -- Same prompt -> same hash across calls
  - `test_response_hash_deterministic` -- Same response -> same hash across calls
  - `test_debug_mode_includes_full_prompt` -- debug=True includes prompt/response text
  - `test_normal_mode_excludes_full_prompt` -- debug=False omits prompt/response text
  - `test_latency_recorded` -- latency_ms is positive integer
  - `test_token_counts_recorded` -- tokens_in and tokens_out are non-negative
- **Fixtures/mocks needed:** `tmp_path` for log files
- **Pass criteria:** JSONL valid; all fields present; hashes deterministic

### P3.3 -- Worker Agent

- **What to test:** Patch generation, stage-specific context, constraint respect
- **Test type:** Unit + Integration
- **Test file path:** `tests/agents/workers/test_workers.py`
- **Key test cases:**
  - `test_base_worker_produces_patch` -- propose_patch returns valid Patch schema
  - `test_synth_worker_uses_synth_knobs` -- Only SYNTH-relevant knobs in proposal
  - `test_placement_worker_uses_placement_knobs` -- Only PLACE-relevant knobs in proposal
  - `test_worker_receives_metrics_context` -- MetricsPayload passed to prompt context
  - `test_worker_receives_evidence_context` -- EvidencePack passed to prompt context
  - `test_worker_receives_lessons_learned` -- History table included in prompt
  - `test_worker_respects_locked_vars` -- Patch never includes locked variable overrides
  - `test_worker_cognitive_retry_feedback` -- After rejection, next attempt includes feedback
- **Fixtures/mocks needed:** `MockLLMProvider`, sample metrics/evidence fixtures
- **Pass criteria:** Workers produce valid patches with stage-appropriate knobs

### P3.4 -- Judge Ensemble

- **What to test:** Majority voting, tie-breaking, gate enforcement, vote recording
- **Test type:** Unit
- **Test file path:** `tests/judge/test_ensemble.py`
- **Key test cases:**
  - `test_majority_pass` -- 2/3 judges vote PASS -> aggregate is PASS
  - `test_majority_fail` -- 2/3 judges vote FAIL -> aggregate is FAIL
  - `test_unanimous_pass` -- 3/3 PASS -> PASS with confidence 1.0
  - `test_unanimous_fail` -- 3/3 FAIL -> FAIL with confidence 1.0
  - `test_tie_breaking` -- Even number of judges with tie uses configured policy
  - `test_individual_votes_recorded` -- JudgeAggregate contains all individual JudgeVote entries
  - `test_gate_enforcement` -- Judge checks DRC gate (violations > 0 -> FAIL)
  - `test_judge_receives_metrics` -- Judge prompt includes before/after metrics
- **Fixtures/mocks needed:** `MockLLMProvider` returning configurable judge votes
- **Pass criteria:** Voting logic correct; all votes recorded; gates enforced

### P3.5 -- Scoring Formula

- **What to test:** Normalization math, anti-cheat detection, MCMM reduction, weight application
- **Test type:** Unit + Property-based
- **Test file path:** `tests/judge/test_scoring.py`
- **Key test cases:**
  - `test_improvement_positive_when_better` -- Lower WNS -> positive improvement score
  - `test_improvement_negative_when_worse` -- Higher area -> negative improvement score
  - `test_normalization_clamped` -- Result always in [-clamp, clamp]
  - `test_anti_cheat_timing` -- effective_setup_period = clock_period - setup_wns (relaxing clock penalized)
  - `test_composite_score_weighted` -- timing*0.5 + area*0.3 + route*0.2 matches manual calculation
  - `test_zero_baseline_handled` -- baseline=0 doesn't cause division by zero (epsilon used)
  - `test_property_normalization_bounded` -- hypothesis: for any baseline/value, result in [-clamp, clamp]
  - `test_property_better_value_better_score` -- hypothesis: strictly better metric -> strictly better score
- **Fixtures/mocks needed:** Sample MetricsPayload pairs (baseline vs current)
- **Pass criteria:** Math correct; anti-cheat works; properties hold

### P3.6 -- Prompt Templates

- **What to test:** Template rendering, variable substitution, output schema reference
- **Test type:** Unit
- **Test file path:** `tests/agents/test_prompts.py`
- **Key test cases:**
  - `test_worker_template_renders` -- worker_base.j2 renders with all required variables
  - `test_judge_template_renders` -- judge.j2 renders with metrics context
  - `test_master_template_renders` -- master.j2 renders with cross-stage context
  - `test_specialist_templates_render` -- Each specialist template renders
  - `test_missing_variable_raises` -- Template with undefined variable raises clear error
  - `test_output_schema_included` -- Rendered prompt includes JSON schema for expected output
  - `test_few_shot_examples_present` -- Templates include few-shot examples where specified
- **Fixtures/mocks needed:** Sample context dicts for each template
- **Pass criteria:** All templates render without error; output schemas present

### P3.7 -- History Compaction

- **What to test:** Table generation, sliding window, trend summarization
- **Test type:** Unit + Golden
- **Test file path:** `tests/orchestration/test_compaction.py`
- **Key test cases:**
  - `test_lessons_learned_table_format` -- Markdown table with correct columns
  - `test_lessons_learned_json_schema` -- JSON matches LessonsLearned Pydantic model
  - `test_sliding_window_last_n` -- Only last N attempts in detail (default N=5)
  - `test_older_attempts_summarized` -- Attempts before window summarized as trend line
  - `test_empty_history` -- No attempts -> empty table with headers only
  - `test_single_attempt` -- One attempt -> one row, no trend
  - `test_golden_lessons_learned` -- Known 5-attempt history produces exact expected markdown
- **Fixtures/mocks needed:** `golden/compaction/` with sample histories and expected outputs
- **Pass criteria:** Table format correct; window applied; golden files match

### P3.8 -- Single-Stage Flow (Integration)

- **What to test:** Complete PLACE_GLOBAL loop with all components integrated
- **Test type:** Integration
- **Test file path:** `tests/integration/test_single_stage_flow.py`
- **Key test cases:**
  - `test_placement_improves_over_3_attempts` -- Composite score improves across 3 physical attempts
  - `test_cognitive_retry_before_physical` -- Invalid patches retried before physical execution
  - `test_lessons_learned_generated` -- lessons_learned.md and .json written after each attempt
  - `test_llm_calls_logged` -- llm_calls.jsonl exists with entries for worker + judge
  - `test_judge_votes_recorded` -- judge_votes.json and judge_aggregate.json written
  - `test_patch_and_metrics_persisted` -- patch.json and metrics.json in each attempt dir
  - `test_evidence_pack_persisted` -- evidence.json in each attempt dir
- **Fixtures/mocks needed:** `MockExecutionAdapter` (improving metrics), `MockLLMProvider` (worker + judge responses)
- **Pass criteria:** Full loop runs; metrics improve; all artifacts written

---

## Phase 4: Rollback + Spatial Actuator

### P4.1 -- Rollback Engine

- **What to test:** Rollback path computation, checkpoint selection, state restoration
- **Test type:** Unit + Integration
- **Test file path:** `tests/orchestration/test_rollback.py`
- **Key test cases:**
  - `test_rollback_path_computed` -- ROUTE_DETAILED failure -> rollback to FLOORPLAN
  - `test_best_checkpoint_selected` -- Checkpoint with highest composite score selected
  - `test_state_baton_reloaded` -- Rolled-back stage receives correct state baton
  - `test_rollback_recorded_in_history` -- lessons_learned marks was_rollback=True
  - `test_no_rollback_when_improving` -- Improving metrics don't trigger rollback
  - `test_master_decides_rollback_vs_retry` -- Master agent's decision schema respected
- **Fixtures/mocks needed:** Multi-stage run history with checkpoints, `MockLLMProvider` for master
- **Pass criteria:** Rollback restores correct state; master decision respected

### P4.2 -- Spatial Hotspot Extraction

- **What to test:** Grid bin identification, coordinate accuracy, severity ranking
- **Test type:** Unit + Golden
- **Test file path:** `tests/distill/test_spatial.py`
- **Key test cases:**
  - `test_hotspot_has_coordinates` -- SpatialHotspot includes x_min, y_min, x_max, y_max
  - `test_hotspot_has_severity` -- Severity is normalized 0.0-1.0
  - `test_hotspot_lists_nearby_macros` -- nearby_macros populated from DEF/ODB
  - `test_hotspots_sorted_by_severity` -- Returned list is severity-descending
  - `test_golden_congestion_map` -- Known congestion input produces exact hotspot list
  - `test_no_congestion_empty_list` -- Clean routing -> empty hotspot list
- **Fixtures/mocks needed:** `golden/spatial/` with congestion reports and expected hotspots
- **Pass criteria:** Hotspots accurate; sorted; golden files match

### P4.3 -- Macro Placement Worker

- **What to test:** Grid snap, collision detection, deterministic ordering
- **Test type:** Unit + Property-based
- **Test file path:** `tests/agents/workers/test_macro_placement.py`
- **Key test cases:**
  - `test_coordinates_snapped_to_grid` -- Output coordinates are multiples of site dimensions
  - `test_collision_detection` -- Overlapping macros detected and rejected
  - `test_sorted_instance_names` -- Macro list sorted for determinism
  - `test_deterministic_offsets` -- Same hotspot input -> same placement proposal
  - `test_within_die_bounds` -- All macros placed within die area
  - `test_property_grid_snap_always_valid` -- hypothesis: any float coordinate snaps to valid grid point
- **Fixtures/mocks needed:** Tech LEF SITE dimensions, sample macro list, die area bounds
- **Pass criteria:** Grid snap correct; no collisions; deterministic

### P4.4 -- MACRO_PLACEMENT_CFG Materialization

- **What to test:** Format conversion, LibreLane compatibility
- **Test type:** Unit + Golden
- **Test file path:** `tests/execution/test_macro_cfg.py`
- **Key test cases:**
  - `test_patch_to_cfg_format` -- macro_placements[] converted to LibreLane MACRO_PLACEMENT_CFG string
  - `test_cfg_format_valid` -- Output matches LibreLane expected format
  - `test_golden_macro_cfg` -- Known patch produces exact expected CFG content
  - `test_empty_placements_no_cfg` -- No macros -> no CFG file generated
- **Fixtures/mocks needed:** `golden/macro_cfg/` with expected outputs
- **Pass criteria:** Format matches LibreLane expectations; golden files match

---

## Phase 5: Full Flow + Parallel Branches

### P5.1 -- Scheduler + Branch Manager

- **What to test:** Branch lifecycle, ID assignment, status tracking, divergence strategies
- **Test type:** Unit
- **Test file path:** `tests/orchestration/test_scheduler.py`
- **Key test cases:**
  - `test_branch_id_assignment` -- Branches get B0, B1, B2, ...
  - `test_branch_status_tracking` -- Status transitions: active -> pruned / completed
  - `test_diverse_sampling_strategy` -- Latin Hypercube sampling produces spread-out knob sets
  - `test_mutational_strategy` -- Perturbation within +/- 10-20% of best patch
  - `test_branch_isolated_directories` -- Each branch has separate workspace root
  - `test_branch_tip_tracked` -- Current best attempt for each branch recorded
- **Fixtures/mocks needed:** Sample knob ranges for sampling
- **Pass criteria:** Branch IDs unique; strategies produce valid knob sets

### P5.2 -- Parallel Job Scheduling

- **What to test:** Semaphore enforcement, isolation, concurrent execution
- **Test type:** Integration
- **Test file path:** `tests/orchestration/test_parallel.py`
- **Key test cases:**
  - `test_semaphore_limits_concurrency` -- max_parallel_jobs=2 means at most 2 concurrent
  - `test_isolation_no_shared_writes` -- Parallel branches don't write to shared workspace
  - `test_all_branches_complete` -- 3 branches all reach completion
  - `test_failure_in_one_branch_doesnt_affect_others` -- One branch failure doesn't crash others
- **Fixtures/mocks needed:** `MockExecutionAdapter` with configurable latency
- **Pass criteria:** Concurrency limited; branches isolated; all complete

### P5.3 -- Pruning + Selection

- **What to test:** Score-based pruning, patience enforcement, best branch selection
- **Test type:** Unit
- **Test file path:** `tests/orchestration/test_pruning.py`
- **Key test cases:**
  - `test_prune_underperforming_branch` -- Branch below threshold for patience attempts pruned
  - `test_no_prune_within_patience` -- Branch below threshold but within patience window survives
  - `test_best_branch_selected` -- Branch with highest composite score selected as winner
  - `test_pruned_branch_workspace_gc` -- Pruned branch heavy artifacts eligible for GC
  - `test_winning_branch_in_manifest` -- manifest.json records winning branch ID
- **Fixtures/mocks needed:** Branch score histories
- **Pass criteria:** Pruning logic correct; best selection correct

### P5.4 -- Zero-Shot Initialization

- **What to test:** IntentProfile to global_init_patch conversion, application to all branches
- **Test type:** Unit
- **Test file path:** `tests/orchestration/test_zero_shot.py`
- **Key test cases:**
  - `test_intent_profile_produces_patch` -- IntentProfile -> global_init_patch.json
  - `test_init_patch_applied_to_all_branches` -- Every branch starts from same init patch
  - `test_init_patch_valid_schema` -- global_init_patch.json validates against Patch schema
  - `test_master_produces_init` -- Master agent's attempt 0 generates init patch
- **Fixtures/mocks needed:** `MockLLMProvider` for master, sample IntentProfile
- **Pass criteria:** All branches start from consistent init patch

### P5.5 -- Plateau Detection

- **What to test:** Sliding window logic, threshold triggering, specialist activation
- **Test type:** Unit
- **Test file path:** `tests/orchestration/test_plateau.py`
- **Key test cases:**
  - `test_plateau_detected` -- Flat scores across window_size attempts triggers plateau
  - `test_no_plateau_when_improving` -- Increasing scores don't trigger
  - `test_specialist_activated_on_plateau` -- Plateau triggers specialist agent call
  - `test_configurable_window_and_threshold` -- Window size and threshold from config respected
- **Fixtures/mocks needed:** Score sequences (flat, improving, declining)
- **Pass criteria:** Plateau detection fires correctly; specialists activated

### P5.6 -- Cycle Detection

- **What to test:** Patch hashing, repeat detection, cycle logging
- **Test type:** Unit
- **Test file path:** `tests/orchestration/test_cycle_detection.py`
- **Key test cases:**
  - `test_same_patch_detected_as_cycle` -- Identical patch + key_overrides -> cycle detected
  - `test_different_patch_no_cycle` -- Different patches -> no cycle
  - `test_cycle_event_logged` -- Cycle detection writes event to cycle_events.jsonl
  - `test_hash_deterministic` -- Same patch always produces same hash
- **Fixtures/mocks needed:** Sample patches (identical and different)
- **Pass criteria:** Cycles detected reliably; no false positives

### P5.7 -- Deadlock Policy

- **What to test:** Policy enum, enforcement, human interaction mode
- **Test type:** Unit
- **Test file path:** `tests/orchestration/test_deadlock.py`
- **Key test cases:**
  - `test_ask_human_policy` -- Deadlock with ask_human pauses and prompts
  - `test_auto_relax_policy` -- Deadlock with auto_relax loosens constraints
  - `test_stop_policy` -- Deadlock with stop terminates run gracefully
  - `test_deadlock_after_n_attempts` -- Triggered after configurable max_no_progress attempts
- **Fixtures/mocks needed:** Run state with no progress for N attempts
- **Pass criteria:** Each policy behaves as specified

### P5.8 -- Reproducibility + Manifest

- **What to test:** Manifest completeness, replay mode, provenance chain
- **Test type:** Unit + Integration
- **Test file path:** `tests/test_manifest.py`
- **Key test cases:**
  - `test_manifest_has_tool_versions` -- Python version, agenticlane version, LibreLane version recorded
  - `test_manifest_has_config` -- Full resolved config in manifest
  - `test_manifest_has_seed` -- Random seed recorded for reproducibility
  - `test_manifest_has_all_decisions` -- Every stage/branch decision recorded
  - `test_manifest_has_best_branch` -- best_branch_id field populated
  - `test_manifest_has_timing` -- start_time, end_time, duration fields
  - `test_replay_mode` -- `agenticlane replay <run_id>` reproduces same decisions with same seed
- **Fixtures/mocks needed:** Complete run directory with all artifacts
- **Pass criteria:** Manifest is complete provenance record; replay works

### P5.9 -- Report Generation

- **What to test:** Terminal output, JSON output, branch comparison, metrics summary
- **Test type:** Unit + Golden
- **Test file path:** `tests/cli/test_report.py`
- **Key test cases:**
  - `test_report_terminal_output` -- Rich tables rendered to terminal
  - `test_report_json_output` -- `--json` flag outputs valid JSON report
  - `test_report_branch_comparison` -- All branches listed with scores
  - `test_report_best_metrics` -- Best branch metrics highlighted
  - `test_report_per_stage_analysis` -- Each stage's attempt history summarized
  - `test_golden_report` -- Known run data produces exact expected report
- **Fixtures/mocks needed:** `golden/reports/` with run data and expected output
- **Pass criteria:** Reports readable; JSON valid; golden files match

### P5.10 -- Dashboard

- **What to test:** Server starts, pages load, data renders from run folder
- **Test type:** Integration / E2E
- **Test file path:** `tests/cli/test_dashboard.py`
- **Key test cases:**
  - `test_dashboard_server_starts` -- FastAPI server starts on configured port
  - `test_dashboard_index_page_loads` -- GET / returns 200 with HTML
  - `test_dashboard_branch_timeline` -- Branch timeline data endpoint returns valid JSON
  - `test_dashboard_metrics_plots` -- Metrics plot data endpoint returns valid JSON
  - `test_dashboard_readonly` -- No POST/PUT/DELETE endpoints exist
  - `test_dashboard_from_golden_data` -- Known run folder renders expected dashboard content
- **Fixtures/mocks needed:** Golden run folder, httpx AsyncClient for FastAPI testing
- **Pass criteria:** Dashboard serves; pages render; data accurate; readonly

### P5.11 -- Checkpoint + Resume

- **What to test:** Checkpoint writing, resume detection, state restoration
- **Test type:** Unit + Integration
- **Test file path:** `tests/orchestration/test_checkpoint.py`
- **Key test cases:**
  - `test_checkpoint_written_after_success` -- checkpoint.json written after successful attempt
  - `test_checkpoint_contains_state` -- current_stage, last_attempt, branch_tip in checkpoint
  - `test_resume_detects_checkpoint` -- `--resume` finds latest checkpoint
  - `test_resume_restores_state` -- Run resumes from checkpointed stage/attempt
  - `test_resume_status_in_manifest` -- manifest.json records resumed=True with resume_from
  - `test_no_checkpoint_no_resume` -- Missing checkpoint with --resume errors clearly
- **Fixtures/mocks needed:** Run directory with checkpoint.json
- **Pass criteria:** Checkpoints accurate; resume works; manifest records it

### P5.12 -- Full Integration Test (E2E)

- **What to test:** Complete end-to-end flow with all components
- **Test type:** E2E
- **Test file path:** `tests/integration/test_full_flow.py`
- **Key test cases:**
  - `test_e2e_3_branches_10_stages` -- 3 branches execute all 10 stages with mock adapter + mock LLM
  - `test_e2e_parallel_execution` -- Branches run concurrently (verified by timing/logs)
  - `test_e2e_pruning_occurs` -- At least one branch pruned during run
  - `test_e2e_best_branch_selected` -- Winning branch identified with highest score
  - `test_e2e_manifest_complete` -- manifest.json has full provenance
  - `test_e2e_report_generated` -- Report command works on completed run
  - `test_e2e_dashboard_serves` -- Dashboard serves completed run data
- **Fixtures/mocks needed:** `MockExecutionAdapter` (multi-stage, multi-branch), `MockLLMProvider` (full agent responses)
- **Pass criteria:** Full flow completes; all artifacts present; metrics improve; best branch wins

---

## Test Infrastructure Summary

### Mock Objects
| Mock | Location | Purpose |
|------|----------|---------|
| MockExecutionAdapter | `tests/mocks/mock_adapter.py` | Simulates LibreLane execution with configurable metrics |
| MockLLMProvider | `tests/mocks/mock_llm.py` | Returns pre-recorded LLM responses by prompt hash |

### Golden File Directories
| Directory | Contents |
|-----------|----------|
| `tests/golden/schemas/` | Known-good JSON for each schema |
| `tests/golden/reports/` | Sample EDA tool output files |
| `tests/golden/compaction/` | Sample attempt histories and expected lessons_learned |
| `tests/golden/spatial/` | Congestion reports and expected hotspot lists |
| `tests/golden/macro_cfg/` | Expected MACRO_PLACEMENT_CFG outputs |
| `tests/golden/run_data/` | Complete mock run directory for report/dashboard tests |

### CI Pipeline
| Tier | Trigger | Tests |
|------|---------|-------|
| Fast CI | Every PR | ruff + mypy + unit + golden + ConstraintGuard |
| Nightly CI | Daily | Integration tests with mock adapter/LLM, full flow E2E |
| Weekly CI | Weekly | Real LibreLane on sky130/gf180 small designs |
