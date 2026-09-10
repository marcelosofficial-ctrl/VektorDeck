import { useEffect, useMemo, useState } from 'react';

type ModelFile = { path: string; name: string; size_bytes: number; kind: 'model' | 'projector' | 'checkpoint' | 'unknown' };
type Health = { status: string; version: string; database: string };
type Runtime = { id: string; label: string; configured: boolean; exists: boolean; path: string | null; launchable: boolean; running: boolean; pid: number | null };
type Profile = { id: number; name: string; runtime_id: string; model_path: string; projector_path: string | null; context_size: number; gpu_layers: number; host: string; port: number; extra_args: string[]; is_default: boolean };
type Telemetry = {
  timestamp: number;
  platform: string;
  cpu: { utilization_percent: number | null; logical_processors: number | null };
  memory: { total_bytes: number | null; used_bytes: number | null; percent: number | null };
  gpu: { name: string | null; utilization_percent: number | null; vram_used_bytes: number | null; vram_total_bytes: number | null; source: string | null };
};
type HistoryPoint = { cpu: number; ram: number; gpu: number; vram: number };
type LlamaHealth = {
  online: boolean;
  latency_ms: number | null;
  models: unknown[];
  active_profile_match?: boolean;
  total_slots?: number | null;
  model_path?: string | null;
  modalities?: unknown;
  build_info?: unknown;
};
type Benchmark = {
  id: number; profile_id: number; profile_name: string; model_path: string; elapsed_seconds: number;
  prompt_tokens: number | null; completion_tokens: number | null; tokens_per_second: number | null;
  server_tokens_per_second: number | null; created_at: string; response_preview?: string;
};
type LabSummary = { profile: Profile; runs: number; average: number; best: number };
type ProfileSummary = { profile: Profile; runs: number; average: number; best: number };

const DEFAULT_PROFILE_NAME = 'Qwen local 65K';
const LAB_PROFILE_NAMES = ['Qwen vision 65K P1', 'Qwen text-only 65K P1', 'Qwen text-only 8K P1'];
const gb = (bytes: number) => `${(bytes / 1024 ** 3).toFixed(2)} GB`;
const percent = (value: number | null | undefined) => value == null ? '—' : `${value.toFixed(1)}%`;
const bytesLabel = (value: number | null | undefined) => value == null ? '—' : gb(value);
const clamp = (value: number | null | undefined) => Math.min(Math.max(value ?? 0, 0), 100);
const loadState = (value: number | null | undefined) => value == null ? 'UNKNOWN' : value >= 85 ? 'HEAVY' : value >= 45 ? 'ACTIVE' : 'CALM';
const sleep = (ms: number) => new Promise(resolve => window.setTimeout(resolve, ms));
const benchmarkSpeed = (run: Benchmark) => Number(run.server_tokens_per_second ?? run.tokens_per_second ?? 0);
const localTimestamp = (value: string) => {
  const normalized = value.includes('T') ? value : value.replace(' ', 'T');
  const utc = /Z$|[+-]\d\d:\d\d$/.test(normalized) ? normalized : `${normalized}Z`;
  const date = new Date(utc);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
};
const isLabProfile = (profile: Profile) => LAB_PROFILE_NAMES.includes(profile.name) || /\bP1\b/i.test(profile.name);
const profileLabel = (profile: Profile) => `${profile.name} · ${profile.context_size.toLocaleString()} ctx · ${profile.projector_path ? 'vision' : 'text'} · ngl ${profile.gpu_layers}`;
const compactBuildInfo = (value: unknown) => {
  if (value == null) return 'build details unavailable';
  if (typeof value === 'string') return value;
  try { return JSON.stringify(value); } catch { return String(value); }
};

function parallelOneArgs(args: string[]) {
  const result: string[] = [];
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (arg === '--parallel' || arg === '-np') { index += 1; continue; }
    if (arg.startsWith('--parallel=')) continue;
    result.push(arg);
  }
  result.push('--parallel', '1');
  return result;
}

function Sparkline({ values }: { values: number[] }) {
  if (values.length < 2) return <div className="sparkline sparklineEmpty" />;
  const width = 220, height = 48;
  const points = values.map((value, index) => {
    const x = (index / (values.length - 1)) * width;
    const y = height - (clamp(value) / 100) * height;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  return <svg className="sparkline" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-hidden="true"><polyline points={points} vectorEffect="non-scaling-stroke" /></svg>;
}

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [runtimes, setRuntimes] = useState<Runtime[]>([]);
  const [models, setModels] = useState<ModelFile[]>([]);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [telemetry, setTelemetry] = useState<Telemetry | null>(null);
  const [history, setHistory] = useState<HistoryPoint[]>([]);
  const [selectedProfile, setSelectedProfile] = useState<number | null>(null);
  const [llamaHealth, setLlamaHealth] = useState<LlamaHealth | null>(null);
  const [benchmarks, setBenchmarks] = useState<Benchmark[]>([]);
  const [scanning, setScanning] = useState(false);
  const [busyRuntime, setBusyRuntime] = useState<string | null>(null);
  const [workspaceBusy, setWorkspaceBusy] = useState(false);
  const [benchmarkBusy, setBenchmarkBusy] = useState(false);
  const [labBusy, setLabBusy] = useState(false);
  const [labProgress, setLabProgress] = useState('');
  const [message, setMessage] = useState('Ready when you are.');

  function acceptTelemetry(snapshot: Telemetry) {
    setTelemetry(snapshot);
    const vramPercent = snapshot.gpu.vram_used_bytes != null && snapshot.gpu.vram_total_bytes
      ? snapshot.gpu.vram_used_bytes / snapshot.gpu.vram_total_bytes * 100 : 0;
    setHistory(current => [...current, {
      cpu: clamp(snapshot.cpu.utilization_percent), ram: clamp(snapshot.memory.percent),
      gpu: clamp(snapshot.gpu.utilization_percent), vram: clamp(vramPercent),
    }].slice(-30));
  }

  async function refresh() {
    const [h, r, m, p, t, b] = await Promise.all([
      fetch('/api/health').then(x => x.json()), fetch('/api/runtimes').then(x => x.json()),
      fetch('/api/models').then(x => x.json()), fetch('/api/profiles').then(x => x.json()),
      fetch('/api/telemetry').then(x => x.json()), fetch('/api/benchmarks?limit=50').then(x => x.json()),
    ]);
    setHealth(h); setRuntimes(r); setModels(m); setProfiles(p); acceptTelemetry(t); setBenchmarks(b);
    setSelectedProfile(current => {
      if (current != null && p.some((profile: Profile) => profile.id === current)) return current;
      return p.find((profile: Profile) => profile.is_default)?.id ?? p[0]?.id ?? null;
    });
  }

  async function refreshTelemetry() {
    try {
      const response = await fetch('/api/telemetry');
      if (response.ok) acceptTelemetry(await response.json());
    } catch { /* retain last good sample */ }
  }

  async function refreshRuntimes() {
    try {
      const response = await fetch('/api/runtimes');
      if (response.ok) setRuntimes(await response.json());
    } catch { /* backend may be restarting */ }
  }

  async function checkHealthFor(profileId: number | null) {
    if (!profileId) { setLlamaHealth(null); return; }
    try {
      const response = await fetch(`/api/llama/health/${profileId}`);
      if (response.ok) setLlamaHealth(await response.json());
    } catch { setLlamaHealth({ online: false, latency_ms: null, models: [] }); }
  }

  async function scan() {
    setScanning(true); setMessage('Scanning local model roots…');
    try {
      const result = await fetch('/api/scan', { method: 'POST' }).then(x => x.json());
      setMessage(`Indexed ${result.indexed} local AI assets.`); await refresh();
    } finally { setScanning(false); }
  }

  async function createSuggestedProfile() {
    const model = models.find(x => x.kind === 'model');
    const projector = models.find(x => x.kind === 'projector');
    if (!model) { setMessage('Scan a GGUF language model before creating a profile.'); return; }
    const response = await fetch('/api/profiles', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: DEFAULT_PROFILE_NAME, model_path: model.path, projector_path: projector?.path ?? null, context_size: 65536, gpu_layers: 99, host: '127.0.0.1', port: 8080, extra_args: [] }),
    });
    const data = await response.json();
    if (!response.ok) { setMessage(data.detail ?? 'Could not create launch profile.'); return; }
    setSelectedProfile(data.id); setMessage(`Saved launch profile “${data.name}”.`); await refresh();
  }

  async function ensureLabProfiles(): Promise<Profile[]> {
    let currentProfiles = profiles;
    const base = currentProfiles.find(profile => profile.is_default) ?? currentProfiles.find(profile => profile.projector_path) ?? currentProfiles[0];
    if (!base) throw new Error('Create a base Qwen profile first.');

    const specs = [
      { name: LAB_PROFILE_NAMES[0], projector_path: base.projector_path, context_size: 65536 },
      { name: LAB_PROFILE_NAMES[1], projector_path: null, context_size: 65536 },
      { name: LAB_PROFILE_NAMES[2], projector_path: null, context_size: 8192 },
    ];

    for (const spec of specs) {
      if (currentProfiles.some(profile => profile.name === spec.name)) continue;
      const response = await fetch('/api/profiles', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: spec.name,
          model_path: base.model_path,
          projector_path: spec.projector_path,
          context_size: spec.context_size,
          gpu_layers: base.gpu_layers,
          host: base.host,
          port: base.port,
          extra_args: parallelOneArgs(base.extra_args),
        }),
      });
      if (!response.ok && response.status !== 409) {
        const data = await response.json();
        throw new Error(data.detail ?? `Could not create ${spec.name}`);
      }
    }

    currentProfiles = await fetch('/api/profiles').then(x => x.json());
    setProfiles(currentProfiles);
    return LAB_PROFILE_NAMES.map(name => currentProfiles.find(profile => profile.name === name)).filter((profile): profile is Profile => Boolean(profile));
  }

  async function runSingleUserLab() {
    if (runtimes.some(runtime => runtime.running)) {
      setMessage('Stop Qwen, Hermes and Image Studio before running the clean benchmark suite.');
      return;
    }
    const returnProfile = profiles.find(profile => profile.is_default) ?? profiles.find(profile => !isLabProfile(profile)) ?? null;
    setLabBusy(true); setBenchmarkBusy(true); setLabProgress('Preparing single-user profiles…');
    try {
      const targets = await ensureLabProfiles();
      if (targets.length !== LAB_PROFILE_NAMES.length) throw new Error('Could not prepare all benchmark lab profiles.');
      let completedRuns = 0;
      const totalRuns = targets.length * 2;

      for (let profileIndex = 0; profileIndex < targets.length; profileIndex += 1) {
        const profile = targets[profileIndex];
        setSelectedProfile(profile.id);
        setLlamaHealth(null);
        setLabProgress(`Profile ${profileIndex + 1}/${targets.length} · starting ${profile.name}`);

        const launchResponse = await fetch(`/api/runtimes/llama.cpp/launch/${profile.id}`, { method: 'POST' });
        const launchData = await launchResponse.json();
        if (!launchResponse.ok) throw new Error(launchData.detail ?? `Could not launch ${profile.name}`);
        await checkHealthFor(profile.id);

        try {
          for (let run = 1; run <= 2; run += 1) {
            setLabProgress(`${profile.name} · benchmark ${run}/2 · overall ${completedRuns + 1}/${totalRuns}`);
            const benchmarkResponse = await fetch(`/api/benchmarks/${profile.id}`, { method: 'POST' });
            const benchmarkData = await benchmarkResponse.json();
            if (!benchmarkResponse.ok) throw new Error(benchmarkData.detail ?? `Benchmark failed for ${profile.name}`);
            completedRuns += 1;
          }
        } finally {
          await fetch('/api/runtimes/llama.cpp/stop', { method: 'POST' });
          setLlamaHealth(null);
          await sleep(1200);
        }
      }

      setLabProgress('Suite complete.');
      setMessage(`Single-user benchmark suite complete · ${completedRuns} controlled runs saved.`);
      await refresh();
      if (returnProfile) setSelectedProfile(returnProfile.id);
    } catch (error) {
      await fetch('/api/runtimes/llama.cpp/stop', { method: 'POST' }).catch(() => undefined);
      setLlamaHealth(null);
      setMessage(error instanceof Error ? error.message : 'Single-user benchmark suite failed.');
      if (returnProfile) setSelectedProfile(returnProfile.id);
    } finally {
      setLabBusy(false); setBenchmarkBusy(false);
    }
  }

  async function launch(runtime: Runtime) {
    setBusyRuntime(runtime.id); setMessage(`Launching ${runtime.label}…`);
    try {
      let url: string | null = null;
      if (runtime.id === 'llama.cpp') url = selectedProfile ? `/api/runtimes/llama.cpp/launch/${selectedProfile}` : null;
      if (runtime.id === 'a1111') url = '/api/runtimes/a1111/launch';
      if (runtime.id === 'hermes') url = '/api/runtimes/hermes/launch';
      if (!url) { setMessage('Create or select a llama.cpp launch profile first.'); return; }
      const response = await fetch(url, { method: 'POST' });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? 'Launch failed');
      setMessage(`${data.label} launched as PID ${data.pid}.`); await refresh(); await checkHealthFor(selectedProfile);
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Launch failed'); }
    finally { setBusyRuntime(null); }
  }

  async function launchWorkspace() {
    if (!selectedProfile) { setMessage('Create or select a llama.cpp launch profile first.'); return; }
    setWorkspaceBusy(true); setMessage('Starting Qwen and waiting for the local API before opening Hermes…');
    try {
      const response = await fetch(`/api/workspace/launch/${selectedProfile}`, { method: 'POST' });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? 'Workspace launch failed');
      setMessage(`AI workspace ready · Qwen PID ${data.llama_pid} · Hermes PID ${data.hermes_pid}`); await refresh(); await checkHealthFor(selectedProfile);
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Workspace launch failed'); }
    finally { setWorkspaceBusy(false); }
  }

  async function stopWorkspace() {
    setWorkspaceBusy(true); setMessage('Stopping Hermes and Qwen…');
    try {
      const response = await fetch('/api/workspace/stop', { method: 'POST' });
      if (!response.ok) throw new Error('Workspace stop failed');
      setLlamaHealth(null); setMessage('AI workspace stopped.'); await refresh();
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Workspace stop failed'); }
    finally { setWorkspaceBusy(false); }
  }

  async function stop(runtime: Runtime) {
    setBusyRuntime(runtime.id); setMessage(`Stopping ${runtime.label}…`);
    try {
      const response = await fetch(`/api/runtimes/${encodeURIComponent(runtime.id)}/stop`, { method: 'POST' });
      const data = await response.json(); if (!response.ok) throw new Error(data.detail ?? 'Stop failed');
      if (runtime.id === 'llama.cpp') setLlamaHealth(null);
      setMessage(`${runtime.label} stopped.`); await refresh();
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Stop failed'); }
    finally { setBusyRuntime(null); }
  }

  async function runSelectedBenchmark() {
    if (!selectedProfile) return;
    setBenchmarkBusy(true); setMessage('Running local Qwen benchmark…');
    try {
      const response = await fetch(`/api/benchmarks/${selectedProfile}`, { method: 'POST' });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? 'Benchmark failed');
      const speed = data.server_tokens_per_second ?? data.tokens_per_second;
      setMessage(`Benchmark complete · ${speed != null ? Number(speed).toFixed(2) + ' tok/s' : 'speed unavailable'}`);
      await refresh(); await checkHealthFor(selectedProfile);
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Benchmark failed'); }
    finally { setBenchmarkBusy(false); }
  }

  useEffect(() => {
    void refresh();
    const telemetryTimer = window.setInterval(() => void refreshTelemetry(), 3000);
    const runtimeTimer = window.setInterval(() => void refreshRuntimes(), 4000);
    return () => { window.clearInterval(telemetryTimer); window.clearInterval(runtimeTimer); };
  }, []);

  const llamaRunning = runtimes.some(x => x.id === 'llama.cpp' && x.running);
  useEffect(() => {
    void checkHealthFor(selectedProfile);
    if (!llamaRunning || !selectedProfile) return;
    const timer = window.setInterval(() => void checkHealthFor(selectedProfile), 2000);
    return () => window.clearInterval(timer);
  }, [selectedProfile, llamaRunning]);

  const counts = useMemo(() => ({ llm: models.filter(x => x.kind === 'model').length, projectors: models.filter(x => x.kind === 'projector').length, image: models.filter(x => x.kind === 'checkpoint').length }), [models]);
  const duplicateKeys = useMemo(() => {
    const map = new Map<string, number>();
    models.filter(x => x.kind === 'checkpoint').forEach(model => { const key = `${model.name.toLowerCase()}::${model.size_bytes}`; map.set(key, (map.get(key) ?? 0) + 1); });
    return new Set([...map.entries()].filter(([, count]) => count > 1).map(([key]) => key));
  }, [models]);

  const everydayProfiles = profiles.filter(profile => profile.is_default);
  const experimentalProfiles = profiles.filter(profile => !profile.is_default && !isLabProfile(profile));
  const labProfiles = profiles.filter(isLabProfile);
  const ramDetail = telemetry?.memory.used_bytes != null && telemetry?.memory.total_bytes != null ? `${bytesLabel(telemetry.memory.used_bytes)} / ${bytesLabel(telemetry.memory.total_bytes)}` : 'memory details unavailable';
  const vramPercent = telemetry?.gpu.vram_used_bytes != null && telemetry?.gpu.vram_total_bytes ? telemetry.gpu.vram_used_bytes / telemetry.gpu.vram_total_bytes * 100 : null;
  const vramDetail = telemetry?.gpu.vram_used_bytes != null ? telemetry.gpu.vram_total_bytes != null ? `${bytesLabel(telemetry.gpu.vram_used_bytes)} / ${bytesLabel(telemetry.gpu.vram_total_bytes)}` : `${bytesLabel(telemetry.gpu.vram_used_bytes)} dedicated memory used` : 'VRAM counter unavailable';
  const latestHistory = { cpu: history.map(x => x.cpu), ram: history.map(x => x.ram), gpu: history.map(x => x.gpu), vram: history.map(x => x.vram) };
  const llamaReady = runtimes.some(x => x.id === 'llama.cpp' && x.exists);
  const hermesReady = runtimes.some(x => x.id === 'hermes' && x.exists);
  const hermesRunning = runtimes.some(x => x.id === 'hermes' && x.running);
  const workspaceRunning = llamaRunning && hermesRunning;
  const selectedBenchmarks = benchmarks.filter(run => run.profile_id === selectedProfile);
  const latestBenchmark = selectedBenchmarks[0] ?? null;

  const profileSummaries = useMemo<ProfileSummary[]>(() => profiles.map(profile => {
    const speeds = benchmarks.filter(item => item.profile_id === profile.id).map(benchmarkSpeed).filter(speed => speed > 0);
    if (speeds.length === 0) return null;
    return { profile, runs: speeds.length, average: speeds.reduce((a, b) => a + b, 0) / speeds.length, best: Math.max(...speeds) };
  }).filter((item): item is ProfileSummary => Boolean(item)).sort((a, b) => b.average - a.average), [profiles, benchmarks]);

  const benchmarkWinner = profileSummaries[0] ?? null;
  const secondPlace = profileSummaries[1] ?? null;
  const winnerMargin = benchmarkWinner && secondPlace && secondPlace.average > 0 ? ((benchmarkWinner.average / secondPlace.average) - 1) * 100 : null;

  const labSummaries = useMemo<LabSummary[]>(() => LAB_PROFILE_NAMES.map(name => {
    const profile = profiles.find(item => item.name === name);
    if (!profile) return null;
    const runs = benchmarks.filter(item => item.profile_id === profile.id).map(benchmarkSpeed).filter(speed => speed > 0);
    if (runs.length === 0) return null;
    return { profile, runs: runs.length, average: runs.reduce((a, b) => a + b, 0) / runs.length, best: Math.max(...runs) };
  }).filter((item): item is LabSummary => Boolean(item)), [profiles, benchmarks]);

  return <main>
    <header><div><p className="eyebrow">LOCAL AI CONTROL DECK</p><h1>Vektor<span>Deck</span></h1><p className="tagline">One place for the models you actually run.</p></div><div className="status"><i></i>{health?.status === 'ok' ? 'SYSTEM ONLINE' : 'CONNECTING'}</div></header>

    <section className="overview">
      <article><span>BACKEND</span><strong>{health?.version ?? '—'}</strong><small>{health?.database === 'ok' ? 'SQLite integrity ok' : 'waiting for backend'}</small></article>
      <article><span>LANGUAGE MODELS</span><strong>{counts.llm}</strong><small>{counts.projectors} multimodal projector(s)</small></article>
      <article><span>IMAGE MODELS</span><strong>{counts.image}</strong><small>Stable Diffusion checkpoints indexed</small></article>
      <article><span>RUNTIMES</span><strong>{runtimes.filter(x => x.exists).length}/{runtimes.length}</strong><small>configured launch targets found</small></article>
    </section>

    <section className="telemetrySection">
      <div className="sectionHead"><div><p className="eyebrow">MACHINE STATE</p><h2>What the workstation is doing.</h2></div><p className="consoleMessage">Live snapshot · 90 second rolling history</p></div>
      <div className="telemetryGrid">
        {[
          ['CPU', telemetry?.cpu.utilization_percent, `${telemetry?.cpu.logical_processors ?? '—'} logical processors`, latestHistory.cpu],
          ['RAM', telemetry?.memory.percent, ramDetail, latestHistory.ram],
          ['GPU', telemetry?.gpu.utilization_percent, telemetry?.gpu.name ?? 'GPU telemetry unavailable', latestHistory.gpu],
          ['VRAM', vramPercent, vramDetail, latestHistory.vram],
        ].map(([label, value, detail, values]) => <article className="telemetryCard" key={String(label)}><div className="telemetryTop"><span>{String(label)}</span><b>{loadState(value as number | null)}</b></div><strong>{label === 'VRAM' ? (telemetry?.gpu.vram_used_bytes != null ? bytesLabel(telemetry.gpu.vram_used_bytes) : '—') : percent(value as number | null)}</strong><small>{String(detail)}</small><div className="telemetryMeter"><i style={{ width: `${clamp(value as number | null)}%` }}></i></div><Sparkline values={values as number[]} /></article>)}
      </div>
    </section>

    <section className="runtimeSection">
      <div className="sectionHead"><div><p className="eyebrow">RUNTIME DECK</p><h2>Boot what you need.</h2></div><p className="consoleMessage">{message}</p></div>
      <div className="profileBar"><div><span className="profileLabel">LLAMA.CPP PROFILE</span>{profiles.length > 0 ? <select value={selectedProfile ?? ''} onChange={event => setSelectedProfile(Number(event.target.value))}>
        {everydayProfiles.length > 0 && <optgroup label="EVERYDAY">{everydayProfiles.map(profile => <option value={profile.id} key={profile.id}>★ {profileLabel(profile)}</option>)}</optgroup>}
        {experimentalProfiles.length > 0 && <optgroup label="EXPERIMENTAL">{experimentalProfiles.map(profile => <option value={profile.id} key={profile.id}>{profileLabel(profile)}</option>)}</optgroup>}
        {labProfiles.length > 0 && <optgroup label="LAB / ARCHIVE">{labProfiles.map(profile => <option value={profile.id} key={profile.id}>{profileLabel(profile)}</option>)}</optgroup>}
      </select> : <span className="profileEmpty">No saved profiles yet.</span>}</div>{profiles.length === 0 && <button className="secondaryButton" onClick={() => void createSuggestedProfile()}>CREATE SUGGESTED QWEN PROFILE</button>}</div>
      <div className="profileBar labBar"><div><span className="profileLabel">SINGLE-USER LAB</span><span className="profileEmpty">Vision/text-only · 65K/8K · --parallel 1 · two runs each</span></div><button className="secondaryButton labButton" onClick={() => void runSingleUserLab()} disabled={labBusy || profiles.length === 0}>{labBusy ? 'RUNNING LAB…' : 'RUN AUTOMATED LAB'}</button></div>
      {labBusy && <div className="labProgress"><span>LAB ACTIVE</span><strong>{labProgress}</strong></div>}
      <div className="profileBar"><div><span className="profileLabel">AI WORKSPACE</span><span className="profileEmpty">Qwen + Hermes · Image Studio remains independent</span></div>{workspaceRunning ? <button className="secondaryButton dangerButton" onClick={() => void stopWorkspace()} disabled={workspaceBusy}>{workspaceBusy ? 'STOPPING…' : 'STOP AI WORKSPACE'}</button> : <button className="secondaryButton" onClick={() => void launchWorkspace()} disabled={workspaceBusy || !selectedProfile || !llamaReady || !hermesReady}>{workspaceBusy ? 'STARTING WORKSPACE…' : 'BOOT AI WORKSPACE'}</button>}</div>

      {llamaHealth?.online && <div className="runtimeDiagnostics">
        <article><span>ACTIVE API</span><strong>{llamaHealth.latency_ms != null ? `${llamaHealth.latency_ms.toFixed(1)} ms` : 'ONLINE'}</strong><small>loopback-only profile · localhost CORS</small></article>
        <article><span>INFERENCE SLOTS</span><strong>{llamaHealth.total_slots ?? '—'}</strong><small>{llamaHealth.total_slots === 1 ? 'single-stream runtime' : llamaHealth.total_slots ? `${llamaHealth.total_slots} concurrent server slots` : 'runtime did not report slot count'}</small></article>
        <article><span>MODALITY</span><strong>{profiles.find(profile => profile.id === selectedProfile)?.projector_path ? 'VISION' : 'TEXT'}</strong><small>{llamaHealth.model_path ?? 'active model path unavailable'}</small></article>
        <article><span>LLAMA BUILD</span><strong>LIVE</strong><small>{compactBuildInfo(llamaHealth.build_info)}</small></article>
      </div>}

      <div className="runtimeGrid">
        {runtimes.map(runtime => <article className={`runtimeCard ${runtime.running ? 'runtimeRunning' : ''}`} key={runtime.id}><div className="runtimeTop"><span>{runtime.id.toUpperCase()}</span><b className={runtime.running ? 'running' : runtime.exists ? 'ready' : 'missing'}>{runtime.running ? `RUNNING · PID ${runtime.pid}` : runtime.exists ? 'READY' : 'NOT FOUND'}</b></div><h3>{runtime.label}</h3><p>{runtime.path ?? 'Runtime path not configured yet.'}</p>{runtime.running ? <button className="stopButton" onClick={() => void stop(runtime)} disabled={busyRuntime === runtime.id || labBusy}>{busyRuntime === runtime.id ? 'STOPPING…' : 'STOP RUNTIME'}</button> : <button onClick={() => void launch(runtime)} disabled={!runtime.launchable || busyRuntime === runtime.id || labBusy}>{busyRuntime === runtime.id ? 'LAUNCHING…' : runtime.id === 'a1111' ? 'BOOT IMAGE STUDIO' : runtime.id === 'hermes' ? 'BOOT HERMES' : 'BOOT SELECTED PROFILE'}</button>}</article>)}
      </div>
    </section>

    <section className="benchmarkSection">
      <div className="sectionHead"><div><p className="eyebrow">LLM HEALTH / BENCHMARK</p><h2>Measure the runtime, not the guess.</h2></div><p className="consoleMessage">Results are saved locally in SQLite</p></div>
      <div className="benchmarkGrid">
        <article className="benchmarkCard"><span>API STATUS</span><strong className={llamaHealth?.online ? 'ready' : 'missing'}>{llamaHealth?.online ? 'ONLINE' : 'OFFLINE'}</strong><small>{llamaHealth?.latency_ms != null ? `${llamaHealth.latency_ms.toFixed(1)} ms /v1/models latency` : 'Selected profile must be the active llama.cpp runtime'}</small></article>
        <article className="benchmarkCard winnerCard"><span>CURRENT WINNER</span><strong>{benchmarkWinner ? `${benchmarkWinner.average.toFixed(2)} tok/s` : '—'}</strong><small>{benchmarkWinner ? `${benchmarkWinner.profile.name}${winnerMargin != null ? ` · ${winnerMargin.toFixed(1)}% ahead of #2` : ''}` : 'Run controlled benchmarks to rank profiles'}</small></article>
        <article className="benchmarkCard"><span>SELECTED PROFILE SPEED</span><strong>{latestBenchmark ? `${benchmarkSpeed(latestBenchmark).toFixed(2)} tok/s` : '—'}</strong><small>{latestBenchmark ? `${latestBenchmark.profile_name} · ${latestBenchmark.completion_tokens ?? '—'} completion tokens` : 'No saved run for selected profile'}</small></article>
        <article className="benchmarkAction"><div><span>CONTROLLED LOCAL TEST</span><small>Fixed prompt · temperature 0 · max 160 tokens</small></div><button className="scanButton" onClick={() => void runSelectedBenchmark()} disabled={benchmarkBusy || labBusy || !selectedProfile || !llamaHealth?.online}>{benchmarkBusy && !labBusy ? 'BENCHMARKING…' : 'RUN BENCHMARK'}</button></article>
      </div>

      {profileSummaries.length > 0 && <div className="profileRanking"><div className="labSummaryHead"><span>PROFILE RANKING</span><small>Average server-reported generation speed</small></div>{profileSummaries.map((item, index) => <div className={`labSummaryRow ${index === 0 ? 'rankingWinner' : ''}`} key={item.profile.id}><strong>{index === 0 ? '★ ' : ''}{item.profile.name}</strong><span>{item.profile.context_size.toLocaleString()} ctx</span><span>{item.profile.projector_path ? 'VISION' : 'TEXT'}</span><b>{item.average.toFixed(2)} avg tok/s</b><small>{item.best.toFixed(2)} best · {item.runs} run(s)</small></div>)}</div>}

      {labSummaries.length > 0 && <div className="labSummary"><div className="labSummaryHead"><span>SINGLE-USER LAB SUMMARY</span><small>--parallel 1 controls · preserved as experiment evidence</small></div>{labSummaries.map(item => <div className="labSummaryRow" key={item.profile.id}><strong>{item.profile.name}</strong><span>{item.profile.context_size.toLocaleString()} ctx</span><span>{item.profile.projector_path ? 'VISION' : 'TEXT'}</span><b>{item.average.toFixed(2)} avg tok/s</b><small>{item.best.toFixed(2)} best · {item.runs} run(s)</small></div>)}</div>}

      {benchmarks.length > 0 && <div className="benchmarkHistory">{benchmarks.slice(0, 16).map(run => <div className="benchmarkRow" key={run.id}><span>#{String(run.id).padStart(3, '0')}</span><strong>{run.profile_name}</strong><b>{benchmarkSpeed(run).toFixed(2)} tok/s</b><small>{Number(run.elapsed_seconds).toFixed(2)} s</small><small>{localTimestamp(run.created_at)}</small></div>)}</div>}
    </section>

    <section className="models"><div className="sectionHead"><div><p className="eyebrow">MODEL LIBRARY</p><h2>What is on this machine.</h2></div><button className="scanButton" onClick={scan} disabled={scanning}>{scanning ? 'SCANNING…' : 'SCAN NOW'}</button></div><div className="modelList">{models.length === 0 && <div className="empty">No assets indexed yet. Configure model roots and run the first scan.</div>}{models.map((model, index) => { const duplicate = model.kind === 'checkpoint' && duplicateKeys.has(`${model.name.toLowerCase()}::${model.size_bytes}`); return <div className="model" key={model.path}><span className="index">{String(index + 1).padStart(2, '0')}</span><div><strong>{model.name}{duplicate && <em className="duplicateTag">duplicate copy</em>}</strong><small>{model.path}</small></div><span className={`kind kind-${model.kind}`}>{model.kind.toUpperCase()}</span><b>{gb(model.size_bytes)}</b></div>; })}</div></section>
    <footer><span>VEKTORDECK / LOCAL-FIRST</span><span>YOUR MACHINE. YOUR MODELS. YOUR RULES.</span></footer>
  </main>;
}
