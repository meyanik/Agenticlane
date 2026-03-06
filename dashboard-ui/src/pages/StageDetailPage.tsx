/** Stage detail page — single stage deep dive with attempt timeline. */

import { useParams, useNavigate } from 'react-router-dom';
import { useState } from 'react';
import { useApi } from '../hooks/useApi';
import { api } from '../api';
import { MetricsCard } from '../components/MetricsCard';
import { JudgeVotes } from '../components/JudgeVotes';
import { StatusBadge } from '../components/StatusBadge';
import { Tooltip } from '../components/Tooltip';
import { STAGE_LABELS, STAGE_DESCRIPTIONS, GLOSSARY } from '../constants';

export function StageDetailPage() {
  const { runId, stage } = useParams<{ runId: string; stage: string }>();
  const navigate = useNavigate();
  const [expanded, setExpanded] = useState<number | null>(null);
  const [showGlossary, setShowGlossary] = useState(false);

  const { data: attemptsData } = useApi(
    () => api.getStageAttempts(runId!, stage!),
    [runId, stage],
  );

  if (!runId || !stage) return null;

  const attempts = attemptsData?.attempts || [];
  const label = STAGE_LABELS[stage] || stage;
  const description = STAGE_DESCRIPTIONS[stage] || '';

  return (
    <div className="stage-detail-page">
      <nav>
        <a href={`/runs/${runId}`} onClick={e => { e.preventDefault(); navigate(`/runs/${runId}`); }}>&larr; Run Overview</a>
        <span className="nav-spacer" />
        <button className="btn btn-small" onClick={() => setShowGlossary(!showGlossary)}>
          {showGlossary ? 'Hide' : 'Show'} Glossary
        </button>
      </nav>

      <h1>{label}</h1>
      <div className="stage-description card">
        <p>{description}</p>
        <Tooltip text="Click attempt cards below to see detailed metrics, patches, and judge votes." />
      </div>

      {/* Glossary panel */}
      {showGlossary && (
        <div className="card glossary-panel">
          <h3>VLSI Glossary</h3>
          <div className="glossary-grid">
            {Object.entries(GLOSSARY).map(([term, def]) => (
              <div key={term} className="glossary-item">
                <strong>{term}</strong>: {def}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Attempt timeline */}
      <h2>Attempts ({attempts.length})</h2>
      <div className="attempt-timeline">
        {attempts.map((att, i) => {
          const isExpanded = expanded === i;
          const score = att.composite_score?.score;
          const passed = att.checkpoint?.status === 'passed';
          const status = passed ? 'passed' : 'failed';

          return (
            <div key={i} className="attempt-card-wrapper">
              {/* Timeline dot */}
              <div className="attempt-timeline-dot" style={{
                background: passed ? 'var(--green)' : 'var(--red)',
              }}>
                {att.attempt}
              </div>

              {/* Attempt card */}
              <div
                className={`card attempt-card ${isExpanded ? 'expanded' : ''}`}
                onClick={() => setExpanded(isExpanded ? null : i)}
              >
                <div className="attempt-header">
                  <span className="attempt-num">Attempt {att.attempt}</span>
                  <StatusBadge status={status} />
                  {score != null && <span className="attempt-score">Score: {score.toFixed(3)}</span>}
                </div>

                {/* Expanded detail */}
                {isExpanded && (
                  <div className="attempt-detail">
                    {/* Metrics */}
                    {att.metrics && (
                      <>
                        <h3>Metrics</h3>
                        <div className="grid grid-3">
                          <MetricsCard
                            label="Execution"
                            value={att.metrics.execution_status}
                            tooltip="Whether the EDA tool ran successfully"
                          />
                          <MetricsCard
                            label="Runtime"
                            value={att.metrics.runtime?.stage_seconds.toFixed(1) ?? null}
                            unit="s"
                            tooltip="How long the EDA tool took to run"
                          />
                          {att.metrics.timing && (
                            <MetricsCard
                              label="Setup WNS"
                              value={Object.values(att.metrics.timing.setup_wns_ns)[0] ?? null}
                              unit="ns"
                              tooltip="Worst Negative Slack - timing margin. Negative = violation."
                            />
                          )}
                          {att.metrics.physical && (
                            <>
                              <MetricsCard
                                label="Utilization"
                                value={att.metrics.physical.utilization_pct}
                                unit="%"
                                tooltip="How much of the die area is used by cells"
                              />
                              <MetricsCard
                                label="Cell Count"
                                value={att.metrics.physical.cell_count}
                                tooltip="Number of standard cells in the design"
                              />
                            </>
                          )}
                          {att.metrics.signoff && (
                            <>
                              <MetricsCard
                                label="DRC"
                                value={att.metrics.signoff.drc_count}
                                tooltip="Design Rule Check violations"
                              />
                              <MetricsCard
                                label="LVS"
                                value={att.metrics.signoff.lvs_pass ? 'PASS' : 'FAIL'}
                                tooltip="Layout vs Schematic verification"
                              />
                            </>
                          )}
                          {att.metrics.power && (
                            <MetricsCard
                              label="Power"
                              value={att.metrics.power.total_power_mw}
                              unit="mW"
                              tooltip="Total estimated power consumption"
                            />
                          )}
                        </div>
                      </>
                    )}

                    {/* Judge votes */}
                    {att.judge_votes && (
                      <>
                        <h3>Judge Votes</h3>
                        <JudgeVotes aggregate={att.judge_votes} />
                      </>
                    )}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {attempts.length === 0 && (
        <p className="text-dim" style={{ textAlign: 'center', padding: 40 }}>
          No attempts found for this stage.
        </p>
      )}
    </div>
  );
}
