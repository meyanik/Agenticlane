/** Filter controls for the Agent Logs page — role toggles, stage dropdown, search. */

import { AGENT_COLORS, AGENT_ROLE_LABELS, STAGE_ORDER, STAGE_LABELS } from '../constants';
import type { AgentRole } from '../types/logs';

const ROLES: AgentRole[] = ['worker', 'judge', 'master', 'rag', 'execution'];

const ROLE_NAMES: Record<string, string> = {
  worker: 'Worker',
  judge: 'Judge',
  master: 'Master',
  rag: 'RAG',
  execution: 'Execution',
};

interface LogFiltersProps {
  activeRoles: Set<AgentRole>;
  onToggleRole: (role: AgentRole) => void;
  selectedStage: string;
  onStageChange: (stage: string) => void;
  searchText: string;
  onSearchChange: (text: string) => void;
  autoScroll: boolean;
  onAutoScrollChange: (v: boolean) => void;
  isLive: boolean;
}

export function LogFilters({
  activeRoles,
  onToggleRole,
  selectedStage,
  onStageChange,
  searchText,
  onSearchChange,
  autoScroll,
  onAutoScrollChange,
  isLive,
}: LogFiltersProps) {
  return (
    <div className="log-filters">
      <div className="log-filters-roles">
        {ROLES.map(role => {
          const active = activeRoles.has(role);
          return (
            <button
              key={role}
              className={`log-role-btn ${active ? 'active' : ''}`}
              style={{
                borderColor: AGENT_COLORS[role],
                background: active ? AGENT_COLORS[role] + '22' : 'transparent',
                color: active ? AGENT_COLORS[role] : 'var(--text-dim)',
              }}
              onClick={() => onToggleRole(role)}
              title={`${active ? 'Hide' : 'Show'} ${ROLE_NAMES[role]} entries`}
            >
              <span className="log-role-badge" style={{ background: AGENT_COLORS[role] }}>
                {AGENT_ROLE_LABELS[role]}
              </span>
              {ROLE_NAMES[role]}
            </button>
          );
        })}
      </div>

      <div className="log-filters-controls">
        <select
          className="log-stage-select"
          value={selectedStage}
          onChange={e => onStageChange(e.target.value)}
        >
          <option value="">All Stages</option>
          {STAGE_ORDER.map(s => (
            <option key={s} value={s}>{STAGE_LABELS[s]}</option>
          ))}
        </select>

        <input
          className="log-search"
          type="text"
          placeholder="Search logs..."
          value={searchText}
          onChange={e => onSearchChange(e.target.value)}
        />

        {isLive && (
          <label className="log-autoscroll">
            <input
              type="checkbox"
              checked={autoScroll}
              onChange={e => onAutoScrollChange(e.target.checked)}
            />
            Auto-scroll
          </label>
        )}
      </div>
    </div>
  );
}
