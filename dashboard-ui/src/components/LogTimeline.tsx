/** Terminal-aesthetic log timeline viewer with expandable entries. */

import { useState, useEffect, useRef } from 'react';
import { AGENT_COLORS, AGENT_ROLE_LABELS, STAGE_LABELS, STAGE_DESCRIPTIONS } from '../constants';
import type { LogEntry } from '../types/logs';

const TYPE_ICONS: Record<string, string> = {
  llm_call: '\u2728',    // sparkles
  decision: '\u2696',    // scales
  patch: '\u{1F527}',    // wrench
  metrics: '\u{1F4CA}',  // chart
  evidence: '\u{1F50D}', // magnifying glass
  judge_vote: '\u{1F3AF}', // target
  score: '\u2605',       // star
  checkpoint: '\u{1F4BE}', // floppy
  error: '\u26A0',       // warning
};

function formatTime(ts: string): string {
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return '--:--:--';
  }
}

function LogDetail({ entry }: { entry: LogEntry }) {
  const detail = entry.detail;
  if (!detail) return null;

  return (
    <div className="log-detail">
      {entry.type === 'llm_call' && (
        <>
          <div className="log-detail-row">
            <span className="log-detail-key">Model</span>
            <span>{String(detail.model || '?')}</span>
          </div>
          <div className="log-detail-row">
            <span className="log-detail-key">Provider</span>
            <span>{String(detail.provider || '?')}</span>
          </div>
          <div className="log-detail-row">
            <span className="log-detail-key">Latency</span>
            <span>{String(detail.latency_ms || 0)}ms</span>
          </div>
          <div className="log-detail-row">
            <span className="log-detail-key">Tokens</span>
            <span>{String(detail.tokens_in || 0)} in / {String(detail.tokens_out || 0)} out</span>
          </div>
          {detail.branch && (
            <div className="log-detail-row">
              <span className="log-detail-key">Branch</span>
              <span>{String(detail.branch)}</span>
            </div>
          )}
          {detail.error && (
            <div className="log-detail-row log-detail-error">
              <span className="log-detail-key">Error</span>
              <span>{String(detail.error)}</span>
            </div>
          )}
        </>
      )}
      {entry.type === 'decision' && (
        <>
          <div className="log-detail-row">
            <span className="log-detail-key">Decision</span>
            <span style={{
              color: detail.action === 'accept' ? 'var(--green)'
                : detail.action === 'reject' ? 'var(--red)'
                : detail.action === 'retry' ? 'var(--yellow)'
                : 'var(--text)',
              fontWeight: 600,
            }}>
              {detail.action === 'accept' ? 'PASSED' : detail.action === 'reject' ? 'FAILED' : String(detail.action || '?').toUpperCase()}
            </span>
          </div>
          {detail.branch_id && (
            <div className="log-detail-row">
              <span className="log-detail-key">Branch</span>
              <span>{String(detail.branch_id)}</span>
            </div>
          )}
          {detail.composite_score != null && (
            <div className="log-detail-row">
              <span className="log-detail-key">Quality Score</span>
              <span>{Number(detail.composite_score).toFixed(3)} (composite of timing, area, DRC)</span>
            </div>
          )}
          {detail.reason && (
            <div className="log-detail-row">
              <span className="log-detail-key">Details</span>
              <span>{String(detail.reason)}</span>
            </div>
          )}
        </>
      )}
      {(entry.type === 'patch' || entry.type === 'metrics' || entry.type === 'evidence' ||
        entry.type === 'judge_vote' || entry.type === 'score' || entry.type === 'checkpoint') && (
        <pre className="log-detail-json">{JSON.stringify(detail, null, 2)}</pre>
      )}
    </div>
  );
}

function LogEntryRow({ entry }: { entry: LogEntry }) {
  const [expanded, setExpanded] = useState(false);
  const color = AGENT_COLORS[entry.role] || AGENT_COLORS.execution;

  return (
    <div className={`log-entry ${expanded ? 'expanded' : ''} ${entry.isLive ? 'live' : ''}`}>
      <div className="log-entry-row" onClick={() => setExpanded(!expanded)}>
        <span className="log-entry-time">{formatTime(entry.timestamp)}</span>
        <span className="log-entry-role" style={{ background: color }}>
          {AGENT_ROLE_LABELS[entry.role] || entry.role[0].toUpperCase()}
        </span>
        <span className="log-entry-type">{TYPE_ICONS[entry.type] || '\u2022'}</span>
        <span className="log-entry-summary">{entry.summary}</span>
        {entry.stage && (
          <span className="log-entry-stage">{STAGE_LABELS[entry.stage] || entry.stage}</span>
        )}
        {entry.attempt != null && (
          <span className="log-entry-attempt">#{entry.attempt}</span>
        )}
        {entry.detail && (
          <span className="log-entry-expand">{expanded ? '\u25BC' : '\u25B6'}</span>
        )}
      </div>
      {expanded && <LogDetail entry={entry} />}
    </div>
  );
}

interface LogTimelineProps {
  entries: LogEntry[];
  autoScroll: boolean;
  isLive: boolean;
}

export function LogTimeline({ entries, autoScroll, isLive }: LogTimelineProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const prevLengthRef = useRef(0);

  // Auto-scroll when new entries arrive
  useEffect(() => {
    if (autoScroll && entries.length > prevLengthRef.current && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
    prevLengthRef.current = entries.length;
  }, [entries.length, autoScroll]);

  // Group entries by stage transitions
  let lastStage = '';

  return (
    <div className="log-timeline" ref={scrollRef}>
      <div className="log-timeline-scanline" />
      {entries.length === 0 ? (
        <div className="log-timeline-empty">No log entries yet.</div>
      ) : (
        entries.map(entry => {
          const showDivider = entry.stage && entry.stage !== lastStage;
          if (entry.stage) lastStage = entry.stage;

          return (
            <div key={entry.id}>
              {showDivider && (
                <div className="log-stage-divider">
                  <span className="log-stage-divider-line" />
                  <span className="log-stage-divider-label">
                    {STAGE_LABELS[entry.stage] || entry.stage}
                  </span>
                  <span className="log-stage-divider-line" />
                  {STAGE_DESCRIPTIONS[entry.stage] && (
                    <span className="log-stage-divider-desc">
                      {STAGE_DESCRIPTIONS[entry.stage]}
                    </span>
                  )}
                </div>
              )}
              <LogEntryRow entry={entry} />
            </div>
          );
        })
      )}
      {isLive && (
        <div className="log-cursor">
          <span className="log-cursor-blink">\u2588</span>
        </div>
      )}
    </div>
  );
}
