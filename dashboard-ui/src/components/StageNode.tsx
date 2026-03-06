/** Individual pipeline stage node (SVG). */

import { STAGE_LABELS, STATUS_COLORS, STATUS_ICONS, STAGE_DESCRIPTIONS } from '../constants';
import type { StageStatus } from '../types';

interface StageNodeProps {
  stage: string;
  status: StageStatus;
  score?: number | null;
  attempts?: number;
  x: number;
  y: number;
  width: number;
  height: number;
  onClick?: () => void;
}

export function StageNode({ stage, status, attempts, x, y, width, height, onClick }: StageNodeProps) {
  const color = STATUS_COLORS[status] || STATUS_COLORS.pending;
  const icon = STATUS_ICONS[status] || STATUS_ICONS.pending;
  const label = STAGE_LABELS[stage] || stage;
  const desc = STAGE_DESCRIPTIONS[stage] || '';
  const isRunning = status === 'running';

  return (
    <g
      className={`stage-node ${isRunning ? 'stage-running' : ''}`}
      onClick={onClick}
      style={{ cursor: onClick ? 'pointer' : 'default' }}
    >
      <title>{`${label}: ${desc}`}</title>

      {/* Background rect */}
      <rect
        x={x}
        y={y}
        width={width}
        height={height}
        rx={8}
        ry={8}
        fill="var(--surface)"
        stroke={color}
        strokeWidth={status === 'running' ? 2.5 : 1.5}
      />

      {/* Pulse animation for running */}
      {isRunning && (
        <rect
          x={x}
          y={y}
          width={width}
          height={height}
          rx={8}
          ry={8}
          fill="none"
          stroke={color}
          strokeWidth={2}
          opacity={0.4}
        >
          <animate
            attributeName="opacity"
            values="0.4;0;0.4"
            dur="2s"
            repeatCount="indefinite"
          />
          <animate
            attributeName="strokeWidth"
            values="2;6;2"
            dur="2s"
            repeatCount="indefinite"
          />
        </rect>
      )}

      {/* Stage label */}
      <text
        x={x + width / 2}
        y={y + 18}
        textAnchor="middle"
        fill="var(--text)"
        fontSize={11}
        fontWeight={600}
      >
        {label}
      </text>

      {/* Status icon */}
      <text
        x={x + width / 2}
        y={y + 36}
        textAnchor="middle"
        fill={color}
        fontSize={16}
      >
        {icon}
      </text>

      {/* Attempt badge */}
      {attempts !== undefined && attempts > 0 && (
        <text
          x={x + width / 2}
          y={y + 52}
          textAnchor="middle"
          fill="var(--text-dim)"
          fontSize={9}
        >
          {attempts === 1 ? '1 attempt' : `${attempts} attempts`}
        </text>
      )}
    </g>
  );
}
