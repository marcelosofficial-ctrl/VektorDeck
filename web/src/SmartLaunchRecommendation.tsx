import { useEffect, useState } from 'react';

type SuggestedProfile = {
  name: string;
  model_path: string;
  projector_path: string | null;
  context_size: number;
  gpu_layers: number;
  host: string;
  port: number;
  extra_args: string[];
};

type SavedProfile = SuggestedProfile & { id: number; is_default: boolean };

type Recommendation = {
  status: 'EVIDENCE_BACKED' | 'EXPERIMENTAL' | 'BLOCKED';
  source: string;
  model_path: string;
  architecture: string | null;
  quantization_hint: string | null;
  machine?: { ram_total_bytes: number | null; vram_total_bytes: number | null };
  pairing?: { recommended_projector?: { name: string; path: string; reasons: string[] } | null } | null;
  evidence?: { runs: number; average_tokens_per_second: number; best_tokens_per_second: number } | null;
  reasons: string[];
  profile: SuggestedProfile | null;
};

type Baseline = {
  ready: boolean;
  sample_count: number;
  reasons?: string[];
  active_runtimes?: string[];
  cpu_avg_percent?: number | null;
  cpu_peak_percent?: number | null;
  ram_avg_percent?: number | null;
  ram_peak_percent?: number | null;
  gpu_avg_percent?: number | null;
  gpu_peak_percent?: number | null;
};

type ProcessSnapshot = {
  pid: number;
  name: string;
  cpu_percent: number;
  memory_bytes: number;
  memory_mb: number;
};

type Benchmark = {
  id: number;
  quality: 'HEALTHY' | 'TIGHT' | 'PRESSURED' | 'UNVERIFIED';
  quality_reasons?: string[];
  server_tokens_per_second?: number | null;
  tokens_per_second?: number | null;
  ram_avg_percent?: number | null;
  ram_peak_percent?: number | null;
  vram_peak_bytes?: number | null;
  vram_total_bytes?: number | null;
};

type ValidationResult = {
  profileName: string;
  reusedProfile: boolean;
  runs: Benchmark[];
  finalStatus: string;
  note: string;
};

const gib = (value: number | null | undefined) => value == null ? '—' : `${(value / 1024 ** 3).toFixed(1)} GiB`;
const samePath = (left: string | null | undefined, right: string | null | undefined) =>
  (left ?? '').replace(/\\/g, '/').toLowerCase() === (right ?? '').replace(/\\/g, '/').toLowerCase();
const normalizedArgs = (args: string[]) => JSON.stringify(args.map(String));

async function jsonResponse(response: Response) {
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail ?? `HTTP ${response.status}`);
  return data;
}

function identicalProfile(saved: SavedProfile, suggested: SuggestedProfile) {
  return samePath(saved.model_path, suggested.model_path)
    && samePath(saved.projector_path, suggested.projector_path)
    && saved.context_size === suggested.context_size
    && saved.gpu_layers === suggested.gpu_layers
    && saved.host === suggested.host
    && saved.port === suggested.port
    && normalizedArgs(saved.extra_args) === normalizedArgs(suggested.extra_args);
}

function contaminatorSummary(processes: ProcessSnapshot[]) {
  return processes
    .slice(0, 4)
    .map(item => `${item.name} PID ${item.pid} · CPU ${item.cpu_percent.toFixed(1)}% · RAM ${item.memory_mb.toFixed(0)} MB`)
    .join(' · ');
}

export default function SmartLaunchRecommendation({ modelPath, enabled }: { modelPath: string; enabled: boolean }) {
  const [recommendation, setRecommendation] = useState<Recommendation | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [validation, setValidation] = useState<ValidationResult | null>(null);

  async function load() {
    if (!enabled) {
      setRecommendation(null);
      return null;
    }
    setBusy(true);
    setMessage('Analyzing local hardware, model metadata, profiles and trustworthy benchmark evidence…');
    try {
      const data: Recommendation = await fetch(`/api/recommendations?model_path=${encodeURIComponent(modelPath)}`).then(jsonResponse);
      setRecommendation(data);
      setMessage(data.status === 'EVIDENCE_BACKED'
        ? 'Recommendation is backed by repeated HEALTHY/TIGHT benchmark evidence.'
        : 'Experimental starting point. Benchmark it before treating it as proven.');
      return data;
    } catch (error) {
      setRecommendation(null);
      setMessage(error instanceof Error ? error.message : 'Could not build a smart launch recommendation.');
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function createProfile() {
    if (!recommendation?.profile) return;
    setBusy(true);
    setMessage('Saving suggested profile locally…');
    try {
      const result = await fetch('/api/recommendations/profile', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model_path: modelPath }),
      }).then(jsonResponse);
      setMessage(`Created ${result.created.name}. Reloading dashboard…`);
      window.setTimeout(() => window.location.reload(), 450);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not create suggested profile.');
      setBusy(false);
    }
  }

  async function snapshotProcesses(): Promise<ProcessSnapshot[]> {
    try {
      const payload = await fetch('/api/processes/top?limit=8').then(jsonResponse);
      return Array.isArray(payload.processes) ? payload.processes as ProcessSnapshot[] : [];
    } catch {
      return [];
    }
  }

  async function attachProtocol(run: Benchmark, baseline: Baseline, processes: ProcessSnapshot[]) {
    await fetch(`/api/benchmark-protocol/${run.id}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        run_source: 'smart_launch',
        baseline,
        contaminators: processes,
      }),
    }).then(jsonResponse);
  }

  async function validateSuggestion() {
    if (!recommendation?.profile || recommendation.status !== 'EXPERIMENTAL') return;
    setBusy(true);
    setValidation(null);
    let profileId: number | null = null;
    let launched = false;
    try {
      setMessage('VALIDATION 1/6 · checking for a quiet workstation baseline…');
      const baseline: Baseline = await fetch('/api/optimizer/preflight').then(jsonResponse);
      const processes = await snapshotProcesses();
      if (!baseline.ready) {
        const reason = baseline.reasons?.join(' · ') || 'workstation baseline is not quiet enough';
        const top = contaminatorSummary(processes);
        throw new Error(`Validation did not start: ${reason}${top ? ` · top processes: ${top}` : ''}`);
      }

      setMessage('VALIDATION 2/6 · finding or creating the suggested profile…');
      const profiles: SavedProfile[] = await fetch('/api/profiles').then(jsonResponse);
      const existing = profiles.find(profile => identicalProfile(profile, recommendation.profile!));
      let profile: SavedProfile;
      if (existing) {
        profile = existing;
      } else {
        const created = await fetch('/api/recommendations/profile', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ model_path: modelPath }),
        }).then(jsonResponse);
        profile = created.created as SavedProfile;
      }
      profileId = profile.id;

      setMessage('VALIDATION 3/6 · launching suggested profile and verifying one live slot…');
      await fetch(`/api/runtimes/llama.cpp/launch/${profile.id}`, { method: 'POST' }).then(jsonResponse);
      launched = true;
      const health = await fetch(`/api/llama/health/${profile.id}`).then(jsonResponse);
      if (health.total_slots !== 1) {
        throw new Error(`Validation aborted: llama.cpp reported ${health.total_slots ?? 'unknown'} live slots instead of exactly 1.`);
      }

      setMessage('VALIDATION 4/6 · running evidence benchmark 1 of 2…');
      const first: Benchmark = await fetch(`/api/benchmarks/${profile.id}`, { method: 'POST' }).then(jsonResponse);
      await attachProtocol(first, baseline, processes);
      const runs = [first];
      if (!['HEALTHY', 'TIGHT'].includes(first.quality)) {
        const reason = first.quality_reasons?.join(' · ') || `run quality was ${first.quality}`;
        setValidation({
          profileName: profile.name,
          reusedProfile: Boolean(existing),
          runs,
          finalStatus: 'NOT PROMOTED',
          note: `Stopped after run 1 because evidence was ${first.quality}: ${reason}`,
        });
        setMessage('Validation stopped early because benchmark 1 was not trustworthy.');
        return;
      }

      setMessage('VALIDATION 5/6 · benchmark 1 was clean; running evidence benchmark 2 of 2…');
      const second: Benchmark = await fetch(`/api/benchmarks/${profile.id}`, { method: 'POST' }).then(jsonResponse);
      await attachProtocol(second, baseline, processes);
      runs.push(second);
      const bothTrustworthy = runs.every(run => ['HEALTHY', 'TIGHT'].includes(run.quality));

      setMessage('VALIDATION 6/6 · stopping llama.cpp and recalculating recommendation…');
      await fetch('/api/runtimes/llama.cpp/stop', { method: 'POST' }).then(jsonResponse);
      launched = false;
      const updated: Recommendation = await fetch(`/api/recommendations?model_path=${encodeURIComponent(modelPath)}`).then(jsonResponse);
      setRecommendation(updated);
      setValidation({
        profileName: profile.name,
        reusedProfile: Boolean(existing),
        runs,
        finalStatus: updated.status === 'EVIDENCE_BACKED' ? 'PROMOTED' : 'NOT PROMOTED',
        note: bothTrustworthy
          ? (updated.status === 'EVIDENCE_BACKED'
            ? 'Two clean protocol-v2 runs were saved and Smart Launch promoted the configuration to evidence-backed.'
            : 'Two clean runs were saved, but more evidence is still required by the current recommendation rules.')
          : `Run 2 was ${second.quality}, so the configuration was not promoted.`,
      });
      setMessage(updated.status === 'EVIDENCE_BACKED'
        ? 'Validation complete · configuration is now EVIDENCE-BACKED.'
        : 'Validation complete · configuration remains experimental.');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Smart Launch validation failed.');
    } finally {
      if (launched && profileId != null) {
        try {
          await fetch('/api/runtimes/llama.cpp/stop', { method: 'POST' }).then(jsonResponse);
        } catch {
          setMessage(current => `${current} · llama.cpp stop should be checked manually.`);
        }
      }
      setBusy(false);
    }
  }

  useEffect(() => {
    setRecommendation(null);
    setMessage('');
    setValidation(null);
    if (enabled) void load();
  }, [modelPath, enabled]);

  if (!enabled) return null;

  return <section className="smartLaunchCard">
    <div className="modelInspectorSectionHead">
      <span>SMART LAUNCH</span>
      <small>transparent recommendation · never silently promoted</small>
    </div>

    {busy && !recommendation && <div className="modelInspectorEmpty">BUILDING RECOMMENDATION…</div>}
    {message && <div className="smartLaunchMessage">{message}</div>}

    {recommendation?.profile && <>
      <div className={`smartLaunchStatus smartLaunch${recommendation.status}`}>
        <span>{recommendation.status === 'EVIDENCE_BACKED' ? 'EVIDENCE-BACKED' : 'EXPERIMENTAL'}</span>
        <strong>{recommendation.profile.name}</strong>
        <small>{recommendation.quantization_hint ?? 'quantization unknown'} · {recommendation.profile.context_size.toLocaleString()} ctx · ngl {recommendation.profile.gpu_layers}</small>
      </div>

      <div className="smartLaunchFacts">
        <div><span>RAM CAPACITY</span><b>{gib(recommendation.machine?.ram_total_bytes)}</b></div>
        <div><span>VRAM CAPACITY</span><b>{gib(recommendation.machine?.vram_total_bytes)}</b></div>
        <div><span>PROJECTOR</span><b>{recommendation.profile.projector_path ? recommendation.profile.projector_path.split(/[\\/]/).pop() : 'TEXT-ONLY'}</b></div>
        <div><span>EXTRA ARGS</span><b>{recommendation.profile.extra_args.join(' ') || 'none'}</b></div>
      </div>

      {recommendation.evidence && <div className="smartLaunchEvidence">
        <span>TRUSTWORTHY EVIDENCE</span>
        <strong>{recommendation.evidence.average_tokens_per_second.toFixed(2)} avg tok/s</strong>
        <small>{recommendation.evidence.best_tokens_per_second.toFixed(2)} best · {recommendation.evidence.runs} HEALTHY/TIGHT run(s)</small>
      </div>}

      <ul className="smartLaunchReasons">
        {recommendation.reasons.map((reason, index) => <li key={index}>{reason}</li>)}
      </ul>

      {validation && <div className="smartLaunchValidation">
        <div><span>{validation.finalStatus}</span><strong>{validation.profileName}</strong></div>
        <small>{validation.reusedProfile ? 'reused existing profile' : 'created new experimental profile'} · {validation.runs.length} benchmark run(s)</small>
        {validation.runs.map((run, index) => <p key={index}>RUN {index + 1} · {run.quality} · {Number(run.server_tokens_per_second ?? run.tokens_per_second ?? 0).toFixed(2)} tok/s · RAM {run.ram_avg_percent?.toFixed(1) ?? '—'}% avg</p>)}
        <p>{validation.note}</p>
      </div>}

      <div className="smartLaunchActions">
        <button onClick={() => void load()} disabled={busy}>RECALCULATE</button>
        {recommendation.status === 'EXPERIMENTAL' && <button onClick={() => void validateSuggestion()} disabled={busy}>
          {busy ? 'VALIDATING…' : 'VALIDATE SUGGESTION'}
        </button>}
        <button className="smartLaunchCreate" onClick={() => void createProfile()} disabled={busy}>
          {busy ? 'WORKING…' : 'CREATE SUGGESTED PROFILE'}
        </button>
      </div>
    </>}
  </section>;
}
