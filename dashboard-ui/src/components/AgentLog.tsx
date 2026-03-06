/** Agent activity feed — user-friendly narrative of what happened during the run. */

import { AGENT_COLORS, STAGE_LABELS, STAGE_DESCRIPTIONS } from '../constants';
import type { Decision } from '../types';

interface AgentLogProps {
  decisions: Decision[];
  maxEntries?: number;
}

interface ActivityEntry {
  stage: string;
  stageLabel: string;
  stageDesc: string;
  role: string;
  summary: string;
  detail: string;
  timestamp: string;
  attempt: number;
  action: string;
  branchId: string;
  score: number | null;
}

/** Format ISO timestamp to readable local time. */
function formatTime(ts: string): string {
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString('en-US', {
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  } catch {
    return '--:--:--';
  }
}

/** Convert decisions into user-friendly narrative entries, grouped by stage. */
function decisionsToActivity(decisions: Decision[]): ActivityEntry[] {
  return decisions.map(d => {
    const stageLabel = STAGE_LABELS[d.stage] || d.stage;
    const stageDesc = STAGE_DESCRIPTIONS[d.stage] || '';
    const branch = d.branch_id || 'B0';
    const attempt = d.attempt || 1;

    let role: string;
    let summary: string;
    let detail: string;

    switch (d.action) {
      case 'accept': {
        role = 'judge';
        const scoreStr = d.composite_score != null && d.composite_score > 0
          ? ` (score: ${d.composite_score.toFixed(3)})`
          : '';
        summary = `${stageLabel} completed successfully${scoreStr}`;
        detail = attempt === 1
          ? `Passed on the first attempt. The EDA tools ran successfully and the judge panel approved the results.`
          : `Passed after ${attempt} attempts. The agents optimized the configuration until the judge panel was satisfied.`;
        break;
      }
      case 'reject': {
        role = 'judge';
        const reason = d.reason || 'blocking issues';
        if (reason.startsWith('attempts_used=')) {
          const n = reason.split('=')[1];
          summary = `${stageLabel} failed after ${n} attempts`;
          detail = `All ${n} attempts were exhausted without meeting the quality gates. The pipeline will continue with the best result available.`;
        } else {
          summary = `${stageLabel} rejected by judges`;
          detail = `Reason: ${reason}. The agents could not produce results that satisfied the quality requirements.`;
        }
        break;
      }
      case 'retry': {
        role = 'master';
        const reason = d.reason || '';
        summary = `Retrying ${stageLabel} (attempt ${attempt})`;
        detail = reason.includes('defaulting to retry')
          ? 'The master agent could not reach a clear decision, so the stage is being retried with a different optimization approach.'
          : `Retry triggered: ${reason || 'trying a different configuration strategy.'}`;
        break;
      }
      case 'rollback': {
        role = 'rollback';
        summary = `Rolling back ${stageLabel}`;
        detail = d.reason
          ? `Rollback reason: ${d.reason}. Reverting to an earlier checkpoint to try a fundamentally different approach.`
          : 'The current optimization path was not productive. Reverting to try a different strategy.';
        break;
      }
      case 'advance': {
        role = 'master';
        summary = `Advancing to ${stageLabel}`;
        detail = 'The master agent has decided the current stage results are acceptable and is moving the pipeline forward.';
        break;
      }
      case 'prune': {
        role = 'master';
        summary = `Branch ${branch} pruned at ${stageLabel}`;
        detail = d.reason
          ? `Pruning reason: ${d.reason}`
          : 'This parallel branch was terminated because it fell too far behind the best-performing branch.';
        break;
      }
      case 'specialist_consulted': {
        role = 'rag';
        summary = `Specialist knowledge retrieved for ${stageLabel}`;
        detail = d.reason
          ? d.reason
          : 'Domain-specific chip design knowledge was retrieved from the knowledge base to assist the optimization.';
        break;
      }
      default: {
        role = 'execution';
        summary = `${stageLabel}: ${d.action}`;
        detail = d.reason || 'Action completed.';
      }
    }

    return {
      stage: d.stage,
      stageLabel,
      stageDesc,
      role,
      summary,
      detail,
      timestamp: d.timestamp || '',
      attempt,
      action: d.action,
      branchId: branch,
      score: d.composite_score,
    };
  });
}

const ROLE_LABELS: Record<string, string> = {
  worker: 'Worker',
  judge: 'Judge',
  master: 'Master',
  rag: 'RAG',
  execution: 'Exec',
  guard: 'Guard',
  error: 'Error',
  rollback: 'Rollback',
};

const ACTION_ICONS: Record<string, string> = {
  accept: '\u2713',    // check mark
  reject: '\u2717',    // cross mark
  retry: '\u21BB',     // clockwise arrow
  rollback: '\u21BA',  // anticlockwise arrow
  advance: '\u2192',   // right arrow
  prune: '\u2702',     // scissors
  specialist_consulted: '\u{1F4DA}', // books
};

export function AgentLog({ decisions, maxEntries = 200 }: AgentLogProps) {
  const entries = decisionsToActivity(decisions).slice(-maxEntries);

  if (entries.length === 0) {
    return (
      <div className="card agent-log-empty">
        <p style={{ color: 'var(--text-dim)', margin: 0 }}>
          No agent activity recorded for this run. Agent decisions appear here as each pipeline stage is evaluated.
        </p>
      </div>
    );
  }

  // Group entries by stage for visual separation
  let lastStage = '';

  return (
    <div className="card agent-log">
      <div className="agent-log-scroll">
        {entries.map((entry, i) => {
          const showStageHeader = entry.stage !== lastStage;
          lastStage = entry.stage;

          return (
            <div key={i}>
              {showStageHeader && (
                <div className="agent-log-stage-header">
                  <span className="agent-log-stage-name">{entry.stageLabel}</span>
                  {entry.stageDesc && (
                    <span className="agent-log-stage-desc">{entry.stageDesc}</span>
                  )}
                </div>
              )}
              <div className={`agent-log-entry agent-log-entry--${entry.action}`}>
                <span className="agent-log-icon">
                  {ACTION_ICONS[entry.action] || '\u2022'}
                </span>
                <div className="agent-log-content">
                  <div className="agent-log-header-row">
                    <span
                      className="agent-log-role"
                      style={{ color: AGENT_COLORS[entry.role] || AGENT_COLORS.execution }}
                    >
                      {ROLE_LABELS[entry.role] || entry.role}
                    </span>
                    <span className="agent-log-summary">{entry.summary}</span>
                    {entry.timestamp && (
                      <span className="agent-log-time">{formatTime(entry.timestamp)}</span>
                    )}
                  </div>
                  <div className="agent-log-detail">{entry.detail}</div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
