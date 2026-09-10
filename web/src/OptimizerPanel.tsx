import { useMemo, useState } from 'react';
import './optimizer.css';

type Profile = {
  id: number;
  name: string;
  model_path: string;
  projector_path: string | null;
  context_size: number;
  gpu_layers: number;
  host: string;
  port: number;
  extra_args: string[];
};

type BenchmarkResult = {
  id: number;
  profile_id: number;
  profile_name: string;
  server_tokens_per_second: number | null;
  tokens_per_second: number | null;
  quality: 'HEALTHY' | 'TIGHT' | 'PRESSURED' | 'UNVERIFIED';
  quality_reasons: string[];
  ram_avg_percent: number | null;
  ram_peak_percent: number | null;
  gpu_avg_percent: number | null;
  vram_peak_bytes: number | null;
  vram_total_bytes: number | null;
};

type OptimizerResult = {
  profile: Profile;
  benchmark: BenchmarkResult | null;
  slots: number | null;
  error: string | null;
};

type Capabilities = {
  parallel: boolean;
  cache_type_k: boolean;
  cache_type_v: boolean;
  flash_attn: boolean;
  image_min_tokens: boolean;
  no_host: boolean;
};

type Preflight = {
  ready: boolean;
  sample_count: number;
  cpu_avg_percent?: number | null;
  cpu_peak_percent?: number | null;
  ram_avg_percent?: number | null;
  ram_peak_percent?: number | null;
  gpu_avg_percent?: number | null;
  gpu_peak_percent?: number | null;
  reasons: string[];
};

type ProcessSnapshot = {
  pid: number;
  name: string;
  cpu_percent: number;
  memory_mb: number;
};

type TargetSpec = {
  name: string;
  context_size: number;
  args: string[];
  note: string;
};

const BASE_PROFILE = 'Qwen local 65K';
const sleep = (ms: number) => new Promise(resolve => window.setTimeout(resolve, ms));
const speed = (run: BenchmarkResult | null) => Number(run?.server_tokens_per_second ?? run?.tokens_per_second ?? 0);
const pct = (value: number | null | undefined) => value == null ? '—' : `${value.toFixed(1)}%`;
const gb = (value: number | null) => value == null ? '—' : `${(value / 1024 ** 3).toFixed(2)} GB`;

function stripOptimizerArgs(args: string[]) {
  const valueOptions = new Set([
    '--parallel', '-np', '--cache-type-k', '-ctk', '--cache-type-v', '-ctv', '--flash-attn', '-fa',
  ]);
  const result: string[] = [];
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (valueOptions.has(arg)) { index += 1; continue; }
    if ([...valueOptions].some(option => arg.startsWith(`${option}=`))) continue;
    result.push(arg);
  }
  return result;
}

function optimizerArgs(base: string[], extra: string[]) {
  return [...stripOptimizerArgs(base), '--parallel', '1', ...extra];
}

async function jsonResponse(response: Response) {
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail ?? `HTTP ${response.status}`);
  return data;
}

export default function OptimizerPanel() {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState('Ready for a quiet-baseline memory sweep.');
  const [results, setResults] = useState<OptimizerResult[]>([]);
  const [baseline, setBaseline] = useState<Preflight | null>(null);
  const [contaminators, setContaminators] = useState<ProcessSnapshot[]>([]);
  const [capabilityText, setCapabilityText] = useState('Capabilities are checked from your local llama-server.exe before the sweep.');

  const trustworthy = useMemo(
    () => results.filter(item => item.benchmark && !item.error && ['HEALTHY', 'TIGHT'].includes(item.benchmark.quality)),
    [results],
  );
  const recommendation = useMemo(
    () => [...trustworthy].sort((a, b) => speed(b.benchmark) - speed(a.benchmark))[0] ?? null,
    [trustworthy],
  );

  async function stopAll() {
    await fetch('/api/workspace/stop', { method: 'POST' }).catch(() => undefined);
    await fetch('/api/runtimes/a1111/stop', { method: 'POST' }).catch(() => undefined);
    await fetch('/api/runtimes/hermes/stop', { method: 'POST' }).catch(() => undefined);
    await fetch('/api/runtimes/llama.cpp/stop', { method: 'POST' }).catch(() => undefined);
    await sleep(1500);
  }

  async function processSnapshot(): Promise<ProcessSnapshot[]> {
    try {
      const payload = await fetch('/api/processes/top?limit=8').then(jsonResponse);
      return Array.isArray(payload.processes) ? payload.processes : [];
    } catch {
      return [];
    }
  }

  async function attachProtocol(run: BenchmarkResult, check: Preflight, processes: ProcessSnapshot[]) {
    await fetch(`/api/benchmark-protocol/${run.id}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ run_source: 'optimizer', baseline: check, contaminators: processes }),
    }).then(jsonResponse);
  }

  async function waitForQuietBaseline(label: string): Promise<Preflight> {
    for (let attempt = 1; attempt <= 3; attempt += 1) {
      setProgress(`${label} · checking idle baseline ${attempt}/3…`);
      const check: Preflight = await fetch('/api/optimizer/preflight').then(jsonResponse);
      setBaseline(check);
      if (check.ready) {
        const processes = await processSnapshot();
        setContaminators(processes);
        return check;
      }
      if (attempt < 3) {
        setProgress(`${label} · workstation is still busy: ${check.reasons.join(' · ')} · waiting…`);
        await sleep(3500);
      }
    }
    const last: Preflight = await fetch('/api/optimizer/preflight').then(jsonResponse);
    setBaseline(last);
    const processes = await processSnapshot();
    setContaminators(processes);
    const top = processes.slice(0, 4).map(item => `${item.name} PID ${item.pid} · CPU ${item.cpu_percent.toFixed(1)}% · RAM ${item.memory_mb.toFixed(0)} MB`).join(' · ');
    throw new Error(`Optimizer needs a quieter baseline: ${last.reasons.join(' · ')}${top ? ` · top processes: ${top}` : ''}`);
  }

  function buildTargets(capabilities: Capabilities): TargetSpec[] {
    const targets: TargetSpec[] = [
      {
        name: 'Qwen vision 32K P1 f16 clean',
        context_size: 32768,
        args: [],
        note: '32K control · default f16 KV cache',
      },
    ];

    if (capabilities.cache_type_k) {
      targets.push({
        name: 'Qwen vision 32K P1 q8K clean',
        context_size: 32768,
        args: ['--cache-type-k', 'q8_0'],
        note: '32K · q8 K cache · f16 V cache',
      });
    }

    if (capabilities.cache_type_k && capabilities.cache_type_v && capabilities.flash_attn) {
      targets.push(
        {
          name: 'Qwen vision 32K P1 q8KV FA clean',
          context_size: 32768,
          args: ['--cache-type-k', 'q8_0', '--cache-type-v', 'q8_0', '--flash-attn', 'on'],
          note: '32K · q8 K/V cache · flash attention',
        },
        {
          name: 'Qwen vision 16K P1 q8KV FA clean',
          context_size: 16384,
          args: ['--cache-type-k', 'q8_0', '--cache-type-v', 'q8_0', '--flash-attn', 'on'],
          note: '16K · q8 K/V cache · flash attention',
        },
      );
    }

    return targets;
  }

  async function ensureProfiles(targets: TargetSpec[]): Promise<Profile[]> {
    let profiles: Profile[] = await fetch('/api/profiles').then(jsonResponse);
    const base = profiles.find(profile => profile.name === BASE_PROFILE) ?? profiles.find(profile => profile.projector_path);
    if (!base) throw new Error('No multimodal Qwen base profile is available.');
    if (!base.projector_path) throw new Error('The optimizer requires a vision profile with a projector.');

    for (const target of targets) {
      if (profiles.some(profile => profile.name === target.name)) continue;
      const response = await fetch('/api/profiles', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: target.name,
          model_path: base.model_path,
          projector_path: base.projector_path,
          context_size: target.context_size,
          gpu_layers: base.gpu_layers,
          host: base.host,
          port: base.port,
          extra_args: optimizerArgs(base.extra_args, target.args),
        }),
      });
      if (!response.ok && response.status !== 409) await jsonResponse(response);
    }

    profiles = await fetch('/api/profiles').then(jsonResponse);
    const prepared = targets.map(target => profiles.find(profile => profile.name === target.name)).filter((profile): profile is Profile => Boolean(profile));
    if (prepared.length !== targets.length) throw new Error('Could not prepare all optimizer profiles.');
    return prepared;
  }

  async function runOptimizer() {
    setBusy(true);
    setResults([]);
    setBaseline(null);
    setContaminators([]);
    try {
      setProgress('Stopping AI runtimes so the baseline can settle…');
      await stopAll();
      let currentBaseline = await waitForQuietBaseline('Preflight');

      const capabilityPayload = await fetch('/api/llama/capabilities').then(jsonResponse);
      const capabilities: Capabilities = capabilityPayload.capabilities;
      if (!capabilities.parallel) throw new Error('This llama.cpp build does not advertise --parallel; optimizer stopped.');
      const targets = buildTargets(capabilities);
      setCapabilityText(
        `Detected: parallel ${capabilities.parallel ? 'yes' : 'no'} · q8 K ${capabilities.cache_type_k ? 'yes' : 'no'} · q8 V ${capabilities.cache_type_v ? 'yes' : 'no'} · flash attention ${capabilities.flash_attn ? 'yes' : 'no'}`,
      );
      const profiles = await ensureProfiles(targets);
      const collected: OptimizerResult[] = [];

      for (let index = 0; index < profiles.length; index += 1) {
        const profile = profiles[index];
        if (index > 0) currentBaseline = await waitForQuietBaseline(`Candidate ${index + 1}/${profiles.length}`);
        const currentProcesses = await processSnapshot();
        setContaminators(currentProcesses);
        setProgress(`${index + 1}/${profiles.length} · loading ${profile.name}…`);

        let launched = false;
        try {
          const launch = await fetch(`/api/runtimes/llama.cpp/launch/${profile.id}`, { method: 'POST' });
          await jsonResponse(launch);
          launched = true;

          const health = await fetch(`/api/llama/health/${profile.id}`).then(jsonResponse);
          const slots = typeof health.total_slots === 'number' ? health.total_slots : null;
          if (slots !== 1) {
            const error = slots == null ? 'Could not verify live slot count.' : `Requested one slot but llama.cpp reported ${slots}.`;
            collected.push({ profile, benchmark: null, slots, error });
            setResults([...collected]);
            throw new Error(`${profile.name}: ${error} Sweep stopped to protect benchmark integrity.`);
          }

          setProgress(`${index + 1}/${profiles.length} · verified 1 slot · benchmarking ${profile.context_size.toLocaleString()} context…`);
          const benchmark: BenchmarkResult = await fetch(`/api/benchmarks/${profile.id}`, { method: 'POST' }).then(jsonResponse);
          await attachProtocol(benchmark, currentBaseline, currentProcesses);
          collected.push({ profile, benchmark, slots, error: null });
          setResults([...collected]);
        } catch (error) {
          const message = error instanceof Error ? error.message : 'Candidate failed.';
          if (!collected.some(item => item.profile.id === profile.id)) {
            collected.push({ profile, benchmark: null, slots: null, error: message });
            setResults([...collected]);
          }
          if (message.includes('slot')) throw error;
        } finally {
          if (launched) await fetch('/api/runtimes/llama.cpp/stop', { method: 'POST' }).catch(() => undefined);
          await sleep(1800);
        }
      }

      setProgress('Quiet-baseline KV-cache sweep complete. Protocol-v2 results are saved in benchmark history.');
    } catch (error) {
      setProgress(error instanceof Error ? error.message : 'Optimizer failed.');
    } finally {
      await fetch('/api/runtimes/llama.cpp/stop', { method: 'POST' }).catch(() => undefined);
      setBusy(false);
    }
  }

  return <>
    <button className="optimizerToggle" onClick={() => setOpen(value => !value)} aria-expanded={open}>
      MEMORY OPTIMIZER
    </button>

    <aside className={`optimizerDrawer ${open ? 'optimizerOpen' : ''}`} aria-hidden={!open}>
      <div className="optimizerHeader">
        <div><span>HARDWARE-AWARE LAB</span><strong>Memory Optimizer</strong></div>
        <button onClick={() => setOpen(false)} aria-label="Close optimizer">×</button>
      </div>

      <section className="optimizerIntro">
        <p>Phase 2 requires a quiet workstation baseline, verifies exactly one live llama.cpp slot, then tests only KV-cache controls advertised by your installed build.</p>
        <button onClick={() => void runOptimizer()} disabled={busy}>{busy ? 'OPTIMIZER RUNNING…' : 'RUN QUIET KV SWEEP'}</button>
        <small>{progress}</small>
        <small>{capabilityText}</small>
      </section>

      {baseline && <section className={`optimizerBaseline ${baseline.ready ? 'baselineReady' : 'baselineBusy'}`}>
        <span>IDLE BASELINE</span>
        <strong>{baseline.ready ? 'READY' : 'BUSY'}</strong>
        <small>CPU {pct(baseline.cpu_avg_percent)} avg / {pct(baseline.cpu_peak_percent)} peak · RAM {pct(baseline.ram_avg_percent)} avg · GPU {pct(baseline.gpu_avg_percent)} avg</small>
        {!baseline.ready && <small>{baseline.reasons.join(' · ')}</small>}
        {contaminators.length > 0 && <small>Top processes: {contaminators.slice(0, 4).map(item => `${item.name} ${item.cpu_percent.toFixed(1)}% CPU / ${item.memory_mb.toFixed(0)} MB`).join(' · ')}</small>}
      </section>}

      {recommendation ? <section className="optimizerRecommendation">
        <span>BEST TRUSTWORTHY RESULT</span>
        <strong>{recommendation.profile.context_size.toLocaleString()} ctx · {speed(recommendation.benchmark).toFixed(2)} tok/s</strong>
        <small>{recommendation.benchmark?.quality} · {recommendation.profile.name}</small>
      </section> : results.some(item => item.benchmark) && <section className="optimizerRecommendation optimizerNoWinner">
        <span>TRUSTWORTHY RESULT</span>
        <strong>NONE YET</strong>
        <small>PRESSURED and UNVERIFIED runs are deliberately excluded from recommendations.</small>
      </section>}

      <section className="optimizerResults">
        {results.length === 0 && <div className="optimizerEmpty">No Phase 2 sweep has been run in this session.</div>}
        {results.map(item => <article key={item.profile.id} className={`optimizerResult ${item.benchmark?.quality?.toLowerCase() ?? 'failed'}`}>
          <div className="optimizerResultHead"><strong>{item.profile.context_size.toLocaleString()} ctx</strong><span>{item.error ? 'FAILED' : item.benchmark?.quality}</span></div>
          <small>{item.profile.name} · live slots {item.slots ?? '—'}</small>
          {item.benchmark ? <div className="optimizerMetrics">
            <div><span>SPEED</span><b>{speed(item.benchmark).toFixed(2)} tok/s</b></div>
            <div><span>RAM AVG</span><b>{pct(item.benchmark.ram_avg_percent)}</b></div>
            <div><span>RAM PEAK</span><b>{pct(item.benchmark.ram_peak_percent)}</b></div>
            <div><span>VRAM PEAK</span><b>{gb(item.benchmark.vram_peak_bytes)}</b></div>
          </div> : <p>{item.error}</p>}
        </article>)}
      </section>
    </aside>
  </>;
}
