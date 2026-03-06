/** Run detail page — post-run analysis for completed runs. */

import { useParams, useNavigate } from 'react-router-dom';
import { useApi } from '../hooks/useApi';
import { api } from '../api';
import { Pipeline } from '../components/Pipeline';
import { ScoreChart } from '../components/ScoreChart';
import { AgentLog } from '../components/AgentLog';
import { MetricsCard } from '../components/MetricsCard';
import { StatusBadge } from '../components/StatusBadge';
import type { StageInfo, Manifest } from '../types';

function formatDuration(seconds: number | null): string {
  if (seconds == null) return '\u2014';
  if (seconds < 60) return `${seconds.toFixed(0)}s`;
  if (seconds < 3600) return `${(seconds / 60).toFixed(1)}m`;
  return `${(seconds / 3600).toFixed(1)}h`;
}

export function RunDetailPage() {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();

  const { data: manifest, loading: manifestLoading, error: manifestError } = useApi(
    () => api.getManifest(runId!),
    [runId],
  );
  const { data: stagesData } = useApi(
    () => api.getStages(runId!),
    [runId],
  );
  const { data: metricsData } = useApi(
    () => api.getMetrics(runId!),
    [runId],
  );
  // Check run status to detect crashes
  const { data: runStatus } = useApi(
    () => api.getRunStatus(runId!).catch(() => null),
    [runId],
  );

  if (!runId) {
    return <div className="container"><p className="text-dim">No run ID provided.</p></div>;
  }

  // Show crash info when manifest fails to load
  if (!manifest && !manifestLoading && manifestError) {
    const isCrash = runStatus?.status === 'crashed';
    return (
      <div className="run-detail-page">
        <nav>
          <a href="/" onClick={e => { e.preventDefault(); navigate('/'); }}>&larr; All Runs</a>
        </nav>
        <h1>Run: {runId}</h1>
        <div className="card" style={{
          borderColor: 'var(--red)',
          background: 'rgba(248,81,73,0.08)',
        }}>
          <h3 style={{ color: 'var(--red)', marginBottom: 8 }}>
            {isCrash ? 'Run crashed' : 'Run data unavailable'}
          </h3>
          <p style={{ color: 'var(--text-dim)', marginBottom: 12 }}>
            {isCrash
              ? 'The subprocess exited with an error before producing results.'
              : 'Could not load the run manifest. The run may still be starting or may have failed.'}
          </p>
          {runStatus?.error && (
            <pre style={{
              whiteSpace: 'pre-wrap', wordBreak: 'break-all',
              fontSize: '0.85rem', color: 'var(--text-dim)',
              background: 'var(--bg)', padding: 12, borderRadius: 6,
              maxHeight: 400, overflow: 'auto',
            }}>
              {runStatus.error}
            </pre>
          )}
        </div>
      </div>
    );
  }

  if (!manifest) {
    return <div className="container"><p className="text-dim">Loading run...</p></div>;
  }

  const stages: StageInfo[] = stagesData?.stages || [];
  const branchScores = metricsData?.branch_scores || {};
  const m = manifest as Manifest;

  // Compute actual passed count from stages data (passed = judge approved, executed = EDA tool succeeded)
  const stagesPassed = stages.filter(s => s.status === 'passed' || s.status === 'executed').length;
  const stagesTotal = stages.filter(s => s.status !== 'pending').length;

  // Find signoff metrics
  const signoff = stages.find(s => s.stage === 'SIGNOFF');

  return (
    <div className="run-detail-page">
      <nav>
        <a href="/" onClick={e => { e.preventDefault(); navigate('/'); }}>&larr; All Runs</a>
      </nav>

      <h1>Run: {runId}</h1>

      {/* Status banner for failed runs */}
      {m.status === 'failed' && (
        <div className="card" style={{
          borderColor: 'var(--red)',
          background: 'rgba(248,81,73,0.08)',
          marginBottom: 16,
        }}>
          <h3 style={{ color: 'var(--red)', margin: 0 }}>
            All stages failed
          </h3>
          <p style={{ color: 'var(--text-dim)', margin: '4px 0 0' }}>
            Every stage crashed or failed. This usually means EDA tools are not available
            or the config is invalid. Check stage details below for error messages.
          </p>
        </div>
      )}

      {/* Overview stats */}
      <div className="grid grid-4">
        <MetricsCard label="Status" value={m.status || 'unknown'} />
        <MetricsCard label="Best Score" value={m.best_composite_score} />
        <MetricsCard label="Best Branch" value={m.best_branch_id || '\u2014'} />
        <MetricsCard label="Duration" value={formatDuration(m.duration_seconds)} />
      </div>
      <div className="grid grid-4">
        <MetricsCard label="Stages Passed" value={`${stagesPassed}/${stagesTotal}`} />
        <MetricsCard label="Attempts" value={m.total_attempts} />
        <MetricsCard label="Flow Mode" value={m.flow_mode} />
        <MetricsCard label="Started" value={m.start_time?.substring(0, 19) || '\u2014'} />
      </div>

      {/* Pipeline visualization */}
      <h2>Pipeline</h2>
      <div className="card">
        <Pipeline
          stages={stages}
          onStageClick={stage => navigate(`/runs/${runId}/stages/${stage}`)}
        />
      </div>

      {/* Stage results chart */}
      <h2>Stage Results</h2>
      <div className="card">
        <ScoreChart stages={stages} data={branchScores} />
      </div>

      {/* Metrics summary */}
      <h2>Key Metrics</h2>
      <div className="grid grid-4">
        {signoff?.signoff && (
          <>
            <MetricsCard
              label="DRC"
              value={signoff.signoff.drc_count}
              tooltip="Design Rule Check violations - should be 0 for tape-out"
            />
            <MetricsCard
              label="LVS"
              value={signoff.signoff.lvs_pass ? 'PASS' : 'FAIL'}
              tooltip="Layout vs Schematic - verifies physical matches logical"
            />
            <MetricsCard
              label="Antenna"
              value={signoff.signoff.antenna_count}
              tooltip="Antenna violations - charge buildup during fabrication"
            />
          </>
        )}
        {stages.find(s => s.power)?.power && (
          <MetricsCard
            label="Total Power"
            value={stages.find(s => s.power)?.power?.total_power_mw ?? null}
            unit="mW"
            tooltip="Total estimated power consumption"
          />
        )}
      </div>

      {/* Branches */}
      <h2>Branches</h2>
      <div className="grid grid-2">
        {Object.entries(m.branches || {}).map(([bid, info]) => (
          <div key={bid} className="card">
            <h3>
              {bid}{' '}
              <StatusBadge status={info.status} />
            </h3>
            <p>
              Score: {info.best_score?.toFixed(3) || '\u2014'} |
              Stages: {info.stages_completed}
            </p>
          </div>
        ))}
      </div>

      {/* Agent activity log */}
      <h2>Agent Activity</h2>
      <AgentLog decisions={m.decisions || []} />

      {/* Hierarchical modules */}
      {m.module_results && Object.keys(m.module_results).length > 0 && (
        <>
          <h2>Hierarchical Modules</h2>
          <table>
            <thead>
              <tr>
                <th>Module</th>
                <th>Status</th>
                <th>Stages</th>
                <th>Failed</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(m.module_results).map(([name, info]) => (
                <tr key={name}>
                  <td>{name}</td>
                  <td><StatusBadge status={info.completed ? 'passed' : 'failed'} /></td>
                  <td>{info.stages_completed}</td>
                  <td>{info.stages_failed.join(', ') || '\u2014'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
