/** Agent Logs page — full-page terminal-style viewer of all agent activity across a run. */

import { useState, useMemo, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { useApi } from '../hooks/useApi';
import { useAgentLogs } from '../hooks/useAgentLogs';
import { api } from '../api';
import { MetricsCard } from '../components/MetricsCard';
import { StatusBadge } from '../components/StatusBadge';
import { LogFilters } from '../components/LogFilters';
import { LogTimeline } from '../components/LogTimeline';
import type { AgentRole } from '../types/logs';
import type { RunSummary, ActiveRun } from '../types';
import '../styles/agent-logs.css';

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

export function AgentLogsPage() {
  // Fetch runs list and active runs
  const { data: runsData } = useApi(() => api.listRuns(), [], 5000);
  const { data: activeData } = useApi(() => api.getActiveRuns(), [], 3000);

  const runs: RunSummary[] = runsData?.runs || [];
  const activeRuns: ActiveRun[] = activeData?.active || [];
  const activeIds = new Set(activeRuns.map(a => a.run_id));

  // Auto-select: prefer active run, otherwise first run
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const runId = selectedRunId || activeRuns[0]?.run_id || runs[0]?.run_id || null;
  const isActive = runId ? activeIds.has(runId) : false;

  // Get logs
  const { entries, stats, loading, isLive } = useAgentLogs(runId, isActive);

  // Filters
  const [activeRoles, setActiveRoles] = useState<Set<AgentRole>>(
    new Set(['worker', 'judge', 'master', 'rag', 'execution']),
  );
  const [selectedStage, setSelectedStage] = useState('');
  const [searchText, setSearchText] = useState('');
  const [autoScroll, setAutoScroll] = useState(true);

  const toggleRole = useCallback((role: AgentRole) => {
    setActiveRoles(prev => {
      const next = new Set(prev);
      if (next.has(role)) next.delete(role);
      else next.add(role);
      return next;
    });
  }, []);

  // Apply filters
  const filteredEntries = useMemo(() => {
    return entries.filter(e => {
      if (!activeRoles.has(e.role)) return false;
      if (selectedStage && e.stage !== selectedStage) return false;
      if (searchText && !e.summary.toLowerCase().includes(searchText.toLowerCase())) return false;
      return true;
    });
  }, [entries, activeRoles, selectedStage, searchText]);

  return (
    <div className="agent-logs-page">
      {/* Nav */}
      <nav>
        <Link to="/">&larr; Dashboard</Link>
        <span className="nav-spacer" />
        {isLive && <StatusBadge status="running" label="LIVE" />}
      </nav>

      {/* Header */}
      <div className="agent-logs-header">
        <div>
          <h1>Agent Logs</h1>
          <p className="subtitle">Full agent activity trace across pipeline stages</p>
        </div>
        <select
          className="agent-logs-run-select"
          value={runId || ''}
          onChange={e => setSelectedRunId(e.target.value || null)}
        >
          {runs.length === 0 && <option value="">No runs available</option>}
          {runs.map(r => (
            <option key={r.run_id} value={r.run_id}>
              {r.run_id} {activeIds.has(r.run_id) ? '(LIVE)' : `(${r.status})`}
            </option>
          ))}
        </select>
      </div>

      {/* Stats bar */}
      <div className="grid grid-4" style={{ marginBottom: 16 }}>
        <MetricsCard
          label="LLM Calls"
          value={stats.totalLLMCalls}
          tooltip="Total number of LLM API calls during this run"
        />
        <MetricsCard
          label="Tokens In/Out"
          value={`${formatTokens(stats.tokensIn)} / ${formatTokens(stats.tokensOut)}`}
          tooltip="Total input and output tokens consumed"
        />
        <MetricsCard
          label="Avg Latency"
          value={stats.avgLatencyMs > 0 ? `${stats.avgLatencyMs.toFixed(0)}ms` : '\u2014'}
          tooltip="Average LLM call latency in milliseconds"
        />
        <MetricsCard
          label="Decisions"
          value={stats.decisionsCount}
          tooltip="Total accept/reject/advance decisions"
        />
      </div>

      {/* Filters */}
      <LogFilters
        activeRoles={activeRoles}
        onToggleRole={toggleRole}
        selectedStage={selectedStage}
        onStageChange={setSelectedStage}
        searchText={searchText}
        onSearchChange={setSearchText}
        autoScroll={autoScroll}
        onAutoScrollChange={setAutoScroll}
        isLive={isLive}
      />

      {/* Timeline */}
      {loading && entries.length === 0 ? (
        <div className="log-timeline-loading">Loading agent logs...</div>
      ) : (
        <LogTimeline
          entries={filteredEntries}
          autoScroll={autoScroll}
          isLive={isLive}
        />
      )}
    </div>
  );
}
