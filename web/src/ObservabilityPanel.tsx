import { useEffect, useMemo, useState } from 'react';
import './observability.css';

type Advisory = { severity: 'RECOMMENDED' | 'INFO' | 'WARNING'; code: string; title: string; detail: string };
type RuntimeLog = { available: boolean; path: string | null; lines: string[]; advisories?: Advisory[] };
type BenchmarkEvidence = {
  id: number; profile_name: string; server_tokens_per_second: number | null; tokens_per_second: number | null;
  sample_count: number | null; cpu_avg_percent: number | null; cpu_peak_percent: number | null;
  ram_avg_percent: number | null; ram_peak_percent: number | null; gpu_avg_percent: number | null;
  gpu_peak_percent: number | null; vram_avg_bytes: number | null; vram_peak_bytes: number | null;
  vram_total_bytes: number | null; created_at: string; quality?: 'HEALTHY' | 'TIGHT' | 'PRESSURED' | 'UNVERIFIED';
  quality_reasons?: string[];
};

const pct = (value: number | null) => value == null ? '—' : `${value.toFixed(1)}%`;
const gb = (value: number | null) => value == null ? '—' : `${(value / 1024 ** 3).toFixed(2)} GB`;
const speed = (run: BenchmarkEvidence | null) => {
  if (!run) return '—';
  const value = run.server_tokens_per_second ?? run.tokens_per_second;
  return value == null ? '—' : `${Number(value).toFixed(2)} tok/s`;
};

export default function ObservabilityPanel() {
  const [open, setOpen] = useState(false);
  const [log, setLog] = useState<RuntimeLog>({ available: false, path: null, lines: [], advisories: [] });
  const [benchmarks, setBenchmarks] = useState<BenchmarkEvidence[]>([]);

  useEffect(() => {
    let cancelled = false;
    async function refreshLogs() {
      try { const response = await fetch('/api/runtimes/llama.cpp/logs?lines=120'); if (response.ok && !cancelled) setLog(await response.json()); } catch {}
    }
    async function refreshBenchmarks() {
      try { const response = await fetch('/api/benchmarks?limit=10'); if (response.ok && !cancelled) setBenchmarks(await response.json()); } catch {}
    }
    void refreshLogs(); void refreshBenchmarks();
    const logTimer = window.setInterval(() => void refreshLogs(), 2000);
    const benchmarkTimer = window.setInterval(() => void refreshBenchmarks(), 5000);
    return () => { cancelled = true; window.clearInterval(logTimer); window.clearInterval(benchmarkTimer); };
  }, []);

  const latestEvidence = useMemo(() => benchmarks.find(run => (run.sample_count ?? 0) > 0) ?? null, [benchmarks]);
  const quality = latestEvidence?.quality ?? 'UNVERIFIED';
  const qualityMessage = latestEvidence?.quality_reasons?.join(' · ') ?? 'Run a new benchmark to capture hardware evidence.';

  return <>
    <button className="obsToggle" onClick={() => setOpen(value => !value)} aria-expanded={open}><span className="obsDot" /> OBSERVABILITY</button>
    <aside className={`obsDrawer ${open ? 'obsOpen' : ''}`} aria-hidden={!open}>
      <div className="obsHeader"><div><span>RUNTIME EVIDENCE</span><strong>Observability</strong></div><button onClick={() => setOpen(false)} aria-label="Close observability panel">×</button></div>

      <section className="obsEvidence">
        <div className="obsSectionTitle"><span>LATEST BENCHMARK</span><small>{latestEvidence ? `#${String(latestEvidence.id).padStart(3, '0')} · ${latestEvidence.profile_name}` : 'Run a new benchmark to capture hardware evidence'}</small></div>
        <div className={`obsQuality obsQuality${quality}`}><span>RUN QUALITY</span><strong>{quality}</strong><small>{qualityMessage}</small></div>
        <div className="obsMetricGrid">
          <article><span>SPEED</span><strong>{speed(latestEvidence)}</strong><small>{latestEvidence?.sample_count ? `${latestEvidence.sample_count} telemetry samples` : 'no evidence yet'}</small></article>
          <article><span>CPU</span><strong>{pct(latestEvidence?.cpu_avg_percent ?? null)}</strong><small>{pct(latestEvidence?.cpu_peak_percent ?? null)} peak</small></article>
          <article><span>RAM</span><strong>{pct(latestEvidence?.ram_avg_percent ?? null)}</strong><small>{pct(latestEvidence?.ram_peak_percent ?? null)} peak</small></article>
          <article><span>GPU</span><strong>{pct(latestEvidence?.gpu_avg_percent ?? null)}</strong><small>{pct(latestEvidence?.gpu_peak_percent ?? null)} peak</small></article>
          <article><span>VRAM</span><strong>{gb(latestEvidence?.vram_avg_bytes ?? null)}</strong><small>{gb(latestEvidence?.vram_peak_bytes ?? null)} peak</small></article>
        </div>
      </section>

      {(log.advisories?.length ?? 0) > 0 && <section className="obsAdvisories">
        <div className="obsSectionTitle"><span>RUNTIME ADVISORIES</span><small>Parsed from current llama.cpp log</small></div>
        <div className="obsAdvisoryList">{log.advisories!.map(item => <article key={item.code} className={`obsAdvisory obsAdvisory${item.severity}`}><span>{item.severity}</span><strong>{item.title}</strong><small>{item.detail}</small></article>)}</div>
      </section>}

      <section className="obsLogs">
        <div className="obsSectionTitle"><span>LLAMA.CPP LOG TAIL</span><small>{log.available ? log.path : 'log appears after the next llama.cpp launch'}</small></div>
        <pre>{log.lines.length ? log.lines.join('\n') : 'No runtime log captured yet.'}</pre>
      </section>
    </aside>
  </>;
}
