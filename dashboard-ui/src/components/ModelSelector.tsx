/** LLM model dropdown — queries /api/config/models for available options. */

import { useApi } from '../hooks/useApi';
import { api } from '../api';
import type { ModelOption } from '../types';

interface ModelSelectorProps {
  value: string;
  onChange: (model: string) => void;
  label?: string;
}

export function ModelSelector({ value, onChange, label }: ModelSelectorProps) {
  const { data, loading } = useApi(() => api.getModels(), []);
  const models: ModelOption[] = data?.models || [];

  // Group by provider
  const grouped = models.reduce<Record<string, ModelOption[]>>((acc, m) => {
    const key = m.provider || 'other';
    if (!acc[key]) acc[key] = [];
    acc[key].push(m);
    return acc;
  }, {});

  return (
    <div className="model-selector">
      {label && <label className="stat-label">{label}</label>}
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        disabled={loading}
        className="model-select"
      >
        <option value="">-- Select Model --</option>
        {Object.entries(grouped).map(([provider, providerModels]) => (
          <optgroup key={provider} label={provider.toUpperCase()}>
            {providerModels.map(m => (
              <option key={m.id} value={m.id}>{m.label}</option>
            ))}
          </optgroup>
        ))}
      </select>
    </div>
  );
}
