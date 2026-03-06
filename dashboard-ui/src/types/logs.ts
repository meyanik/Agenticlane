/** Unified log entry types for the Agent Logs page. */

export type LogEntryType =
  | 'llm_call'
  | 'decision'
  | 'patch'
  | 'metrics'
  | 'evidence'
  | 'judge_vote'
  | 'score'
  | 'checkpoint'
  | 'error';

export type AgentRole = 'worker' | 'judge' | 'master' | 'rag' | 'execution';

export interface LogEntry {
  id: string;
  timestamp: string;
  type: LogEntryType;
  role: AgentRole;
  stage: string;
  attempt?: number;
  summary: string;
  detail?: Record<string, unknown>;
  isLive?: boolean;
}

export interface LogStats {
  totalLLMCalls: number;
  tokensIn: number;
  tokensOut: number;
  avgLatencyMs: number;
  decisionsCount: number;
}
