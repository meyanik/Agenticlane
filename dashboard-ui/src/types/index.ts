/** TypeScript interfaces matching AgenticLane Python schemas. */

export type StageStatus = 'pending' | 'running' | 'passed' | 'executed' | 'failed' | 'rollback' | 'retrying';

export interface RunSummary {
  run_id: string;
  flow_mode: string;
  best_composite_score: number | null;
  best_branch_id: string | null;
  total_stages: number;
  stages_passed?: number;
  total_attempts: number;
  duration_seconds: number | null;
  start_time: string | null;
  status: string;
}

export interface Manifest {
  run_id: string;
  flow_mode: string;
  best_composite_score: number | null;
  best_branch_id: string | null;
  total_stages: number;
  stages_passed?: number;
  stages_failed?: number;
  status?: string;
  total_attempts: number;
  duration_seconds: number | null;
  start_time: string | null;
  random_seed: number;
  branches: Record<string, BranchInfo>;
  decisions: Decision[];
  module_results?: Record<string, ModuleResult>;
}

export interface BranchInfo {
  status: string;
  best_score: number | null;
  stages_completed: number;
}

export interface Decision {
  branch_id: string;
  stage: string;
  attempt: number;
  action: string;
  composite_score: number | null;
  reason: string;
  timestamp?: string;
}

export interface ModuleResult {
  completed: boolean;
  stages_completed: number;
  stages_failed: string[];
}

export interface TimingMetrics {
  setup_wns_ns: Record<string, number>;
}

export interface PhysicalMetrics {
  die_area_um2: number | null;
  utilization_pct: number | null;
  cell_count: number | null;
}

export interface SignoffMetrics {
  drc_count: number | null;
  lvs_pass: boolean | null;
  antenna_count: number | null;
}

export interface PowerMetrics {
  total_power_mw: number | null;
  internal_power_mw: number | null;
  switching_power_mw: number | null;
  leakage_power_mw: number | null;
}

export interface RouteMetrics {
  overflow: number | null;
  wirelength_um: number | null;
}

export interface MetricsPayload {
  schema_version: number;
  run_id: string;
  branch_id: string;
  stage: string;
  attempt: number;
  execution_status: string;
  missing_metrics: string[];
  timing: TimingMetrics | null;
  physical: PhysicalMetrics | null;
  route: RouteMetrics | null;
  signoff: SignoffMetrics | null;
  power: PowerMetrics | null;
  runtime: { stage_seconds: number } | null;
  synthesis: { cell_count: number; area_um2: number } | null;
}

export interface StageInfo {
  stage: string;
  status: StageStatus;
  attempts_count?: number;
  branch_id?: string;
  best_score?: number | null;
  execution_status?: string;
  timing?: TimingMetrics;
  physical?: PhysicalMetrics;
  signoff?: SignoffMetrics;
  power?: PowerMetrics;
}

export interface AttemptSummary {
  attempt: string;
  branch_id: string;
  metrics: MetricsPayload | null;
  composite_score: { score: number } | null;
  judge_votes: JudgeAggregate | null;
  checkpoint: { stage: string; attempt: number; status: string } | null;
}

export interface AttemptDetail extends AttemptSummary {
  run_id: string;
  stage: string;
  evidence: EvidencePack | null;
  patch: Patch | null;
  lessons_learned: unknown;
}

export interface JudgeVote {
  judge_id: string;
  model: string;
  vote: 'PASS' | 'FAIL';
  confidence: number;
  blocking_issues: BlockingIssue[];
  reason: string;
}

export interface BlockingIssue {
  metric_key: string;
  description: string;
  severity: string;
}

export interface JudgeAggregate {
  votes: JudgeVote[];
  result: 'PASS' | 'FAIL';
  confidence: number;
  blocking_issues: BlockingIssue[];
}

export interface EvidencePack {
  stage: string;
  attempt: number;
  execution_status: string;
  errors: string[];
  warnings: string[];
  spatial_hotspots: SpatialHotspot[];
}

export interface SpatialHotspot {
  type: string;
  region_label: string;
  severity: number;
  nearby_macros: string[];
}

export interface Patch {
  patch_id: string;
  stage: string;
  types: string[];
  config_vars: Record<string, unknown>;
  rationale: string;
}

export interface LLMCallRecord {
  timestamp: string;
  call_id: string;
  model: string;
  provider: string;
  role: string;
  stage: string;
  attempt: number;
  branch: string;
  latency_ms: number;
  tokens_in: number;
  tokens_out: number;
  error: string | null;
}

export interface ModelOption {
  id: string;
  provider: string;
  label: string;
}

export interface ExampleConfig {
  design: string;
  config_file: string;
  config_path: string;
}

export interface StageDescription {
  stages: string[];
  descriptions: Record<string, string>;
}

export interface SSEEvent {
  type: string;
  run_id: string;
  data: Record<string, unknown>;
  timestamp: number;
}

export interface ActiveRun {
  run_id: string;
  pid: number;
  elapsed_seconds: number;
  status: string;
}
