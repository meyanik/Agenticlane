/** Hook that merges REST agent log data with live SSE events into a unified LogEntry stream. */

import { useMemo } from 'react';
import { useApi } from './useApi';
import { useSSE } from './useSSE';
import { api } from '../api';
import { STAGE_LABELS } from '../constants';
import type { LogEntry, LogStats, AgentRole, LogEntryType } from '../types/logs';
import type { LLMCallRecord, Decision, SSEEvent } from '../types';

/** Map SSE event types to log entry role + type. */
const SSE_MAP: Record<string, { role: AgentRole; type: LogEntryType }> = {
  patch_updated: { role: 'worker', type: 'patch' },
  metrics_updated: { role: 'execution', type: 'metrics' },
  judge_votes_updated: { role: 'judge', type: 'judge_vote' },
  composite_score_updated: { role: 'master', type: 'score' },
  evidence_updated: { role: 'execution', type: 'evidence' },
  checkpoint_updated: { role: 'master', type: 'checkpoint' },
};

/** Human-readable descriptions of what each agent role does per call. */
const ROLE_VERBS: Record<string, string> = {
  worker: 'analyzed metrics and proposed config changes',
  judge: 'evaluated the stage results',
  master: 'decided next action for the pipeline',
  specialist: 'provided domain-specific design advice',
  rag: 'retrieved relevant chip design knowledge',
};

/** Short model name for display (strip provider prefix). */
function shortModel(model: string): string {
  const parts = model.split('/');
  return parts[parts.length - 1];
}

function llmCallToEntry(call: LLMCallRecord): LogEntry {
  const role = (call.role || 'execution') as AgentRole;
  const verb = ROLE_VERBS[call.role] || 'processed data';
  const model = shortModel(call.model || 'unknown');
  const latSec = ((call.latency_ms || 0) / 1000).toFixed(1);

  let summary: string;
  if (call.error) {
    summary = `${role.charAt(0).toUpperCase() + role.slice(1)} agent call to ${model} failed: ${call.error}`;
  } else {
    summary = `${role.charAt(0).toUpperCase() + role.slice(1)} agent ${verb} using ${model} (${latSec}s, ${call.tokens_in || 0} in / ${call.tokens_out || 0} out tokens)`;
  }

  return {
    id: call.call_id || `llm-${call.timestamp}`,
    timestamp: call.timestamp,
    type: 'llm_call',
    role,
    stage: call.stage,
    attempt: call.attempt,
    summary,
    detail: {
      model: call.model,
      provider: call.provider,
      latency_ms: call.latency_ms,
      tokens_in: call.tokens_in,
      tokens_out: call.tokens_out,
      branch: call.branch,
      error: call.error,
    },
  };
}

function stageLabel(stage: string): string {
  return STAGE_LABELS[stage] || stage;
}

function decisionToEntry(d: Decision): LogEntry {
  let role: AgentRole;
  let type: LogEntryType;
  let summary: string;

  const sl = stageLabel(d.stage);
  const branch = d.branch_id || 'B0';
  const attempt = d.attempt || 1;

  switch (d.action) {
    case 'accept': {
      role = 'judge';
      type = 'decision';
      const scoreStr = d.composite_score != null && d.composite_score > 0
        ? ` with score ${d.composite_score.toFixed(3)}`
        : '';
      summary = `${sl} stage PASSED${scoreStr} — approved on attempt ${attempt} (branch ${branch})`;
      break;
    }
    case 'reject': {
      role = 'judge';
      type = 'decision';
      const reason = d.reason || 'blocking issues found';
      // Make "attempts_used=N" more readable
      const readableReason = reason.startsWith('attempts_used=')
        ? `all ${reason.split('=')[1]} attempts exhausted without meeting quality gates`
        : reason;
      summary = `${sl} stage FAILED — ${readableReason} (branch ${branch})`;
      break;
    }
    case 'retry': {
      role = 'master';
      type = 'decision';
      const reason = d.reason || 'retrying with new approach';
      const readableReason = reason.includes('defaulting to retry')
        ? 'master agent could not decide — retrying with a different optimization strategy'
        : reason;
      summary = `Retrying ${sl} — ${readableReason} (attempt ${attempt}, branch ${branch})`;
      break;
    }
    case 'rollback': {
      role = 'master';
      type = 'decision';
      summary = `Rolling back ${sl} — ${d.reason || 'reverting to earlier checkpoint to try a different approach'} (branch ${branch})`;
      break;
    }
    case 'advance': {
      role = 'master';
      type = 'decision';
      summary = `Advancing pipeline to ${sl} stage (branch ${branch})`;
      break;
    }
    case 'prune': {
      role = 'master';
      type = 'decision';
      summary = `Pruned branch ${branch} at ${sl} — ${d.reason || 'underperforming compared to other branches'}`;
      break;
    }
    case 'specialist_consulted': {
      role = 'rag';
      type = 'decision';
      summary = `Specialist consulted for ${sl} — ${d.reason || 'retrieved domain knowledge to assist optimization'}`;
      break;
    }
    default: {
      role = 'execution';
      type = 'decision';
      summary = `${sl}: ${d.action} — ${d.reason || 'action completed'}`;
    }
  }

  return {
    id: `decision-${d.branch_id}-${d.stage}-${d.attempt}-${d.action}`,
    timestamp: d.timestamp || new Date().toISOString(),
    type,
    role,
    stage: d.stage,
    attempt: d.attempt,
    summary,
    detail: {
      action: d.action,
      composite_score: d.composite_score,
      reason: d.reason,
      branch_id: d.branch_id,
    },
  };
}

function sseEventToEntry(event: SSEEvent): LogEntry | null {
  const mapping = SSE_MAP[event.type];
  if (!mapping) return null;

  const data = event.data || {};
  const stage = (data.stage as string) || '';
  const attempt = (data.attempt as number) || undefined;
  const sl = stageLabel(stage);

  let summary: string;
  switch (event.type) {
    case 'patch_updated':
      summary = `Worker proposed config changes for ${sl}: ${(data.rationale as string) || 'tuning EDA tool parameters'}`;
      break;
    case 'metrics_updated': {
      const status = (data.execution_status as string) || '';
      summary = status === 'success'
        ? `${sl} EDA tools completed successfully — collecting results`
        : status === 'tool_crash'
          ? `${sl} EDA tools crashed — check logs for errors`
          : `${sl} execution finished — gathering metrics (${status || 'done'})`;
      break;
    }
    case 'judge_votes_updated':
      summary = `Judge panel evaluated ${sl} results: ${(data.result as string) || 'votes submitted'}`;
      break;
    case 'composite_score_updated':
      summary = `${sl} scored ${typeof data.score === 'number' ? (data.score as number).toFixed(3) : '?'} (composite of timing, area, and DRC metrics)`;
      break;
    case 'evidence_updated': {
      const errs = (data.errors as string[])?.length || 0;
      const warns = (data.warnings as string[])?.length || 0;
      summary = errs > 0
        ? `${sl} produced ${errs} error${errs > 1 ? 's' : ''} and ${warns} warning${warns > 1 ? 's' : ''}`
        : warns > 0
          ? `${sl} completed with ${warns} warning${warns > 1 ? 's' : ''} (no errors)`
          : `${sl} completed cleanly — no errors or warnings`;
      break;
    }
    case 'checkpoint_updated':
      summary = `${sl} checkpoint saved — progress preserved for potential rollback`;
      break;
    default:
      summary = event.type;
  }

  return {
    id: `sse-${event.type}-${event.timestamp}`,
    timestamp: new Date(event.timestamp * 1000).toISOString(),
    type: mapping.type,
    role: mapping.role,
    stage,
    attempt,
    summary,
    detail: data,
    isLive: true,
  };
}

interface UseAgentLogsResult {
  entries: LogEntry[];
  stats: LogStats;
  loading: boolean;
  isLive: boolean;
}

export function useAgentLogs(runId: string | null, isActive: boolean): UseAgentLogsResult {
  // REST data (poll every 5s for non-active, every 10s for active since SSE handles live)
  const { data: agentData, loading } = useApi(
    () => (runId ? api.getAgentLog(runId) : Promise.resolve({ llm_calls: [], decisions: [] })),
    [runId],
    runId ? (isActive ? 10000 : 5000) : undefined,
  );

  // SSE for live runs
  const sseUrl = runId && isActive ? `/api/runs/${runId}/events` : null;
  const { events: sseEvents, connected } = useSSE(sseUrl);

  const entries = useMemo(() => {
    const result: LogEntry[] = [];

    // Add LLM calls from REST
    const llmCalls = (agentData?.llm_calls || []) as LLMCallRecord[];
    for (const call of llmCalls) {
      result.push(llmCallToEntry(call));
    }

    // Add decisions from REST
    const decisions = (agentData?.decisions || []) as Decision[];
    for (const d of decisions) {
      result.push(decisionToEntry(d));
    }

    // Add live SSE events
    for (const event of sseEvents) {
      const entry = sseEventToEntry(event);
      if (entry) result.push(entry);
    }

    // Sort by timestamp
    result.sort((a, b) => a.timestamp.localeCompare(b.timestamp));
    return result;
  }, [agentData, sseEvents]);

  const stats = useMemo((): LogStats => {
    const llmCalls = (agentData?.llm_calls || []) as LLMCallRecord[];
    const decisions = (agentData?.decisions || []) as Decision[];

    const totalLLMCalls = llmCalls.length;
    const tokensIn = llmCalls.reduce((s, c) => s + (c.tokens_in || 0), 0);
    const tokensOut = llmCalls.reduce((s, c) => s + (c.tokens_out || 0), 0);
    const avgLatencyMs = totalLLMCalls > 0
      ? llmCalls.reduce((s, c) => s + (c.latency_ms || 0), 0) / totalLLMCalls
      : 0;
    const decisionsCount = decisions.length;

    return { totalLLMCalls, tokensIn, tokensOut, avgLatencyMs, decisionsCount };
  }, [agentData]);

  return { entries, stats, loading, isLive: connected };
}
