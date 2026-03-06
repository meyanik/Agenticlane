/** API client for the AgenticLane dashboard backend. */

const BASE = '/api';

async function fetchJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`API error ${res.status}: ${path}`);
  return res.json() as Promise<T>;
}

async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`API error ${res.status}: ${path}`);
  return res.json() as Promise<T>;
}

import type {
  RunSummary, Manifest, StageInfo, AttemptSummary,
  AttemptDetail, ModelOption, ExampleConfig, StageDescription, ActiveRun,
} from './types';

export const api = {
  // Runs
  listRuns: () => fetchJSON<{ runs: RunSummary[] }>('/runs'),
  getManifest: (id: string) => fetchJSON<Manifest>(`/runs/${id}/manifest`),
  getBranches: (id: string) => fetchJSON<{ branches: Record<string, unknown>; best_branch_id: string }>(`/runs/${id}/branches`),
  getMetrics: (id: string) => fetchJSON<{ branch_scores: Record<string, { stage: string; attempt: number; score: number }[]> }>(`/runs/${id}/metrics`),
  getEvidence: (id: string) => fetchJSON<{ evidence_packs: unknown[] }>(`/runs/${id}/evidence`),
  getRejections: (id: string) => fetchJSON<{ rejections: unknown[] }>(`/runs/${id}/rejections`),

  // New endpoints
  getStages: (id: string) => fetchJSON<{ stages: StageInfo[] }>(`/runs/${id}/stages`),
  getStageAttempts: (id: string, stage: string) => fetchJSON<{ stage: string; attempts: AttemptSummary[] }>(`/runs/${id}/stages/${stage}/attempts`),
  getAttemptDetail: (id: string, stage: string, attempt: number) => fetchJSON<AttemptDetail>(`/runs/${id}/stages/${stage}/attempts/${attempt}`),
  getAgentLog: (id: string) => fetchJSON<{ llm_calls: unknown[]; decisions: unknown[] }>(`/runs/${id}/agents`),
  getPatches: (id: string) => fetchJSON<{ patches: unknown[] }>(`/runs/${id}/patches`),

  // Config
  getModels: () => fetchJSON<{ models: ModelOption[] }>('/config/models'),
  getExamples: () => fetchJSON<{ examples: ExampleConfig[] }>('/config/examples'),
  getStageInfo: () => fetchJSON<StageDescription>('/config/stages'),

  // Run management
  startRun: (config: unknown) => postJSON<{ run_id: string; status: string; pid: number }>('/runs/start', config),
  stopRun: (id: string) => postJSON<{ status: string; run_id: string }>(`/runs/${id}/stop`, {}),
  getActiveRuns: () => fetchJSON<{ active: ActiveRun[] }>('/runs/active'),
  getRunStatus: (id: string) => fetchJSON<{ run_id: string; status: string; error?: string; exit_code?: number }>(`/runs/${id}/status`),
};
