/** Live run monitoring page — real-time pipeline via SSE. */

import { useParams, useNavigate } from 'react-router-dom';
import { useEffect, useState, useCallback } from 'react';
import { useApi } from '../hooks/useApi';
import { useSSE } from '../hooks/useSSE';
import { api } from '../api';
import { Pipeline } from '../components/Pipeline';
import { AgentLog } from '../components/AgentLog';
import { MetricsCard } from '../components/MetricsCard';
import { StatusBadge } from '../components/StatusBadge';
import type { StageInfo, Decision } from '../types';

export function LiveRunPage() {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const [elapsed, setElapsed] = useState(0);
  const [crashError, setCrashError] = useState<string | null>(null);

  // Poll stages every 2s
  const { data: stagesData, refetch: refetchStages } = useApi(
    () => api.getStages(runId!),
    [runId],
    2000,
  );

  // Poll manifest for decisions
  const { data: manifest, refetch: refetchManifest } = useApi(
    () => api.getManifest(runId!).catch(() => null),
    [runId],
    3000,
  );

  // SSE for real-time updates
  const { events, connected } = useSSE(
    runId ? `/api/runs/${runId}/events` : null,
  );

  // Refetch when SSE events arrive
  useEffect(() => {
    if (events.length > 0) {
      refetchStages();
      refetchManifest();
    }
  }, [events.length, refetchStages, refetchManifest]);

  // Elapsed timer
  useEffect(() => {
    const id = setInterval(() => setElapsed(prev => prev + 1), 1000);
    return () => clearInterval(id);
  }, []);

  // Check if run completed or crashed
  const { data: activeData } = useApi(() => api.getActiveRuns(), [], 3000);
  const isActive = activeData?.active.some(a => a.run_id === runId) ?? true;

  const checkRunStatus = useCallback(async () => {
    if (!runId) return;
    try {
      const status = await api.getRunStatus(runId);
      if (status.status === 'crashed') {
        setCrashError(status.error || `Process exited with code ${status.exit_code ?? '?'}`);
      } else if (status.status === 'finished') {
        navigate(`/runs/${runId}`, { replace: true });
      }
    } catch {
      // Status endpoint not available or run not found — stay on page
    }
  }, [runId, navigate]);

  useEffect(() => {
    if (!isActive && elapsed > 5 && !crashError) {
      checkRunStatus();
    }
  }, [isActive, elapsed, crashError, checkRunStatus]);

  const stages: StageInfo[] = stagesData?.stages || [];
  const decisions: Decision[] = manifest?.decisions || [];
  const currentStage = stages.find(s => s.status === 'running') || [...stages].reverse().find((s: StageInfo) => s.status !== 'pending');
  const passedCount = stages.filter(s => s.status === 'passed').length;

  const handleStop = async () => {
    if (!runId) return;
    try {
      await api.stopRun(runId);
    } catch {
      // Run may already be finished/crashed — that's fine
    }
    navigate(`/runs/${runId}`);
  };

  return (
    <div className="live-run-page">
      <nav>
        <a href="/" onClick={e => { e.preventDefault(); navigate('/'); }}>&larr; All Runs</a>
        <span className="nav-spacer" />
        {connected ? (
          <StatusBadge status="running" label="LIVE" />
        ) : (
          <StatusBadge status="pending" label="CONNECTING..." />
        )}
      </nav>

      <div className="live-header">
        <h1>
          <span className="pulse-dot" />
          {runId}
        </h1>
        <button className="btn btn-danger" onClick={handleStop}>Stop Run</button>
      </div>

      {/* Crash error banner */}
      {crashError && (
        <div className="card" style={{ borderColor: 'var(--red)', background: 'rgba(248,81,73,0.08)' }}>
          <h3 style={{ color: 'var(--red)', marginBottom: 8 }}>Run crashed</h3>
          <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all', fontSize: '0.85rem', color: 'var(--text-dim)' }}>
            {crashError}
          </pre>
        </div>
      )}

      {/* Status bar */}
      <div className="grid grid-4">
        <MetricsCard label="Elapsed" value={`${Math.floor(elapsed / 60)}m ${elapsed % 60}s`} />
        <MetricsCard label="Progress" value={`${passedCount}/10`} />
        <MetricsCard label="Current Stage" value={currentStage?.stage || 'Starting...'} />
        <MetricsCard label="SSE Events" value={events.length} />
      </div>

      {/* Live pipeline */}
      <div className="card">
        <Pipeline
          stages={stages}
          onStageClick={stage => navigate(`/runs/${runId}/stages/${stage}`)}
        />
      </div>

      {/* Split: metrics + agent log */}
      <div className="grid grid-2">
        <div>
          <h2>Current Metrics</h2>
          {currentStage && (
            <div className="card">
              <p><strong>{currentStage.stage}</strong></p>
              {currentStage.execution_status && (
                <p>Status: <StatusBadge status={currentStage.execution_status} /></p>
              )}
              {currentStage.best_score != null && (
                <p>Score: {currentStage.best_score.toFixed(3)}</p>
              )}
              {currentStage.attempts_count && (
                <p>Attempts: {currentStage.attempts_count}</p>
              )}
            </div>
          )}
        </div>
        <div>
          <h2>Agent Activity</h2>
          <AgentLog decisions={decisions} maxEntries={50} />
        </div>
      </div>
    </div>
  );
}
