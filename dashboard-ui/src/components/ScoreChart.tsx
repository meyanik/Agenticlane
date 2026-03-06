/** Stage results visualization — shows execution outcome per stage. */

import { STAGE_ORDER } from '../constants';
import type { StageInfo } from '../types';

interface ScoreChartProps {
  /** Legacy prop — decision-based score data (branch → points). */
  data?: Record<string, { stage: string; attempt: number; score: number }[]>;
  /** Preferred prop — stage info with actual status. */
  stages?: StageInfo[];
  width?: number;
  height?: number;
}

const STAGE_SHORT: Record<string, string> = {
  SYNTH: 'SYN',
  FLOORPLAN: 'FP',
  PDN: 'PDN',
  PLACE_GLOBAL: 'PG',
  PLACE_DETAILED: 'PD',
  CTS: 'CTS',
  ROUTE_GLOBAL: 'RG',
  ROUTE_DETAILED: 'RD',
  FINISH: 'FIN',
  SIGNOFF: 'SO',
};

const STATUS_BAR_COLORS: Record<string, string> = {
  passed: '#238636',
  executed: '#2ea043',
  failed: '#da3633',
  pending: '#30363d',
  running: '#1f6feb',
};

export function ScoreChart({ data, stages, width = 700, height = 250 }: ScoreChartProps) {
  // If we have stages data, show a stage results bar chart
  if (stages && stages.length > 0) {
    return <StageResultsChart stages={stages} width={width} height={height} />;
  }

  // Fallback: check if score data has any non-zero scores
  const hasScores = data && Object.values(data).some(pts => pts.some(p => p.score > 0));
  if (!hasScores) {
    return (
      <div style={{
        width, height: 80,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        color: 'var(--text-dim)', fontSize: 14,
      }}>
        No score progression data available.
      </div>
    );
  }

  // Original score line chart for when we have real score data
  return <ScoreLineChart data={data!} width={width} height={height} />;
}

function StageResultsChart({ stages, width, height }: { stages: StageInfo[]; width: number; height: number }) {
  const pad = { left: 50, right: 20, top: 30, bottom: 50 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;

  const barW = Math.min(plotW / STAGE_ORDER.length - 8, 50);
  const gap = (plotW - barW * STAGE_ORDER.length) / (STAGE_ORDER.length + 1);

  const stageMap = new Map(stages.map(s => [s.stage, s]));

  // Find max attempts for Y axis
  const maxAttempts = Math.max(
    ...stages.map(s => s.attempts_count ?? 1),
    1
  );

  return (
    <svg viewBox={`0 0 ${width} ${height}`} style={{ width, height }}>
      {/* Title */}
      <text x={width / 2} y={16} textAnchor="middle" fill="var(--text-dim)" fontSize={12}>
        Stage Results — color = outcome, height = attempts
      </text>

      {/* Y axis gridlines + labels */}
      {Array.from({ length: 5 }, (_, i) => {
        const val = (maxAttempts / 4) * (4 - i);
        const y = pad.top + (plotH / 4) * i;
        return (
          <g key={i}>
            <line x1={pad.left} y1={y} x2={width - pad.right} y2={y}
              stroke="#30363d" strokeWidth={0.5} />
            <text x={pad.left - 6} y={y + 4} textAnchor="end"
              fill="#8b949e" fontSize={10} fontFamily="monospace">
              {val % 1 === 0 ? val : val.toFixed(1)}
            </text>
          </g>
        );
      })}

      {/* Bars */}
      {STAGE_ORDER.map((stageName, i) => {
        const info = stageMap.get(stageName);
        const attempts = info?.attempts_count ?? 0;
        const status = info?.status || 'pending';
        const barH = attempts > 0 ? Math.max((attempts / maxAttempts) * plotH, 4) : 4;
        const x = pad.left + gap + i * (barW + gap);
        const y = pad.top + plotH - barH;
        const color = STATUS_BAR_COLORS[status] || STATUS_BAR_COLORS.pending;

        return (
          <g key={stageName}>
            {/* Bar */}
            <rect x={x} y={y} width={barW} height={barH} rx={3}
              fill={color} opacity={0.85} />

            {/* Status icon on top */}
            <text x={x + barW / 2} y={y - 6} textAnchor="middle"
              fill={color} fontSize={14}>
              {status === 'passed' || status === 'executed' ? '\u2713' : status === 'failed' ? '\u2717' : '\u2014'}
            </text>

            {/* Attempt count inside bar (if tall enough) */}
            {barH > 16 && (
              <text x={x + barW / 2} y={y + barH / 2 + 4} textAnchor="middle"
                fill="#fff" fontSize={10} fontWeight={600}>
                {attempts}
              </text>
            )}

            {/* Stage label */}
            <text x={x + barW / 2} y={height - pad.bottom + 14} textAnchor="middle"
              fill="#8b949e" fontSize={9} fontFamily="monospace">
              {STAGE_SHORT[stageName] || stageName}
            </text>

            {/* Full name on second line */}
            <text x={x + barW / 2} y={height - pad.bottom + 26} textAnchor="middle"
              fill="#484f58" fontSize={7}>
              {stageName === 'PLACE_GLOBAL' ? 'GLOBAL' :
               stageName === 'PLACE_DETAILED' ? 'DETAIL' :
               stageName === 'ROUTE_GLOBAL' ? 'GLOBAL' :
               stageName === 'ROUTE_DETAILED' ? 'DETAIL' : ''}
            </text>
          </g>
        );
      })}

      {/* Legend */}
      {[
        { label: 'Passed', color: '#238636' },
        { label: 'Executed', color: '#2ea043' },
        { label: 'Failed', color: '#da3633' },
      ].map((item, i) => (
        <g key={item.label}>
          <rect x={width - pad.right - 240 + i * 85} y={height - 14}
            width={10} height={10} rx={2} fill={item.color} />
          <text x={width - pad.right - 226 + i * 85} y={height - 5}
            fill="#8b949e" fontSize={10}>
            {item.label}
          </text>
        </g>
      ))}
    </svg>
  );
}

/** Original line chart for runs with actual score progression. */
function ScoreLineChart({ data, width, height }: {
  data: Record<string, { stage: string; attempt: number; score: number }[]>;
  width: number; height: number;
}) {
  const branches = Object.entries(data);
  let maxPoints = 0;
  let maxScore = 0;
  for (const [, points] of branches) {
    maxPoints = Math.max(maxPoints, points.length);
    for (const p of points) maxScore = Math.max(maxScore, p.score);
  }
  if (maxScore === 0) maxScore = 1;

  const pad = { left: 50, right: 20, top: 20, bottom: 40 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;

  const colors = ['#58a6ff', '#3fb950', '#d29922', '#bc8cff', '#f85149'];

  return (
    <svg viewBox={`0 0 ${width} ${height}`} style={{ width, height }}>
      {/* Grid */}
      {Array.from({ length: 5 }, (_, i) => {
        const y = pad.top + (plotH / 4) * i;
        const val = maxScore * (1 - i / 4);
        return (
          <g key={i}>
            <line x1={pad.left} y1={y} x2={width - pad.right} y2={y}
              stroke="#30363d" strokeWidth={0.5} />
            <text x={pad.left - 6} y={y + 4} textAnchor="end"
              fill="#8b949e" fontSize={10} fontFamily="monospace">
              {val.toFixed(2)}
            </text>
          </g>
        );
      })}

      {/* X labels */}
      {Array.from({ length: maxPoints }, (_, i) => {
        const x = pad.left + (plotW / Math.max(maxPoints - 1, 1)) * i;
        return (
          <text key={i} x={x} y={height - pad.bottom + 16} textAnchor="middle"
            fill="#8b949e" fontSize={10} fontFamily="monospace">
            {i + 1}
          </text>
        );
      })}
      <text x={width / 2} y={height - 4} textAnchor="middle" fill="#8b949e" fontSize={10}>
        Attempt
      </text>

      {/* Lines + dots */}
      {branches.map(([branchId, points], bi) => {
        const color = colors[bi % colors.length];
        const pathD = points.map((p, i) => {
          const x = pad.left + (plotW / Math.max(maxPoints - 1, 1)) * i;
          const y = pad.top + plotH - (p.score / maxScore) * plotH;
          return `${i === 0 ? 'M' : 'L'}${x},${y}`;
        }).join(' ');

        return (
          <g key={branchId}>
            <path d={pathD} fill="none" stroke={color} strokeWidth={2} />
            {points.map((p, i) => {
              const x = pad.left + (plotW / Math.max(maxPoints - 1, 1)) * i;
              const y = pad.top + plotH - (p.score / maxScore) * plotH;
              return <circle key={i} cx={x} cy={y} r={3} fill={color} />;
            })}
            <text x={pad.left + bi * 80} y={pad.top - 4}
              fill={color} fontSize={11}>
              {branchId}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
