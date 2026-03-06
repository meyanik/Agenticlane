/** 10-stage SVG pipeline visualization - the centerpiece component. */

import { STAGE_ORDER } from '../constants';
import type { StageInfo, StageStatus } from '../types';
import { StageNode } from './StageNode';

interface PipelineProps {
  stages: StageInfo[];
  onStageClick?: (stage: string) => void;
  compact?: boolean;
}

/**
 * Layout: two rows of 5, connected by arrows.
 *
 *   SYNTH -> FLOORPLAN -> PDN -> PLACE_GLOBAL -> PLACE_DETAILED
 *                                                       |
 *   SIGNOFF <- FINISH <- ROUTE_DETAILED <- ROUTE_GLOBAL <- CTS
 */
export function Pipeline({ stages, onStageClick, compact }: PipelineProps) {
  const stageMap = new Map(stages.map(s => [s.stage, s]));

  const nodeW = compact ? 90 : 120;
  const nodeH = compact ? 46 : 60;
  const gapX = compact ? 12 : 20;
  const gapY = compact ? 30 : 50;
  const arrowLen = gapX;

  const totalW = 5 * nodeW + 4 * gapX + 2 * arrowLen;
  const totalH = 2 * nodeH + gapY + 30;

  // Top row: stages 0-4 (left to right)
  const topRow = STAGE_ORDER.slice(0, 5);
  // Bottom row: stages 5-9 (right to left for visual flow)
  const bottomRow = [...STAGE_ORDER.slice(5)].reverse();

  function getPos(row: number, col: number) {
    const x = 10 + col * (nodeW + gapX);
    const y = 10 + row * (nodeH + gapY);
    return { x, y };
  }

  function arrow(x1: number, y1: number, x2: number, y2: number, animated = false) {
    const key = `${x1}-${y1}-${x2}-${y2}`;
    return (
      <line
        key={key}
        x1={x1} y1={y1} x2={x2} y2={y2}
        stroke="var(--border)"
        strokeWidth={1.5}
        markerEnd="url(#arrowhead)"
        strokeDasharray={animated ? '6 3' : undefined}
      >
        {animated && (
          <animate
            attributeName="stroke-dashoffset"
            values="9;0"
            dur="0.5s"
            repeatCount="indefinite"
          />
        )}
      </line>
    );
  }

  const arrows: React.ReactNode[] = [];

  // Top row arrows (left to right)
  for (let i = 0; i < 4; i++) {
    const from = getPos(0, i);
    const to = getPos(0, i + 1);
    const stage = stageMap.get(topRow[i]);
    const animated = stage?.status === 'passed' || stage?.status === 'executed';
    arrows.push(arrow(from.x + nodeW, from.y + nodeH / 2, to.x, to.y + nodeH / 2, animated));
  }

  // Vertical connector (top-right to bottom-right)
  const trPos = getPos(0, 4);
  const brPos = getPos(1, 4);
  const topRightStage = stageMap.get(topRow[4]);
  arrows.push(arrow(
    trPos.x + nodeW / 2, trPos.y + nodeH,
    brPos.x + nodeW / 2, brPos.y,
    topRightStage?.status === 'passed' || topRightStage?.status === 'executed',
  ));

  // Bottom row arrows (right to left)
  for (let i = 0; i < 4; i++) {
    const from = getPos(1, 4 - i);
    const to = getPos(1, 3 - i);
    const stage = stageMap.get(bottomRow[i]);
    const animated = stage?.status === 'passed' || stage?.status === 'executed';
    arrows.push(arrow(from.x, from.y + nodeH / 2, to.x + nodeW, to.y + nodeH / 2, animated));
  }

  return (
    <svg
      viewBox={`0 0 ${totalW + 20} ${totalH}`}
      className="pipeline-svg"
      style={{ width: '100%', maxWidth: compact ? 600 : 900, height: 'auto' }}
    >
      <defs>
        <marker
          id="arrowhead"
          markerWidth="8"
          markerHeight="6"
          refX="8"
          refY="3"
          orient="auto"
        >
          <polygon points="0 0, 8 3, 0 6" fill="var(--border)" />
        </marker>
      </defs>

      {arrows}

      {/* Top row */}
      {topRow.map((stage, i) => {
        const info = stageMap.get(stage);
        const pos = getPos(0, i);
        return (
          <StageNode
            key={stage}
            stage={stage}
            status={(info?.status as StageStatus) || 'pending'}
            score={info?.best_score}
            attempts={info?.attempts_count}
            x={pos.x}
            y={pos.y}
            width={nodeW}
            height={nodeH}
            onClick={onStageClick ? () => onStageClick(stage) : undefined}
          />
        );
      })}

      {/* Bottom row (reversed visually) */}
      {bottomRow.map((stage, i) => {
        const info = stageMap.get(stage);
        const pos = getPos(1, 4 - i);
        return (
          <StageNode
            key={stage}
            stage={stage}
            status={(info?.status as StageStatus) || 'pending'}
            score={info?.best_score}
            attempts={info?.attempts_count}
            x={pos.x}
            y={pos.y}
            width={nodeW}
            height={nodeH}
            onClick={onStageClick ? () => onStageClick(stage) : undefined}
          />
        );
      })}
    </svg>
  );
}
