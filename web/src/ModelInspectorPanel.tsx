import { useEffect, useMemo, useState } from 'react';
import SmartLaunchRecommendation from './SmartLaunchRecommendation';
import './model-inspector.css';

type Intelligence = {
  path: string;
  modified_ns: number;
  size_bytes: number;
  status: 'ok' | 'error';
  error: string | null;
  gguf_version: number | null;
  tensor_count: number | null;
  metadata_count: number | null;
  architecture: string | null;
  display_name: string | null;
  context_length: number | null;
  parameter_count: number | null;
  size_label: string | null;
  file_type: number | null;
  quantization_version: number | null;
  metadata: Record<string, unknown>;
  inspected_at: string;
  kind?: 'model' | 'projector' | 'unknown';
  indexed_name?: string;
};

type PairCandidate = { path: string; name: string; score: number; reasons: string[] };
type Pairing = {
  model_path: string;
  model_name: string;
  recommended_projector: PairCandidate | null;
  candidates: PairCandidate[];
};

type ReadinessReason = { level: 'OK' | 'WARN' | 'BLOCKED'; message: string };
type ProfileReadiness = {
  profile_id: number;
  profile_name: string;
  status: 'READY' | 'WARN' | 'BLOCKED';
  model_path: string;
  projector_path: string | null;
  quantization_hint: string | null;
  architecture: string | null;
  advertised_context: number | null;
  requested_context: number;
  reasons: ReadinessReason[];
};

type ScanResult = {
  candidates: number;
  inspected: number;
  cached: number;
  errors: number;
  results: Intelligence[];
  pairings: Pairing[];
  profiles: ProfileReadiness[];
};

const gb = (bytes: number) => `${(bytes / 1024 ** 3).toFixed(2)} GB`;
const compactNumber = (value: number | null) => {
  if (value == null) return '—';
  if (value >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(1)}B`;
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  return value.toLocaleString();
};
const quantizationHint = (path: string) => {
  const name = (path.split(/[\\/]/).pop() ?? path).toUpperCase();
  const match = name.match(/(IQ\d(?:_[A-Z0-9]+)+|Q\d(?:_[A-Z0-9]+)+|BF16|F16|F32)/);
  return match?.[1] ?? null;
};
const samePath = (left: string | null | undefined, right: string | null | undefined) =>
  Boolean(left && right && left.replace(/\\/g, '/').toLowerCase() === right.replace(/\\/g, '/').toLowerCase());

async function jsonResponse(response: Response) {
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail ?? `HTTP ${response.status}`);
  return data;
}

export default function ModelInspectorPanel() {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Intelligence[]>([]);
  const [pairings, setPairings] = useState<Pairing[]>([]);
  const [profiles, setProfiles] = useState<ProfileReadiness[]>([]);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [kindFilter, setKindFilter] = useState<'ALL' | 'MODEL' | 'PROJECTOR'>('ALL');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('GGUF metadata is read locally without loading models into VRAM.');

  async function refreshList() {
    try {
      const [metadata, pairingData, profileData] = await Promise.all([
        fetch('/api/model-intelligence').then(jsonResponse),
        fetch('/api/model-intelligence/pairings').then(jsonResponse),
        fetch('/api/model-intelligence/profiles').then(jsonResponse),
      ]);
      setItems(metadata);
      setPairings(pairingData);
      setProfiles(profileData);
      setSelectedPath(current => current ?? metadata[0]?.path ?? null);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not load model metadata.');
    }
  }

  async function scan() {
    setBusy(true);
    setMessage('Inspecting changed GGUF metadata and compatibility…');
    try {
      const result: ScanResult = await fetch('/api/model-intelligence/scan', { method: 'POST' }).then(jsonResponse);
      setItems(result.results);
      setPairings(result.pairings ?? []);
      setProfiles(result.profiles ?? []);
      setSelectedPath(current => current ?? result.results[0]?.path ?? null);
      setMessage(`Metadata ready · ${result.inspected} inspected · ${result.cached} cached · ${result.errors} error(s)`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Model inspection failed.');
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (open) void refreshList();
  }, [open]);

  const filteredItems = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return items.filter(item => {
      if (kindFilter === 'MODEL' && item.kind !== 'model') return false;
      if (kindFilter === 'PROJECTOR' && item.kind !== 'projector') return false;
      if (!needle) return true;
      const haystack = [
        item.display_name,
        item.indexed_name,
        item.path,
        item.architecture,
        quantizationHint(item.path),
      ].filter(Boolean).join(' ').toLowerCase();
      return haystack.includes(needle);
    });
  }, [items, query, kindFilter]);

  const selected = useMemo(
    () => items.find(item => item.path === selectedPath) ?? null,
    [items, selectedPath],
  );

  const metadataRows = useMemo(() => {
    if (!selected) return [];
    return Object.entries(selected.metadata)
      .filter(([key, value]) => (
        key.startsWith('general.')
        || key.endsWith('.context_length')
        || key.endsWith('.block_count')
        || key.includes('embedding_length')
        || key.includes('attention.head_count')
      ) && (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean'))
      .slice(0, 18);
  }, [selected]);

  const selectedQuantization = selected ? quantizationHint(selected.path) : null;
  const selectedPairing = useMemo(
    () => pairings.find(item => samePath(item.model_path, selectedPath)) ?? null,
    [pairings, selectedPath],
  );
  const selectedProfiles = useMemo(
    () => profiles.filter(profile => samePath(profile.model_path, selectedPath)),
    [profiles, selectedPath],
  );

  return <>
    <button className="modelInspectorToggle" onClick={() => setOpen(value => !value)} aria-expanded={open}>
      MODELS
    </button>

    <aside className={`modelInspectorDrawer ${open ? 'modelInspectorOpen' : ''}`} aria-hidden={!open}>
      <div className="modelInspectorHeader">
        <div><span>LOCAL MODEL INTELLIGENCE</span><strong>Model Inspector</strong></div>
        <button onClick={() => setOpen(false)} aria-label="Close model inspector">×</button>
      </div>

      <div className="modelInspectorToolbar">
        <p>{message}</p>
        <button onClick={() => void scan()} disabled={busy}>{busy ? 'INSPECTING…' : 'REFRESH METADATA'}</button>
      </div>

      <div className="modelInspectorSearch">
        <input
          value={query}
          onChange={event => setQuery(event.target.value)}
          placeholder="Search model, path, architecture or quantization…"
          aria-label="Search model library"
        />
        <div>
          {(['ALL', 'MODEL', 'PROJECTOR'] as const).map(value => <button
            key={value}
            className={kindFilter === value ? 'active' : ''}
            onClick={() => setKindFilter(value)}
          >{value}</button>)}
        </div>
      </div>

      <div className="modelInspectorBody">
        <nav className="modelInspectorList">
          {items.length === 0 && <div className="modelInspectorEmpty">No GGUF metadata cached yet. Click REFRESH METADATA.</div>}
          {items.length > 0 && filteredItems.length === 0 && <div className="modelInspectorEmpty">No indexed GGUF assets match this filter.</div>}
          {filteredItems.map(item => <button
            key={item.path}
            className={item.path === selectedPath ? 'selected' : ''}
            onClick={() => setSelectedPath(item.path)}
          >
            <span>{item.kind === 'projector' ? 'PROJECTOR' : item.status === 'ok' ? (item.architecture ?? 'MODEL') : 'ERROR'}</span>
            <strong>{item.display_name ?? item.indexed_name ?? item.path.split(/[\\/]/).pop()}</strong>
            <small>{gb(item.size_bytes)} · {quantizationHint(item.path) ?? `GGUF ${item.gguf_version ?? '—'}`}</small>
          </button>)}
        </nav>

        <section className="modelInspectorDetail">
          {!selected && <div className="modelInspectorEmpty">Select a model to inspect it.</div>}
          {selected && <>
            <div className="modelInspectorTitle">
              <span>{selected.kind === 'projector' ? 'PROJECTOR' : selected.status === 'ok' ? 'INSPECTED MODEL' : 'INSPECTION ERROR'}</span>
              <h2>{selected.display_name ?? selected.indexed_name ?? selected.path.split(/[\\/]/).pop()}</h2>
              <p>{selected.path}</p>
            </div>

            {selected.status === 'error' ? <div className="modelInspectorError">{selected.error}</div> : <>
              <div className="modelInspectorMetrics">
                <article><span>ARCHITECTURE</span><strong>{selected.architecture ?? '—'}</strong></article>
                <article><span>CONTEXT</span><strong>{selected.context_length?.toLocaleString() ?? '—'}</strong></article>
                <article><span>TENSORS</span><strong>{compactNumber(selected.tensor_count)}</strong></article>
                <article><span>PARAMETERS</span><strong>{selected.size_label ?? compactNumber(selected.parameter_count)}</strong></article>
                <article><span>QUANTIZATION</span><strong>{selectedQuantization ?? (selected.file_type != null ? `TYPE ${selected.file_type}` : '—')}</strong></article>
                <article><span>METADATA</span><strong>{compactNumber(selected.metadata_count)}</strong></article>
              </div>

              <div className="modelInspectorFacts">
                <div><span>ASSET KIND</span><b>{(selected.kind ?? 'unknown').toUpperCase()}</b></div>
                <div><span>GGUF VERSION</span><b>{selected.gguf_version ?? '—'}</b></div>
                <div><span>FILE TYPE</span><b>{selected.file_type ?? '—'}</b></div>
                <div><span>QUANTIZATION VERSION</span><b>{selected.quantization_version ?? '—'}</b></div>
                <div><span>FILE SIZE</span><b>{gb(selected.size_bytes)}</b></div>
              </div>

              {selected.kind === 'model' && selectedPairing && <div className="modelInspectorCompatibility">
                <div className="modelInspectorSectionHead"><span>PROJECTOR PAIRING</span><small>local evidence only · never auto-applied</small></div>
                {selectedPairing.recommended_projector ? <div className="pairingRecommendation">
                  <span>RECOMMENDED</span>
                  <strong>{selectedPairing.recommended_projector.name}</strong>
                  <small>{selectedPairing.recommended_projector.reasons.join(' · ')}</small>
                  <code>{selectedPairing.recommended_projector.path}</code>
                </div> : <div className="modelInspectorEmpty">No strong projector pairing signal found.</div>}
              </div>}

              {selected.kind === 'model' && <div className="modelInspectorCompatibility">
                <div className="modelInspectorSectionHead"><span>PROFILE READINESS</span><small>indexed assets + GGUF metadata + local safety rules</small></div>
                {selectedProfiles.length === 0 && <div className="modelInspectorEmpty">No saved profiles currently use this model.</div>}
                {selectedProfiles.map(profile => <article className={`readinessCard readiness${profile.status}`} key={profile.profile_id}>
                  <div><span>{profile.status}</span><strong>{profile.profile_name}</strong></div>
                  <small>{profile.quantization_hint ?? 'quantization unknown'} · requested {profile.requested_context.toLocaleString()} ctx{profile.advertised_context ? ` · GGUF ${profile.advertised_context.toLocaleString()} max` : ''}</small>
                  <ul>{profile.reasons.map((reason, index) => <li key={`${reason.level}-${index}`}><b>{reason.level}</b>{reason.message}</li>)}</ul>
                </article>)}
              </div>}

              <SmartLaunchRecommendation modelPath={selected.path} enabled={selected.kind === 'model'} />

              <div className="modelInspectorMetadata">
                <div className="modelInspectorSectionHead"><span>KEY METADATA</span><small>bounded local GGUF header read</small></div>
                {metadataRows.length === 0 && <div className="modelInspectorEmpty">No additional scalar metadata selected for display.</div>}
                {metadataRows.map(([key, value]) => <div key={key}><span>{key}</span><b>{String(value)}</b></div>)}
              </div>
            </>}
          </>}
        </section>
      </div>
    </aside>
  </>;
}
