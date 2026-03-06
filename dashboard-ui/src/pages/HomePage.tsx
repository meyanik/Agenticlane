/** Home page — runs list + active runs banner + quick stats. */

import { useNavigate } from 'react-router-dom';
import { useApi } from '../hooks/useApi';
import { api } from '../api';
import { StatusBadge } from '../components/StatusBadge';
import type { RunSummary, StageInfo, ActiveRun } from '../types';
import { STAGE_ORDER } from '../constants';

function MiniPipeline({ stages }: { stages: StageInfo[] }) {
  return (
    <div className="mini-pipeline">
      {STAGE_ORDER.map(s => {
        const info = stages.find(st => st.stage === s);
        const status = info?.status || 'pending';
        const color = (status === 'passed' || status === 'executed') ? 'var(--green)'
          : status === 'failed' ? 'var(--red)'
          : status === 'running' ? 'var(--accent)'
          : 'var(--border)';
        return (
          <span
            key={s}
            className="mini-dot"
            style={{ background: color }}
            title={`${s}: ${status}`}
          />
        );
      })}
    </div>
  );
}

function formatDuration(seconds: number | null): string {
  if (seconds == null) return '\u2014';
  if (seconds < 60) return `${seconds.toFixed(0)}s`;
  if (seconds < 3600) return `${(seconds / 60).toFixed(1)}m`;
  return `${(seconds / 3600).toFixed(1)}h`;
}

export function HomePage() {
  const navigate = useNavigate();
  const { data: runsData, loading } = useApi(() => api.listRuns(), [], 5000);
  const { data: activeData } = useApi(() => api.getActiveRuns(), [], 3000);

  const runs: RunSummary[] = runsData?.runs || [];
  const active: ActiveRun[] = activeData?.active || [];
  const activeIds = new Set(active.map(a => a.run_id));

  // Quick stats
  const totalRuns = runs.length;
  const avgScore = runs.reduce((s, r) => s + (r.best_composite_score || 0), 0) / Math.max(totalRuns, 1);
  const passRate = runs.filter(r => r.status === 'completed').length / Math.max(totalRuns, 1) * 100;

  return (
    <div className="home-page">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1>AgenticLane Dashboard</h1>
          <p className="subtitle">RTL-to-GDSII Agentic Flow Monitor</p>
        </div>
        <div style={{ display: 'flex', gap: 12 }}>
          <a
            href="/new"
            className="btn btn-primary"
            style={{ display: 'flex', alignItems: 'center', gap: 8, textDecoration: 'none' }}
            onClick={e => { e.preventDefault(); navigate('/new'); }}
          >
            + New Run
          </a>
          <a
            href="/logs"
            className="btn"
            style={{ display: 'flex', alignItems: 'center', gap: 8, textDecoration: 'none' }}
            onClick={e => { e.preventDefault(); navigate('/logs'); }}
          >
            Agent Logs
          </a>
        </div>
      </div>

      {/* Active runs banner */}
      {active.length > 0 && (
        <div className="active-banner">
          <h2>Active Runs</h2>
          {active.map(a => (
            <div
              key={a.run_id}
              className="active-run-card card"
              onClick={() => navigate(`/runs/${a.run_id}/live`)}
            >
              <span className="pulse-dot" />
              <span className="active-run-id">{a.run_id}</span>
              <span className="active-run-elapsed">{formatDuration(a.elapsed_seconds)}</span>
              <StatusBadge status="running" label="RUNNING" />
            </div>
          ))}
        </div>
      )}

      {/* Quick stats */}
      <div className="grid grid-3">
        <div className="card">
          <div className="stat-label">Total Runs</div>
          <div className="stat-value">{totalRuns}</div>
        </div>
        <div className="card">
          <div className="stat-label">Avg Score</div>
          <div className="stat-value">{avgScore.toFixed(3)}</div>
        </div>
        <div className="card">
          <div className="stat-label">Success Rate</div>
          <div className="stat-value">{passRate.toFixed(0)}%</div>
        </div>
      </div>

      {/* Runs table */}
      <h2>All Runs</h2>
      {loading && <p className="text-dim">Loading...</p>}
      <table>
        <thead>
          <tr>
            <th>Run ID</th>
            <th>Mode</th>
            <th>Pipeline</th>
            <th>Best Score</th>
            <th>Stages</th>
            <th>Duration</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {runs.map(run => (
            <tr
              key={run.run_id}
              onClick={() => navigate(activeIds.has(run.run_id) ? `/runs/${run.run_id}/live` : `/runs/${run.run_id}`)}
              style={{ cursor: 'pointer' }}
            >
              <td><code>{run.run_id}</code></td>
              <td><span className="tag">{run.flow_mode}</span></td>
              <td>
                <MiniPipeline
                  stages={STAGE_ORDER.map((s, i) => ({
                    stage: s,
                    status: i < run.total_stages
                      ? (i < (run.stages_passed ?? 0) ? 'passed' : 'failed')
                      : 'pending',
                  }))}
                />
              </td>
              <td>{run.best_composite_score?.toFixed(3) || '\u2014'}</td>
              <td>{run.stages_passed ?? 0}/{run.total_stages}</td>
              <td>{formatDuration(run.duration_seconds)}</td>
              <td>
                <StatusBadge status={activeIds.has(run.run_id) ? 'running' : run.status} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {runs.length === 0 && !loading && (
        <p className="text-dim" style={{ textAlign: 'center', padding: 40 }}>
          No runs found. Start a new run from the{' '}
          <a href="/new">New Run</a> page.
        </p>
      )}
    </div>
  );
}
