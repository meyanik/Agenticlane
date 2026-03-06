/** New run page — full config builder with upload/build tabs, info buttons, presets. */

import { useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useApi } from '../hooks/useApi';
import { api } from '../api';
import { ModelSelector } from '../components/ModelSelector';
import { InfoButton } from '../components/InfoButton';
import { CollapsibleSection } from '../components/CollapsibleSection';
import { STAGE_ORDER, STAGE_LABELS, CONFIG_HELP, PRESET_PROFILES } from '../constants';
import type { PresetProfile } from '../constants';
import yaml from 'js-yaml';

/* ---------- helpers ---------- */

function Info({ k }: { k: string }) {
  const h = CONFIG_HELP[k];
  if (!h) return null;
  return <InfoButton title={h.title} content={h.content} />;
}

function Label({ text, k }: { text: string; k: string }) {
  return (
    <div className="form-label-row">
      <label>{text}</label>
      <Info k={k} />
    </div>
  );
}

/* ---------- component ---------- */

// Default LM Studio URL — used when auto-detecting local models.
const LM_STUDIO_DEFAULT_URL = 'http://127.0.0.1:1234/v1';

export function NewRunPage() {
  const navigate = useNavigate();
  const { data: examplesData } = useApi(() => api.getExamples(), []);
  const examples = examplesData?.examples || [];

  // Fetch models list to detect local vs cloud models
  const { data: modelsData } = useApi(() => api.getModels(), []);
  const localModelIds = useMemo(() => {
    const ids = new Set<string>();
    for (const m of modelsData?.models || []) {
      if (m.provider === 'local') ids.add(m.id);
    }
    return ids;
  }, [modelsData]);

  // Tab state
  const [tab, setTab] = useState<'build' | 'upload'>('build');

  // Upload mode
  const [yamlText, setYamlText] = useState('');
  const [yamlError, setYamlError] = useState('');

  // Preset
  const [activePreset, setActivePreset] = useState<string>('Balanced');

  // --- Form state ---
  // Design
  const [designSource, setDesignSource] = useState<'example' | 'custom'>('custom');
  const [selectedExample, setSelectedExample] = useState('');
  const [customConfigPath, setCustomConfigPath] = useState('');
  const [verilogFiles, setVerilogFiles] = useState('');
  const [pdk, setPdk] = useState('sky130A');
  const [clockPeriod, setClockPeriod] = useState('10.0');
  const [clockStrategy, setClockStrategy] = useState<'locked' | 'optimize'>('locked');
  const [flowMode, setFlowMode] = useState<'flat' | 'hierarchical'>('flat');
  // Intent
  const [intentPrompt, setIntentPrompt] = useState('Optimize timing closure while keeping area reasonable.');
  const [timingWeight, setTimingWeight] = useState(0.7);
  // LLM — per-model api_base for mixed local/API
  const [defaultWorker, setDefaultWorker] = useState('');
  const [defaultWorkerApiBase, setDefaultWorkerApiBase] = useState('');
  const [defaultJudge, setDefaultJudge] = useState('');
  const [defaultJudgeApiBase, setDefaultJudgeApiBase] = useState('');
  const [stageOverrides, setStageOverrides] = useState<Record<string, { worker: string; judge: string }>>({});
  const [temperature, setTemperature] = useState(0.0);
  // Flow control
  const [attemptsPerStage, setAttemptsPerStage] = useState(5);
  const [cognitiveRetries, setCognitiveRetries] = useState(3);
  const [deadlockPolicy, setDeadlockPolicy] = useState('auto_relax');
  const [plateauEnabled, setPlateauEnabled] = useState(true);
  const [plateauWindow, setPlateauWindow] = useState(3);
  const [plateauMinDelta, setPlateauMinDelta] = useState(0.01);
  const [humanInTheLoop, setHumanInTheLoop] = useState(false);
  // Parallel
  const [parallelEnabled, setParallelEnabled] = useState(false);
  const [maxBranches, setMaxBranches] = useState(2);
  const [maxJobs, setMaxJobs] = useState(2);
  const [branchPolicy, setBranchPolicy] = useState('best_of_n');
  const [pruneEnabled, setPruneEnabled] = useState(true);
  // Knowledge
  const [ragEnabled, setRagEnabled] = useState(true);
  const [ragTopK, setRagTopK] = useState(5);
  const [ragThreshold, setRagThreshold] = useState(0.35);
  // Action space
  const [permConfigVars, setPermConfigVars] = useState(true);
  const [permSdc, setPermSdc] = useState(true);
  const [permTcl, setPermTcl] = useState(false);
  const [permMacro, setPermMacro] = useState(true);
  const [sdcMode, setSdcMode] = useState('restricted_freeform');
  const [tclMode, setTclMode] = useState('restricted_freeform');
  // Constraints
  const [lockedVars, setLockedVars] = useState('CLOCK_PERIOD');
  const [allowRelaxation, setAllowRelaxation] = useState(true);
  const [maxRelaxationPct, setMaxRelaxationPct] = useState(50);
  // Judging
  const [voteStrategy, setVoteStrategy] = useState('majority');
  const [tieBreaker, setTieBreaker] = useState('fail');
  // Execution & GC
  const [executionMode, setExecutionMode] = useState('local');
  const [toolTimeout, setToolTimeout] = useState(21600);
  const [gcEnabled, setGcEnabled] = useState(true);
  const [gcPolicy, setGcPolicy] = useState('keep_pass_and_tips');
  const [maxDiskGb, setMaxDiskGb] = useState(40);
  const [compressArtifacts, setCompressArtifacts] = useState(true);
  // Initialization
  const [zeroShotEnabled, setZeroShotEnabled] = useState(true);

  // Launch
  const [launching, setLaunching] = useState(false);
  const [launchError, setLaunchError] = useState('');

  /* ---------- clock strategy -> locked_vars sync ---------- */

  const effectiveLockedVars = useMemo(() => {
    const vars = lockedVars.split(',').map(s => s.trim()).filter(Boolean);
    if (clockStrategy === 'locked' && !vars.includes('CLOCK_PERIOD')) {
      return [...vars, 'CLOCK_PERIOD'];
    }
    if (clockStrategy === 'optimize') {
      return vars.filter(v => v !== 'CLOCK_PERIOD');
    }
    return vars;
  }, [lockedVars, clockStrategy]);

  /* ---------- derive llm mode from api_base / model provider ---------- */

  const hasAnyLocalModel = !!(defaultWorkerApiBase || defaultJudgeApiBase || localModelIds.has(defaultWorker) || localModelIds.has(defaultJudge));
  const hasAnyApiModel = (!defaultWorkerApiBase && !localModelIds.has(defaultWorker)) || (!defaultJudgeApiBase && !localModelIds.has(defaultJudge));
  const derivedLlmMode = hasAnyLocalModel && !hasAnyApiModel ? 'local' : hasAnyLocalModel ? 'mixed' : 'api';

  /* ---------- preset application ---------- */

  const applyPreset = (preset: PresetProfile) => {
    setActivePreset(preset.name);
    const v = preset.values as Record<string, unknown>;
    setAttemptsPerStage(v.attemptsPerStage as number);
    setCognitiveRetries(v.cognitiveRetries as number);
    setDeadlockPolicy(v.deadlockPolicy as string);
    setPlateauEnabled(v.plateauEnabled as boolean);
    setPlateauWindow(v.plateauWindow as number);
    setPlateauMinDelta(v.plateauMinDelta as number);
    setHumanInTheLoop(v.humanInTheLoop as boolean);
    setParallelEnabled(v.parallelEnabled as boolean);
    setMaxBranches(v.maxBranches as number);
    setMaxJobs(v.maxJobs as number);
    setBranchPolicy(v.branchPolicy as string);
    setPruneEnabled(v.pruneEnabled as boolean);
    setRagEnabled(v.ragEnabled as boolean);
    setRagTopK(v.ragTopK as number);
    setRagThreshold(v.ragThreshold as number);
    setPermConfigVars(v.permConfigVars as boolean);
    setPermSdc(v.permSdc as boolean);
    setPermTcl(v.permTcl as boolean);
    setPermMacro(v.permMacro as boolean);
    setSdcMode(v.sdcMode as string);
    setTclMode(v.tclMode as string);
    setAllowRelaxation(v.allowRelaxation as boolean);
    setMaxRelaxationPct(v.maxRelaxationPct as number);
    setVoteStrategy(v.voteStrategy as string);
    setTieBreaker(v.tieBreaker as string);
    setGcEnabled(v.gcEnabled as boolean);
    setGcPolicy(v.gcPolicy as string);
    setMaxDiskGb(v.maxDiskGb as number);
    setCompressArtifacts(v.compressArtifacts as boolean);
    setTemperature(v.temperature as number);
    setExecutionMode(v.executionMode as string);
    setToolTimeout(v.toolTimeout as number);
    setZeroShotEnabled(v.zeroShotEnabled as boolean);
  };

  /* ---------- config builder ---------- */

  const buildConfig = () => {
    // Auto-detect local models: if the user selected a model from the "LOCAL"
    // group but didn't manually fill in the API base, we fill it automatically.
    const workerIsLocal = localModelIds.has(defaultWorker);
    const judgeIsLocal = localModelIds.has(defaultJudge);
    const effectiveWorkerApiBase = defaultWorkerApiBase || (workerIsLocal ? LM_STUDIO_DEFAULT_URL : '');
    const effectiveJudgeApiBase = defaultJudgeApiBase || (judgeIsLocal ? LM_STUDIO_DEFAULT_URL : '');

    const anyLocal = !!(effectiveWorkerApiBase || effectiveJudgeApiBase);
    const llmMode = anyLocal ? 'local' : 'api';

    const config: Record<string, unknown> = {
      project: { name: 'dashboard_run', run_id: 'auto' },
      design: { flow_mode: flowMode },
      intent: {
        prompt: intentPrompt,
        weights_hint: { timing: timingWeight, area: +(1 - timingWeight).toFixed(2) },
      },
      initialization: {
        zero_shot: { enabled: zeroShotEnabled },
      },
      flow_control: {
        budgets: {
          physical_attempts_per_stage: attemptsPerStage,
          cognitive_retries_per_attempt: cognitiveRetries,
        },
        deadlock_policy: deadlockPolicy,
        plateau_detection: {
          enabled: plateauEnabled,
          window: plateauWindow,
          min_delta_score: plateauMinDelta,
        },
        ask_human: { enabled: humanInTheLoop },
      },
      parallel: {
        enabled: parallelEnabled,
        max_parallel_branches: maxBranches,
        max_parallel_jobs: maxJobs,
        branch_policy: branchPolicy,
        prune: { enabled: pruneEnabled },
      },
      action_space: {
        permissions: {
          config_vars: permConfigVars,
          sdc: permSdc,
          tcl: permTcl,
          macro_placements: permMacro,
        },
        sdc: { mode: sdcMode },
        tcl: { mode: tclMode },
      },
      constraints: {
        locked_vars: effectiveLockedVars,
        allow_relaxation: allowRelaxation,
        max_relaxation_pct: maxRelaxationPct,
      },
      judging: {
        ensemble: { vote: voteStrategy, tie_breaker: tieBreaker },
      },
      scoring: {
        normalization: { method: 'percent_over_baseline' },
      },
      artifact_gc: {
        enabled: gcEnabled,
        policy: gcPolicy,
        max_run_disk_gb: maxDiskGb,
        compress_pass_artifacts: compressArtifacts,
      },
      llm: {
        mode: llmMode,
        temperature,
        ...(anyLocal ? { api_base: effectiveWorkerApiBase || effectiveJudgeApiBase } : {}),
        models: {
          worker: defaultWorker,
          judge: defaultJudge ? [defaultJudge] : [],
          stage_overrides: Object.fromEntries(
            Object.entries(stageOverrides)
              .filter(([, v]) => v.worker || v.judge)
              .map(([stage, v]) => [stage, {
                ...(v.worker ? { worker: v.worker } : {}),
                ...(v.judge ? { judge: [v.judge] } : {}),
              }])
          ),
        },
      },
      knowledge: {
        enabled: ragEnabled,
        top_k: ragTopK,
        score_threshold: ragThreshold,
      },
      execution: {
        mode: executionMode,
        tool_timeout_seconds: toolTimeout,
      },
    };

    // Hierarchical mode requires modules dict — dashboard has no modules editor,
    // so force flat mode if hierarchical was selected.
    const designObj = config.design as Record<string, unknown>;
    if (flowMode === 'hierarchical') {
      designObj.flow_mode = 'flat';
    }

    // Design source
    if (designSource === 'example' && selectedExample) {
      const ex = examples.find(e => `${e.design}/${e.config_file}` === selectedExample);
      if (ex) designObj.librelane_config_path = ex.config_path;
    } else if (designSource === 'custom') {
      if (customConfigPath) designObj.librelane_config_path = customConfigPath;
      if (pdk) designObj.pdk = pdk;
    }

    return config;
  };

  const configYaml = useMemo(() => {
    try {
      return yaml.dump(buildConfig(), { sortKeys: false, lineWidth: 120 });
    } catch {
      return '# Error generating YAML';
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    flowMode, designSource, selectedExample, customConfigPath, verilogFiles, pdk, clockPeriod, clockStrategy,
    intentPrompt, timingWeight,
    defaultWorker, defaultWorkerApiBase, defaultJudge, defaultJudgeApiBase,
    stageOverrides, temperature,
    attemptsPerStage, cognitiveRetries, deadlockPolicy, plateauEnabled,
    plateauWindow, plateauMinDelta, humanInTheLoop,
    parallelEnabled, maxBranches, maxJobs, branchPolicy, pruneEnabled,
    ragEnabled, ragTopK, ragThreshold,
    permConfigVars, permSdc, permTcl, permMacro, sdcMode, tclMode,
    lockedVars, allowRelaxation, maxRelaxationPct, effectiveLockedVars,
    voteStrategy, tieBreaker,
    executionMode, toolTimeout, gcEnabled, gcPolicy, maxDiskGb, compressArtifacts,
    zeroShotEnabled,
  ]);

  /* ---------- handlers ---------- */

  const handleOverrideChange = (stage: string, role: 'worker' | 'judge', value: string) => {
    setStageOverrides(prev => ({
      ...prev,
      [stage]: { ...prev[stage], [role]: value },
    }));
  };

  const handleLaunch = async (config?: unknown) => {
    setLaunchError('');
    const cfg = config || buildConfig();

    // Validate: config path must be set (unless uploading raw YAML)
    if (!config) {
      const design = (cfg as Record<string, unknown>).design as Record<string, unknown> | undefined;
      if (!design?.librelane_config_path) {
        setLaunchError('LibreLane config path is required. Select an example or enter a custom path.');
        return;
      }
    }

    setLaunching(true);
    try {
      const result = await api.startRun(cfg);
      navigate(`/runs/${result.run_id}/live`);
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Unknown error';
      setLaunchError(`Failed to start run: ${msg}`);
      setLaunching(false);
    }
  };

  const parseYaml = () => {
    try {
      const parsed = yaml.load(yamlText);
      if (!parsed || typeof parsed !== 'object') throw new Error('YAML must be an object');
      setYamlError('');
      return parsed;
    } catch (e) {
      setYamlError(e instanceof Error ? e.message : 'Invalid YAML');
      return null;
    }
  };

  const handleLoadIntoBuilder = () => {
    const parsed = parseYaml();
    if (!parsed) return;
    setTab('build');
    loadConfigIntoForm(parsed as Record<string, unknown>);
  };

  const loadConfigIntoForm = (cfg: Record<string, unknown>) => {
    const get = (path: string) => {
      const parts = path.split('.');
      let v: unknown = cfg;
      for (const p of parts) {
        if (v && typeof v === 'object') v = (v as Record<string, unknown>)[p];
        else return undefined;
      }
      return v;
    };

    // Design
    if (get('design.flow_mode')) setFlowMode(get('design.flow_mode') as 'flat' | 'hierarchical');
    if (get('design.librelane_config_path')) {
      setDesignSource('custom');
      setCustomConfigPath(get('design.librelane_config_path') as string);
    }
    if (get('design.pdk')) setPdk(get('design.pdk') as string);
    if (get('design.clock_period_ns') !== undefined) setClockPeriod(String(get('design.clock_period_ns')));
    const vf = get('design.verilog_files');
    if (Array.isArray(vf)) setVerilogFiles(vf.join(', '));
    // Clock strategy from locked_vars
    const lv = get('constraints.locked_vars');
    if (Array.isArray(lv)) {
      setLockedVars(lv.join(', '));
      setClockStrategy(lv.includes('CLOCK_PERIOD') ? 'locked' : 'optimize');
    }
    // Intent
    if (get('intent.prompt')) setIntentPrompt(get('intent.prompt') as string);
    if (get('intent.weights_hint.timing') !== undefined) setTimingWeight(get('intent.weights_hint.timing') as number);
    // LLM
    if (get('llm.api_base')) {
      const base = get('llm.api_base') as string;
      setDefaultWorkerApiBase(base);
      setDefaultJudgeApiBase(base);
    }
    if (get('llm.temperature') !== undefined) setTemperature(get('llm.temperature') as number);
    if (get('llm.models.worker')) setDefaultWorker(get('llm.models.worker') as string);
    const judges = get('llm.models.judge');
    if (Array.isArray(judges) && judges.length > 0) setDefaultJudge(judges[0] as string);
    else if (typeof judges === 'string') setDefaultJudge(judges);
    // Flow control
    if (get('flow_control.budgets.physical_attempts_per_stage') !== undefined)
      setAttemptsPerStage(get('flow_control.budgets.physical_attempts_per_stage') as number);
    if (get('flow_control.budgets.cognitive_retries_per_attempt') !== undefined)
      setCognitiveRetries(get('flow_control.budgets.cognitive_retries_per_attempt') as number);
    if (get('flow_control.deadlock_policy')) setDeadlockPolicy(get('flow_control.deadlock_policy') as string);
    if (get('flow_control.plateau_detection.enabled') !== undefined) setPlateauEnabled(get('flow_control.plateau_detection.enabled') as boolean);
    if (get('flow_control.plateau_detection.window') !== undefined) setPlateauWindow(get('flow_control.plateau_detection.window') as number);
    if (get('flow_control.plateau_detection.min_delta_score') !== undefined) setPlateauMinDelta(get('flow_control.plateau_detection.min_delta_score') as number);
    if (get('flow_control.ask_human.enabled') !== undefined) setHumanInTheLoop(get('flow_control.ask_human.enabled') as boolean);
    // Parallel
    if (get('parallel.enabled') !== undefined) setParallelEnabled(get('parallel.enabled') as boolean);
    if (get('parallel.max_parallel_branches') !== undefined) setMaxBranches(get('parallel.max_parallel_branches') as number);
    if (get('parallel.max_parallel_jobs') !== undefined) setMaxJobs(get('parallel.max_parallel_jobs') as number);
    if (get('parallel.branch_policy')) setBranchPolicy(get('parallel.branch_policy') as string);
    if (get('parallel.prune.enabled') !== undefined) setPruneEnabled(get('parallel.prune.enabled') as boolean);
    // Knowledge
    if (get('knowledge.enabled') !== undefined) setRagEnabled(get('knowledge.enabled') as boolean);
    if (get('knowledge.top_k') !== undefined) setRagTopK(get('knowledge.top_k') as number);
    if (get('knowledge.score_threshold') !== undefined) setRagThreshold(get('knowledge.score_threshold') as number);
    // Action space
    if (get('action_space.permissions.config_vars') !== undefined) setPermConfigVars(get('action_space.permissions.config_vars') as boolean);
    if (get('action_space.permissions.sdc') !== undefined) setPermSdc(get('action_space.permissions.sdc') as boolean);
    if (get('action_space.permissions.tcl') !== undefined) setPermTcl(get('action_space.permissions.tcl') as boolean);
    if (get('action_space.permissions.macro_placements') !== undefined) setPermMacro(get('action_space.permissions.macro_placements') as boolean);
    if (get('action_space.sdc.mode')) setSdcMode(get('action_space.sdc.mode') as string);
    if (get('action_space.tcl.mode')) setTclMode(get('action_space.tcl.mode') as string);
    // Constraints
    if (get('constraints.allow_relaxation') !== undefined) setAllowRelaxation(get('constraints.allow_relaxation') as boolean);
    if (get('constraints.max_relaxation_pct') !== undefined) setMaxRelaxationPct(get('constraints.max_relaxation_pct') as number);
    // Judging
    if (get('judging.ensemble.vote')) setVoteStrategy(get('judging.ensemble.vote') as string);
    if (get('judging.ensemble.tie_breaker')) setTieBreaker(get('judging.ensemble.tie_breaker') as string);
    // Execution
    if (get('execution.mode')) setExecutionMode(get('execution.mode') as string);
    if (get('execution.tool_timeout_seconds') !== undefined) setToolTimeout(get('execution.tool_timeout_seconds') as number);
    // GC
    if (get('artifact_gc.enabled') !== undefined) setGcEnabled(get('artifact_gc.enabled') as boolean);
    if (get('artifact_gc.policy')) setGcPolicy(get('artifact_gc.policy') as string);
    if (get('artifact_gc.max_run_disk_gb') !== undefined) setMaxDiskGb(get('artifact_gc.max_run_disk_gb') as number);
    if (get('artifact_gc.compress_pass_artifacts') !== undefined) setCompressArtifacts(get('artifact_gc.compress_pass_artifacts') as boolean);
    // Initialization
    if (get('initialization.zero_shot.enabled') !== undefined) setZeroShotEnabled(get('initialization.zero_shot.enabled') as boolean);

    setActivePreset('');
  };

  /* ---------- toggle helper ---------- */

  function Toggle({ value, onChange, labels = ['Enabled', 'Disabled'] }: {
    value: boolean; onChange: (v: boolean) => void; labels?: [string, string];
  }) {
    return (
      <div className="toggle-group">
        <button className={`toggle-btn ${value ? 'active' : ''}`} onClick={() => onChange(true)}>{labels[0]}</button>
        <button className={`toggle-btn ${!value ? 'active' : ''}`} onClick={() => onChange(false)}>{labels[1]}</button>
      </div>
    );
  }

  /* ---------- render ---------- */

  return (
    <div className="new-run-page">
      <nav>
        <a href="/" onClick={e => { e.preventDefault(); navigate('/'); }}>&larr; All Runs</a>
      </nav>

      <h1>New Run</h1>
      <p className="subtitle">Configure and launch an AgenticLane flow</p>

      {/* Tab switch */}
      <div className="config-tabs">
        <button className={`config-tab ${tab === 'build' ? 'active' : ''}`} onClick={() => setTab('build')}>
          Build from Scratch
        </button>
        <button className={`config-tab ${tab === 'upload' ? 'active' : ''}`} onClick={() => setTab('upload')}>
          Upload Config YAML
        </button>
      </div>

      {/* ==================== UPLOAD MODE ==================== */}
      {tab === 'upload' && (
        <div>
          <div className="card">
            <h2>Paste or Upload YAML Config</h2>
            <p className="text-dim" style={{ fontSize: '0.85rem', marginBottom: 12 }}>
              Paste an existing AgenticLane YAML config, or upload a file. You can then load it into the visual builder or launch directly.
            </p>
            <div className="upload-zone">
              <label className="btn" style={{ cursor: 'pointer' }}>
                Choose File
                <input
                  type="file"
                  accept=".yaml,.yml"
                  style={{ display: 'none' }}
                  onChange={e => {
                    const file = e.target.files?.[0];
                    if (!file) return;
                    const reader = new FileReader();
                    reader.onload = ev => {
                      setYamlText(ev.target?.result as string);
                      setYamlError('');
                    };
                    reader.readAsText(file);
                  }}
                />
              </label>
            </div>
            <textarea
              className="yaml-editor"
              value={yamlText}
              onChange={e => { setYamlText(e.target.value); setYamlError(''); }}
              placeholder={'# Paste your AgenticLane config YAML here\nproject:\n  name: my_run\ndesign:\n  flow_mode: flat\n  librelane_config_path: ./config.yaml\nintent:\n  prompt: Optimize timing closure'}
              spellCheck={false}
            />
            {yamlError && <div className="yaml-error">{yamlError}</div>}
            <div style={{ marginTop: 16, display: 'flex', gap: 12 }}>
              <button
                className="btn"
                onClick={handleLoadIntoBuilder}
                disabled={!yamlText.trim()}
              >
                Load into Builder
              </button>
              <button
                className="btn btn-primary"
                onClick={() => {
                  const parsed = parseYaml();
                  if (parsed) handleLaunch(parsed);
                }}
                disabled={launching || !yamlText.trim()}
              >
                {launching ? 'Launching...' : 'Launch Directly'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ==================== BUILD MODE ==================== */}
      {tab === 'build' && (
        <div>
          {/* --- Preset Profiles --- */}
          <div className="card">
            <div className="form-label-row">
              <h2 style={{ margin: 0 }}>Preset Profiles</h2>
              <Info k="presets" />
            </div>
            <p className="text-dim" style={{ fontSize: '0.85rem', margin: '8px 0 12px' }}>
              Select a starting point, then customize individual settings below.
            </p>
            <div className="preset-grid">
              {PRESET_PROFILES.map(p => (
                <div
                  key={p.name}
                  className={`preset-card ${activePreset === p.name ? 'active' : ''}`}
                  onClick={() => applyPreset(p)}
                >
                  <div className="preset-card-name">{p.name}</div>
                  <div className="preset-card-desc">{p.description}</div>
                  <span className="preset-card-tag" style={{ background: p.tagColor, color: '#fff' }}>
                    {p.tag}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* --- Essential: Design --- */}
          <div className="card">
            <h2>Design</h2>
            <div className="form-group">
              <label style={{ marginBottom: 8, display: 'block' }}>Design Source</label>
              <div className="toggle-group">
                <button className={`toggle-btn ${designSource === 'custom' ? 'active' : ''}`} onClick={() => setDesignSource('custom')}>Custom Design</button>
                <button className={`toggle-btn ${designSource === 'example' ? 'active' : ''}`} onClick={() => setDesignSource('example')}>Use Example</button>
              </div>
            </div>

            {designSource === 'example' ? (
              <div className="form-group">
                <Label text="Example Design" k="design.example" />
                <select
                  value={selectedExample}
                  onChange={e => setSelectedExample(e.target.value)}
                  className="form-select"
                >
                  <option value="">-- Select Example --</option>
                  {examples.map(ex => (
                    <option key={`${ex.design}/${ex.config_file}`} value={`${ex.design}/${ex.config_file}`}>
                      {ex.design} / {ex.config_file}
                    </option>
                  ))}
                </select>
              </div>
            ) : (
              <>
                <div className="form-group">
                  <Label text="LibreLane Config Path" k="design.librelane_config_path" />
                  <input
                    type="text"
                    value={customConfigPath}
                    onChange={e => setCustomConfigPath(e.target.value)}
                    className="form-input"
                    placeholder="./config.yaml (path to your LibreLane design config)"
                  />
                </div>
                <div className="form-group">
                  <Label text="Verilog Source Files" k="design.verilog_files" />
                  <input
                    type="text"
                    value={verilogFiles}
                    onChange={e => setVerilogFiles(e.target.value)}
                    className="form-input"
                    placeholder="src/top.v, src/alu.v (comma-separated, optional if in LibreLane config)"
                  />
                </div>
                <div className="form-row">
                  <div className="form-group">
                    <Label text="PDK" k="design.pdk" />
                    <select value={pdk} onChange={e => setPdk(e.target.value)} className="form-select">
                      <option value="sky130A">SkyWater 130nm (sky130A)</option>
                      <option value="gf180mcuD">GlobalFoundries 180nm (gf180mcuD)</option>
                    </select>
                  </div>
                  <div className="form-group">
                    <Label text="Clock Period (ns)" k="design.clock_period" />
                    <input
                      type="number"
                      value={clockPeriod}
                      onChange={e => setClockPeriod(e.target.value)}
                      className="form-input"
                      min={0.1} max={1000} step={0.1}
                      placeholder="10.0"
                    />
                  </div>
                </div>
                <div className="form-group">
                  <Label text="Clock Strategy" k="design.clock_strategy" />
                  <div className="toggle-group">
                    <button className={`toggle-btn ${clockStrategy === 'locked' ? 'active' : ''}`} onClick={() => setClockStrategy('locked')}>Lock Period</button>
                    <button className={`toggle-btn ${clockStrategy === 'optimize' ? 'active' : ''}`} onClick={() => setClockStrategy('optimize')}>Let Agents Optimize</button>
                  </div>
                  {clockStrategy === 'optimize' && (
                    <p className="text-dim" style={{ fontSize: '0.82rem', marginTop: 6 }}>
                      Agents will use {clockPeriod}ns as a starting point but may push for a tighter (faster) clock if the design allows it.
                      CLOCK_PERIOD will be removed from locked variables.
                    </p>
                  )}
                  {clockStrategy === 'locked' && (
                    <p className="text-dim" style={{ fontSize: '0.82rem', marginTop: 6 }}>
                      Agents will optimize the design to meet {clockPeriod}ns but will not change the clock period itself.
                    </p>
                  )}
                </div>
              </>
            )}

            <div className="form-group">
              <Label text="Flow Mode" k="design.flow_mode" />
              <div className="toggle-group">
                <button className={`toggle-btn ${flowMode === 'flat' ? 'active' : ''}`} onClick={() => setFlowMode('flat')}>Flat</button>
                <button className={`toggle-btn ${flowMode === 'hierarchical' ? 'active' : ''}`} onClick={() => setFlowMode('hierarchical')}>Hierarchical</button>
              </div>
            </div>
          </div>

          {/* --- Essential: Intent --- */}
          <div className="card">
            <h2>Intent</h2>
            <div className="intent-callout">
              Agents read this prompt verbatim at every stage. Be specific about your optimization goals.
            </div>
            <div className="form-group">
              <Label text="Optimization Prompt" k="intent.prompt" />
              <textarea
                value={intentPrompt}
                onChange={e => setIntentPrompt(e.target.value)}
                className="form-textarea"
                rows={3}
                placeholder='e.g., "Minimize timing violations, target WNS > -0.1ns, keep utilization under 70%"'
              />
            </div>
            <div className="form-group">
              <Label
                text={`Timing vs Area (timing: ${(timingWeight * 100).toFixed(0)}%, area: ${((1 - timingWeight) * 100).toFixed(0)}%)`}
                k="intent.weights_hint.timing"
              />
              <input
                type="range" min={0} max={1} step={0.1}
                value={timingWeight}
                onChange={e => setTimingWeight(parseFloat(e.target.value))}
                className="form-range"
              />
            </div>
          </div>

          {/* --- Essential: Models --- */}
          <div className="card">
            <h2>Models</h2>
            <p className="text-dim" style={{ fontSize: '0.85rem', marginBottom: 12 }}>
              You can mix local and API models. Leave API Base URL blank for cloud API models, or enter a local server URL (e.g., http://127.0.0.1:1234/v1) for locally-hosted models.
              {derivedLlmMode === 'mixed' && (
                <span style={{ color: 'var(--accent)', fontWeight: 600 }}> Currently using mixed mode (local + API).</span>
              )}
            </p>

            {/* Worker */}
            <div className="form-row">
              <div className="form-group">
                <Label text="Default Worker" k="llm.models.worker" />
                <ModelSelector value={defaultWorker} onChange={setDefaultWorker} />
              </div>
              <div className="form-group">
                <Label text="Worker API Base (blank = cloud API)" k="llm.api_base" />
                <input
                  type="text"
                  value={defaultWorkerApiBase}
                  onChange={e => setDefaultWorkerApiBase(e.target.value)}
                  className="form-input"
                  placeholder="blank = cloud API, or http://127.0.0.1:1234/v1"
                />
              </div>
            </div>

            {/* Judge */}
            <div className="form-row">
              <div className="form-group">
                <Label text="Default Judge" k="llm.models.judge" />
                <ModelSelector value={defaultJudge} onChange={setDefaultJudge} />
              </div>
              <div className="form-group">
                <Label text="Judge API Base (blank = cloud API)" k="llm.api_base" />
                <input
                  type="text"
                  value={defaultJudgeApiBase}
                  onChange={e => setDefaultJudgeApiBase(e.target.value)}
                  className="form-input"
                  placeholder="blank = cloud API, or http://127.0.0.1:1234/v1"
                />
              </div>
            </div>

            <h3>Per-Stage Overrides <Info k="llm.models.stage_overrides" /></h3>
            <p className="text-dim" style={{ fontSize: '0.85rem', marginBottom: 12 }}>
              Leave blank to use the default model. Assign different models to specific stages.
            </p>
            <table className="stage-model-table">
              <thead>
                <tr><th>Stage</th><th>Worker Model</th><th>Judge Model</th></tr>
              </thead>
              <tbody>
                {STAGE_ORDER.map(stage => (
                  <tr key={stage}>
                    <td><strong>{STAGE_LABELS[stage]}</strong></td>
                    <td><ModelSelector value={stageOverrides[stage]?.worker || ''} onChange={v => handleOverrideChange(stage, 'worker', v)} /></td>
                    <td><ModelSelector value={stageOverrides[stage]?.judge || ''} onChange={v => handleOverrideChange(stage, 'judge', v)} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* ==================== ADVANCED (COLLAPSED) ==================== */}

          {/* --- Flow Control --- */}
          <CollapsibleSection title="Flow Control" badge="Advanced">
            <div className="form-row">
              <div className="form-group">
                <Label text="Attempts per Stage" k="flow_control.budgets.physical_attempts_per_stage" />
                <input
                  type="number" min={1} max={20}
                  value={attemptsPerStage}
                  onChange={e => setAttemptsPerStage(parseInt(e.target.value) || 5)}
                  className="form-input"
                />
              </div>
              <div className="form-group">
                <Label text="Cognitive Retries" k="flow_control.budgets.cognitive_retries_per_attempt" />
                <input
                  type="number" min={0} max={10}
                  value={cognitiveRetries}
                  onChange={e => setCognitiveRetries(parseInt(e.target.value) || 3)}
                  className="form-input"
                />
              </div>
            </div>
            <div className="form-row">
              <div className="form-group">
                <Label text="Deadlock Policy" k="flow_control.deadlock_policy" />
                <select value={deadlockPolicy} onChange={e => setDeadlockPolicy(e.target.value)} className="form-select">
                  <option value="auto_relax">Auto Relax</option>
                  <option value="ask_human">Ask Human</option>
                  <option value="stop">Stop</option>
                </select>
              </div>
              <div className="form-group">
                <Label text="Human-in-the-Loop" k="flow_control.ask_human.enabled" />
                <Toggle value={humanInTheLoop} onChange={setHumanInTheLoop} />
              </div>
            </div>
            <div className="form-row">
              <div className="form-group">
                <Label text="Plateau Detection" k="flow_control.plateau_detection.enabled" />
                <Toggle value={plateauEnabled} onChange={setPlateauEnabled} />
              </div>
              {plateauEnabled && (
                <div className="form-group">
                  <Label text="Plateau Window" k="flow_control.plateau_detection.window" />
                  <input
                    type="number" min={1} max={10}
                    value={plateauWindow}
                    onChange={e => setPlateauWindow(parseInt(e.target.value) || 3)}
                    className="form-input"
                  />
                </div>
              )}
            </div>
            {plateauEnabled && (
              <div className="form-group">
                <Label text="Plateau Min Delta" k="flow_control.plateau_detection.min_delta_score" />
                <input
                  type="number" min={0} max={1} step={0.005}
                  value={plateauMinDelta}
                  onChange={e => setPlateauMinDelta(parseFloat(e.target.value) || 0.01)}
                  className="form-input"
                  style={{ maxWidth: 200 }}
                />
              </div>
            )}
            <div className="form-group">
              <Label text="Zero-Shot Initialization" k="initialization.zero_shot.enabled" />
              <Toggle value={zeroShotEnabled} onChange={setZeroShotEnabled} />
            </div>
            <div className="form-group">
              <Label text="Temperature" k="llm.temperature" />
              <input
                type="number" min={0} max={2} step={0.1}
                value={temperature}
                onChange={e => setTemperature(parseFloat(e.target.value) || 0)}
                className="form-input"
                style={{ maxWidth: 200 }}
              />
            </div>
          </CollapsibleSection>

          {/* --- Parallel Branches --- */}
          <CollapsibleSection title="Parallel Branches" badge="Advanced">
            <div className="form-row">
              <div className="form-group">
                <Label text="Parallel Exploration" k="parallel.enabled" />
                <Toggle value={parallelEnabled} onChange={setParallelEnabled} />
              </div>
              {parallelEnabled && (
                <div className="form-group">
                  <Label text="Branch Policy" k="parallel.branch_policy" />
                  <select value={branchPolicy} onChange={e => setBranchPolicy(e.target.value)} className="form-select">
                    <option value="best_of_n">Best of N</option>
                    <option value="pareto">Pareto</option>
                  </select>
                </div>
              )}
            </div>
            {parallelEnabled && (
              <>
                <div className="form-row">
                  <div className="form-group">
                    <Label text="Max Branches" k="parallel.max_parallel_branches" />
                    <input
                      type="number" min={1} max={8}
                      value={maxBranches}
                      onChange={e => setMaxBranches(parseInt(e.target.value) || 2)}
                      className="form-input"
                    />
                  </div>
                  <div className="form-group">
                    <Label text="Max Parallel Jobs" k="parallel.max_parallel_jobs" />
                    <input
                      type="number" min={1} max={8}
                      value={maxJobs}
                      onChange={e => setMaxJobs(Math.min(parseInt(e.target.value) || 1, maxBranches))}
                      className="form-input"
                    />
                  </div>
                </div>
                <div className="form-group">
                  <Label text="Branch Pruning" k="parallel.prune.enabled" />
                  <Toggle value={pruneEnabled} onChange={setPruneEnabled} />
                </div>
              </>
            )}
          </CollapsibleSection>

          {/* --- RAG Knowledge --- */}
          <CollapsibleSection title="RAG Knowledge Base" badge="Advanced">
            <div className="form-group">
              <Label text="RAG Knowledge Base" k="knowledge.enabled" />
              <Toggle value={ragEnabled} onChange={setRagEnabled} />
            </div>
            {ragEnabled && (
              <div className="form-row">
                <div className="form-group">
                  <Label text="Top-K Results" k="knowledge.top_k" />
                  <input
                    type="number" min={1} max={20}
                    value={ragTopK}
                    onChange={e => setRagTopK(parseInt(e.target.value) || 5)}
                    className="form-input"
                  />
                </div>
                <div className="form-group">
                  <Label text="Score Threshold" k="knowledge.score_threshold" />
                  <input
                    type="number" min={0} max={1} step={0.05}
                    value={ragThreshold}
                    onChange={e => setRagThreshold(parseFloat(e.target.value) || 0.35)}
                    className="form-input"
                  />
                </div>
              </div>
            )}
          </CollapsibleSection>

          {/* --- Action Space & Constraints --- */}
          <CollapsibleSection title="Action Space & Constraints" badge="Advanced">
            <h3>Agent Permissions</h3>
            <div className="grid grid-2">
              <div className="form-group">
                <Label text="Config Variables" k="action_space.permissions.config_vars" />
                <Toggle value={permConfigVars} onChange={setPermConfigVars} />
              </div>
              <div className="form-group">
                <Label text="SDC Constraints" k="action_space.permissions.sdc" />
                <Toggle value={permSdc} onChange={setPermSdc} />
              </div>
              <div className="form-group">
                <Label text="Tcl Hooks" k="action_space.permissions.tcl" />
                <Toggle value={permTcl} onChange={setPermTcl} />
              </div>
              <div className="form-group">
                <Label text="Macro Placements" k="action_space.permissions.macro_placements" />
                <Toggle value={permMacro} onChange={setPermMacro} />
              </div>
            </div>
            {permSdc && (
              <div className="form-group">
                <Label text="SDC Mode" k="action_space.sdc.mode" />
                <select value={sdcMode} onChange={e => setSdcMode(e.target.value)} className="form-select">
                  <option value="templated">Templated (Safe)</option>
                  <option value="restricted_freeform">Restricted Freeform</option>
                  <option value="expert_freeform">Expert Freeform</option>
                </select>
              </div>
            )}
            {permTcl && (
              <div className="form-group">
                <Label text="Tcl Mode" k="action_space.tcl.mode" />
                <select value={tclMode} onChange={e => setTclMode(e.target.value)} className="form-select">
                  <option value="restricted_freeform">Restricted Freeform</option>
                  <option value="expert_freeform">Expert Freeform</option>
                </select>
              </div>
            )}
            <h3>Constraints</h3>
            <div className="form-group">
              <Label text="Locked Variables (comma-separated)" k="constraints.locked_vars" />
              <input
                type="text"
                value={lockedVars}
                onChange={e => setLockedVars(e.target.value)}
                className="form-input"
                placeholder="CLOCK_PERIOD, DIE_AREA"
              />
              {clockStrategy === 'optimize' && lockedVars.includes('CLOCK_PERIOD') && (
                <p className="text-dim" style={{ fontSize: '0.82rem', marginTop: 4, color: 'var(--yellow)' }}>
                  Note: Clock Strategy is set to "Let Agents Optimize" — CLOCK_PERIOD will be automatically removed from locked vars.
                </p>
              )}
            </div>
            <div className="form-row">
              <div className="form-group">
                <Label text="Allow Relaxation" k="constraints.allow_relaxation" />
                <Toggle value={allowRelaxation} onChange={setAllowRelaxation} />
              </div>
              {allowRelaxation && (
                <div className="form-group">
                  <Label text="Max Relaxation %" k="constraints.max_relaxation_pct" />
                  <input
                    type="number" min={0} max={100}
                    value={maxRelaxationPct}
                    onChange={e => setMaxRelaxationPct(parseInt(e.target.value) || 0)}
                    className="form-input"
                  />
                </div>
              )}
            </div>
          </CollapsibleSection>

          {/* --- Judging & Scoring --- */}
          <CollapsibleSection title="Judging & Scoring" badge="Advanced">
            <div className="form-row">
              <div className="form-group">
                <Label text="Vote Strategy" k="judging.ensemble.vote" />
                <select value={voteStrategy} onChange={e => setVoteStrategy(e.target.value)} className="form-select">
                  <option value="majority">Majority</option>
                  <option value="unanimous">Unanimous</option>
                </select>
              </div>
              <div className="form-group">
                <Label text="Tie Breaker" k="judging.ensemble.tie_breaker" />
                <select value={tieBreaker} onChange={e => setTieBreaker(e.target.value)} className="form-select">
                  <option value="fail">Fail (Strict)</option>
                  <option value="pass">Pass (Lenient)</option>
                </select>
              </div>
            </div>
          </CollapsibleSection>

          {/* --- Execution & GC --- */}
          <CollapsibleSection title="Execution & Artifact GC" badge="Advanced">
            <div className="form-row">
              <div className="form-group">
                <Label text="Execution Mode" k="execution.mode" />
                <select value={executionMode} onChange={e => setExecutionMode(e.target.value)} className="form-select">
                  <option value="local">Local (Nix)</option>
                  <option value="docker">Docker</option>
                </select>
              </div>
              <div className="form-group">
                <Label text="Tool Timeout (seconds)" k="execution.tool_timeout_seconds" />
                <input
                  type="number" min={60} max={86400}
                  value={toolTimeout}
                  onChange={e => setToolTimeout(parseInt(e.target.value) || 21600)}
                  className="form-input"
                />
              </div>
            </div>
            <div className="form-row">
              <div className="form-group">
                <Label text="Artifact GC" k="artifact_gc.enabled" />
                <Toggle value={gcEnabled} onChange={setGcEnabled} />
              </div>
              {gcEnabled && (
                <div className="form-group">
                  <Label text="GC Policy" k="artifact_gc.policy" />
                  <select value={gcPolicy} onChange={e => setGcPolicy(e.target.value)} className="form-select">
                    <option value="keep_pass_and_tips">Keep Pass + Tips</option>
                    <option value="keep_all">Keep All</option>
                    <option value="keep_none">Keep None</option>
                  </select>
                </div>
              )}
            </div>
            {gcEnabled && (
              <div className="form-row">
                <div className="form-group">
                  <Label text="Max Disk (GB)" k="artifact_gc.max_run_disk_gb" />
                  <input
                    type="number" min={1} max={500}
                    value={maxDiskGb}
                    onChange={e => setMaxDiskGb(parseInt(e.target.value) || 40)}
                    className="form-input"
                  />
                </div>
                <div className="form-group">
                  <Label text="Compress Artifacts" k="artifact_gc.compress_pass_artifacts" />
                  <Toggle value={compressArtifacts} onChange={setCompressArtifacts} />
                </div>
              </div>
            )}
          </CollapsibleSection>

          {/* --- Config Preview --- */}
          <CollapsibleSection title="Config Preview" badge="YAML" defaultOpen={false}>
            <pre className="config-preview">{configYaml}</pre>
          </CollapsibleSection>

          {/* --- Launch --- */}
          <div className="launch-section">
            {launchError && (
              <div className="card" style={{ borderColor: 'var(--red)', background: 'rgba(248,81,73,0.08)', marginBottom: 16 }}>
                <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all', fontSize: '0.85rem', color: 'var(--red)', margin: 0 }}>
                  {launchError}
                </pre>
              </div>
            )}
            <button
              className="btn btn-primary btn-large"
              onClick={() => handleLaunch()}
              disabled={launching}
            >
              {launching ? 'Launching...' : 'Launch Run'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
