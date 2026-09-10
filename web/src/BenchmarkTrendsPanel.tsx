import { useEffect, useMemo, useState } from 'react';
import './benchmark-trends.css';

type RunQuality = 'HEALTHY' | 'TIGHT' | 'PRESSURED' | 'UNVERIFIED';

type Benchmark = {
  id: number;
  profile_id: number;
  profile_name: string;
  server_tokens_per_second: number | null;
  tokens_per_second: number | null;
  ram_avg_percent: number | null;
  ram_peak_percent: number | null;
  gpu_avg_percent: number | null;
  vram_peak_bytes: number | null;
  vram_total_bytes: number | null;
  quality: RunQuality;
  quality_reasons: string[];
  created_at: string;
};

type Protocol = {
  benchmark_id: number;
  protocol_version: number;
  run_source: 'smart_launch' | 'optimizer' | 'manual';
  baseline_ready: boolean;
  baseline_cpu_avg_percent: number | null;
  baseline_ram_avg_percent: number | null;
  baseline_gpu_avg_percent: number | null;
};

type ProfileSummary = {
  name: string;
  runs: number;
  average: number;
  best: number;
};

const speed = (run: Benchmark) => Number(run.server_tokens_per_second ?? run.tokens_per_second ?? 0);
const trustworthy = (run: Benchmark) => run.quality === 'HEALTHY' || run.quality === 'TIGHT';
const localTime = (value: string) => {
  const normalized = value.includes('T') ? value : value.replace(' ', 'T');
  const utc = /Z$|[+-]\d\d:\d\d$/.test(normalized) ? normalized : `${normalized}Z`;
  const date = new Date(utc);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
};

function TrendChart({ values, maxHint }: { values: number[]; maxHint?: number }) {
  if (values.length < 2) return <div className="trendEmpty">Need at least two runs.</div>;
  const width = 520;
  const height = 120;
  const max = Math.max(maxHint ?? 0, ...values, 1);
  const min = Math.min(...values, 0);
  const range = Math.max(max - min, 1);
  const points = values.map((value, index) => {
    const x = (index / (values.length - 1)) * width;
    const y = height - ((value - min) / range) * height;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  return <svg className="trendChart" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-hidden="true">
    <line x1="0" y1={height} x2={width} y2={height} />
    <polyline points={points} vectorEffect="non-scaling-stroke" />
  </svg>;
}

export default function BenchmarkTrendsPanel() {
  const [open, setOpen] = useState(false);
  const [runs, setRuns] = useState<Benchmark[]>([]);
  const [protocols, setProtocols] = useState<Protocol[]>([]);
  const [filter, setFilter] = useState<'ALL' | 'PROTOCOL_V2' | 'TRUSTWORTHY' | RunQuality>('ALL');
  const [message, setMessage] = useState('Benchmark history is stored locally in SQLite.');

  async function refresh() {
    try {
      const [runResponse, protocolResponse] = await Promise.all([
        fetch('/api/benchmarks?limit=100'),
        fetch('/api/benchmark-protocol?limit=100'),
      ]);
      const runData = await runResponse.json();
      const protocolData = await protocolResponse.json();
      if (!runResponse.ok) throw new Error(runData.detail ?? `HTTP ${runResponse.status}`);
      if (!protocolResponse.ok) throw new Error(protocolData.detail ?? `HTTP ${protocolResponse.status}`);
      setRuns(runData);
      setProtocols(protocolData);
      setMessage(`${runData.length} saved run${runData.length === 1 ? '' : 's'} loaded · ${protocolData.length} protocol-v2 record${protocolData.length === 1 ? '' : 's'}.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not load benchmark history.');
    }
  }

  useEffect(() => {
    if (open) void refresh();
  }, [open]);

  const protocolByRun = useMemo(() => new Map(protocols.map(item => [item.benchmark_id, item])), [protocols]);
  const v2Eligible = (run: Benchmark) => {
    const protocol = protocolByRun.get(run.id);
    return Boolean(protocol && protocol.protocol_version >= 2 && protocol.baseline_ready);
  };
  const rankingEligible = (run: Benchmark) => trustworthy(run) && v2Eligible(run);

  const counts = useMemo(() => ({
    healthy: runs.filter(run => run.quality === 'HEALTHY').length,
    tight: runs.filter(run => run.quality === 'TIGHT').length,
    pressured: runs.filter(run => run.quality === 'PRESSURED').length,
    unverified: runs.filter(run => run.quality === 'UNVERIFIED').length,
    protocolV2: runs.filter(v2Eligible).length,
    legacy: runs.filter(run => !protocolByRun.has(run.id)).length,
  }), [runs, protocolByRun]);

  const filtered = useMemo(() => {
    if (filter === 'ALL') return runs;
    if (filter === 'PROTOCOL_V2') return runs.filter(v2Eligible);
    if (filter === 'TRUSTWORTHY') return runs.filter(rankingEligible);
    return runs.filter(run => run.quality === filter);
  }, [runs, filter, protocolByRun]);

  const chronological = useMemo(() => [...filtered].reverse(), [filtered]);
  const speedValues = chronological.map(speed).filter(value => value > 0);
  const ramValues = chronological.map(run => Number(run.ram_avg_percent ?? 0)).filter(value => value > 0);

  const profileSummaries = useMemo<ProfileSummary[]>(() => {
    const groups = new Map<string, number[]>();
    runs.filter(rankingEligible).forEach(run => {
      const value = speed(run);
      if (value <= 0) return;
      groups.set(run.profile_name, [...(groups.get(run.profile_name) ?? []), value]);
    });
    return [...groups.entries()].map(([name, values]) => ({
      name,
      runs: values.length,
      average: values.reduce((sum, value) => sum + value, 0) / values.length,
      best: Math.max(...values),
    })).filter(item => item.runs >= 2).sort((a, b) => b.average - a.average);
  }, [runs, protocolByRun]);

  const bestTrustworthy = profileSummaries[0] ?? null;
  const secondTrustworthy = profileSummaries[1] ?? null;
  const margin = bestTrustworthy && secondTrustworthy && secondTrustworthy.average > 0
    ? ((bestTrustworthy.average - secondTrustworthy.average) / secondTrustworthy.average) * 100
    : null;

  return <>
    <button className="trendsToggle" onClick={() => setOpen(value => !value)} aria-expanded={open}>TRENDS</button>
    <aside className={`trendsDrawer ${open ? 'trendsOpen' : ''}`} aria-hidden={!open}>
      <div className="trendsHeader">
        <div><span>BENCHMARK EVIDENCE</span><strong>Performance Trends</strong></div>
        <button onClick={() => setOpen(false)} aria-label="Close benchmark trends">×</button>
      </div>

      <div className="trendsMessage">{message}</div>

      <section className={`trustConclusion ${bestTrustworthy ? 'trustConclusionReady' : ''}`}>
        <span>PROTOCOL-V2 TRUSTWORTHY CONCLUSION</span>
        {bestTrustworthy ? <>
          <strong>{bestTrustworthy.name}</strong>
          <b>{bestTrustworthy.average.toFixed(2)} avg tok/s</b>
          <small>{bestTrustworthy.runs} quiet-baseline HEALTHY/TIGHT run(s){margin != null ? ` · ${margin.toFixed(1)}% ahead of #2` : ' · more comparison evidence needed'}</small>
        </> : <>
          <strong>NO TRUSTWORTHY WINNER YET</strong>
          <small>Promotion requires at least two protocol-v2 HEALTHY/TIGHT runs with a recorded quiet baseline. Legacy history remains visible but cannot win.</small>
        </>}
      </section>

      <section className="qualityCounts">
        <article><span>PROTOCOL V2</span><strong>{counts.protocolV2}</strong></article>
        <article><span>LEGACY</span><strong>{counts.legacy}</strong></article>
        <article><span>PRESSURED</span><strong>{counts.pressured}</strong></article>
        <article><span>UNVERIFIED</span><strong>{counts.unverified}</strong></article>
      </section>

      <section className="trendFilters">
        {(['ALL', 'PROTOCOL_V2', 'TRUSTWORTHY', 'HEALTHY', 'TIGHT', 'PRESSURED', 'UNVERIFIED'] as const).map(value =>
          <button key={value} className={filter === value ? 'trendFilterActive' : ''} onClick={() => setFilter(value)}>{value}</button>
        )}
      </section>

      <section className="trendBlock">
        <div><span>GENERATION SPEED</span><small>{filtered.length} filtered run(s)</small></div>
        <TrendChart values={speedValues} />
        <small>Oldest → newest · tok/s</small>
      </section>

      <section className="trendBlock">
        <div><span>RAM PRESSURE</span><small>selected evidence only</small></div>
        <TrendChart values={ramValues} maxHint={100} />
        <small>Oldest → newest · average RAM % during inference</small>
      </section>

      <section className="trustworthyRanking">
        <div className="trustworthyRankingHead"><span>PROTOCOL-V2 PROFILE AVERAGES</span><small>quiet baseline + HEALTHY/TIGHT + 2 runs minimum</small></div>
        {profileSummaries.length === 0 && <div className="trendEmpty">No protocol-v2 profile has enough trustworthy evidence yet.</div>}
        {profileSummaries.map((profile, index) => <div className="trustworthyRow" key={profile.name}>
          <span>{String(index + 1).padStart(2, '0')}</span>
          <strong>{profile.name}</strong>
          <b>{profile.average.toFixed(2)} avg tok/s</b>
          <small>{profile.best.toFixed(2)} best · {profile.runs} run(s)</small>
        </div>)}
      </section>

      <section className="trendHistory">
        {filtered.slice(0, 30).map(run => {
          const protocol = protocolByRun.get(run.id);
          return <article key={run.id}>
            <span>#{String(run.id).padStart(3, '0')}</span>
            <div>
              <strong>{run.profile_name}</strong>
              <small>{localTime(run.created_at)} · {protocol ? `v${protocol.protocol_version} ${protocol.run_source.replace('_', ' ')}` : 'legacy protocol'}</small>
            </div>
            <b>{speed(run).toFixed(2)} tok/s</b>
            <em className={`qualityTag quality${run.quality}`}>{run.quality}</em>
          </article>;
        })}
      </section>
    </aside>
  </>;
}
