/** Metric display card with optional tooltip for students. */

import { Tooltip } from './Tooltip';

interface MetricsCardProps {
  label: string;
  value: string | number | null;
  unit?: string;
  tooltip?: string;
  trend?: 'up' | 'down' | 'neutral';
}

const TREND_SYMBOLS: Record<string, string> = {
  up: '\u2191',    // up arrow
  down: '\u2193',  // down arrow
  neutral: '\u2014', // em dash
};

const TREND_COLORS: Record<string, string> = {
  up: 'var(--green)',
  down: 'var(--red)',
  neutral: 'var(--text-dim)',
};

export function MetricsCard({ label, value, unit, tooltip, trend }: MetricsCardProps) {
  const displayValue = value != null
    ? typeof value === 'number'
      ? Number.isInteger(value) ? String(value) : value.toFixed(3)
      : String(value)
    : '\u2014';

  return (
    <div className="card metrics-card">
      <div className="stat-label">
        {label}
        {tooltip && <Tooltip text={tooltip} />}
      </div>
      <div className="stat-value">
        {displayValue}
        {unit && <span className="stat-unit">{unit}</span>}
        {trend && (
          <span className="stat-trend" style={{ color: TREND_COLORS[trend] }}>
            {TREND_SYMBOLS[trend]}
          </span>
        )}
      </div>
    </div>
  );
}
