import { useEffect, useRef, useState } from 'react';
import './profile-manager.css';

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
  is_default: boolean;
};

type Preview = { profile_id: number; command: string[]; display: string };
type RuntimePreflight = {
  state: 'free' | 'managed' | 'external' | 'blocked';
  occupied: boolean;
  llama_compatible: boolean;
  managed: boolean;
  active_profile_id: number | null;
  latency_ms: number | null;
  reason: string;
  owner_pid?: number | null;
  owner_name?: string | null;
};

async function jsonResponse(response: Response) {
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail ?? `HTTP ${response.status}`);
  return data;
}

const argsText = (profile: Profile) => profile.extra_args.join(' ');

export default function ProfileManagerPanel() {
  const [open, setOpen] = useState(false);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [editing, setEditing] = useState<Profile | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [preflight, setPreflight] = useState<RuntimePreflight | null>(null);
  const [message, setMessage] = useState('Profiles are stored locally in SQLite.');
  const [busy, setBusy] = useState(false);
  const drawerRef = useRef<HTMLElement | null>(null);

  async function refresh() {
    try {
      const data: Profile[] = await fetch('/api/profiles').then(jsonResponse);
      setProfiles(data);
      if (editing) setEditing(data.find(profile => profile.id === editing.id) ?? null);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not load profiles.');
    }
  }

  useEffect(() => {
    if (open) void refresh();
  }, [open]);

  async function loadPreflight(profileId: number) {
    try {
      const data: RuntimePreflight = await fetch(`/api/llama/preflight/${profileId}`).then(jsonResponse);
      setPreflight(data);
    } catch (error) {
      setPreflight(null);
      setMessage(error instanceof Error ? error.message : 'Could not inspect the selected profile port.');
    }
  }

  function beginEdit(profile: Profile) {
    setEditing({ ...profile });
    setPreview(null);
    setPreflight(null);
    setMessage(`Editing ${profile.name}. CLOSE returns to the profile list.`);
    window.requestAnimationFrame(() => drawerRef.current?.scrollTo({ top: 0, behavior: 'smooth' }));
    void loadPreflight(profile.id);
  }

  function closeEdit() {
    setEditing(null);
    setPreview(null);
    setPreflight(null);
    setMessage('Profiles are stored locally in SQLite.');
    window.requestAnimationFrame(() => drawerRef.current?.scrollTo({ top: 0, behavior: 'smooth' }));
  }

  function updateField<K extends keyof Profile>(key: K, value: Profile[K]) {
    setEditing(current => current ? { ...current, [key]: value } : current);
    setPreview(null);
  }

  async function loadPreview() {
    if (!editing) return;
    setBusy(true);
    try {
      const data: Preview = await fetch(`/api/profiles/${editing.id}/preview`).then(jsonResponse);
      setPreview(data);
      setMessage('Launch preview generated from the saved profile. Unsaved edits are not included yet.');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not build launch preview.');
    } finally {
      setBusy(false);
    }
  }

  async function copyPreview() {
    if (!preview) return;
    try {
      await navigator.clipboard.writeText(preview.display);
      setMessage('Exact saved launch command copied to clipboard.');
    } catch {
      setMessage('Browser clipboard access was unavailable. Select the command text and copy it manually.');
    }
  }

  async function save() {
    if (!editing) return;
    setBusy(true);
    try {
      await fetch(`/api/profiles/${editing.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: editing.name,
          model_path: editing.model_path,
          projector_path: editing.projector_path || null,
          context_size: editing.context_size,
          gpu_layers: editing.gpu_layers,
          host: editing.host,
          port: editing.port,
          extra_args: editing.extra_args,
        }),
      }).then(jsonResponse);
      setMessage(`Saved ${editing.name}. Reloading the dashboard so selectors stay in sync…`);
      window.setTimeout(() => window.location.reload(), 450);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not save profile.');
    } finally {
      setBusy(false);
    }
  }

  async function makeDefault(profile: Profile) {
    if (profile.is_default) return;
    setBusy(true);
    try {
      await fetch(`/api/profiles/${profile.id}/default`, { method: 'POST' }).then(jsonResponse);
      setMessage(`${profile.name} is now the default profile. Reloading…`);
      window.setTimeout(() => window.location.reload(), 450);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not change the default profile.');
    } finally {
      setBusy(false);
    }
  }

  async function duplicate(profile: Profile) {
    const proposed = `${profile.name} copy`;
    const name = window.prompt('Name for the duplicate profile:', proposed)?.trim();
    if (!name) return;
    setBusy(true);
    try {
      await fetch(`/api/profiles/${profile.id}/duplicate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      }).then(jsonResponse);
      setMessage(`Created ${name}. Reloading the dashboard so selectors stay in sync…`);
      window.setTimeout(() => window.location.reload(), 450);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not duplicate profile.');
    } finally {
      setBusy(false);
    }
  }

  async function remove(profile: Profile) {
    if (!window.confirm(`Delete profile “${profile.name}”?\n\nSaved benchmark history will remain.`)) return;
    setBusy(true);
    try {
      await fetch(`/api/profiles/${profile.id}`, { method: 'DELETE' }).then(jsonResponse);
      setMessage(`Deleted ${profile.name}. Benchmark history was preserved. Reloading…`);
      if (editing?.id === profile.id) setEditing(null);
      window.setTimeout(() => window.location.reload(), 450);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not delete profile.');
    } finally {
      setBusy(false);
    }
  }

  const ownerText = preflight?.owner_pid
    ? `${preflight.owner_name ?? 'process'} · PID ${preflight.owner_pid}`
    : null;

  return <>
    <button className="profileManagerToggle" onClick={() => setOpen(value => !value)} aria-expanded={open}>
      PROFILES
    </button>

    <aside ref={drawerRef} className={`profileManagerDrawer ${open ? 'profileManagerOpen' : ''}`} aria-hidden={!open}>
      <div className="profileManagerHeader">
        <div><span>LOCAL CONFIGURATION</span><strong>{editing ? 'Edit Profile' : 'Profile Manager'}</strong></div>
        <button onClick={() => setOpen(false)} aria-label="Close profile manager">×</button>
      </div>

      <div className="profileManagerMessage">{message}</div>

      {!editing && <section className="profileManagerList">
        {profiles.map(profile => <article key={profile.id} className={profile.is_default ? 'profileManagerDefault' : ''}>
          <div>
            <span>{profile.is_default ? 'EVERYDAY · DEFAULT' : profile.projector_path ? 'VISION' : 'TEXT'}</span>
            <strong>{profile.name}</strong>
            <small>{profile.context_size.toLocaleString()} ctx · ngl {profile.gpu_layers} · port {profile.port}</small>
          </div>
          <div className="profileManagerActions">
            {!profile.is_default && <button onClick={() => void makeDefault(profile)} disabled={busy}>MAKE DEFAULT</button>}
            <button onClick={() => beginEdit(profile)}>EDIT</button>
            <button onClick={() => void duplicate(profile)} disabled={busy}>DUPLICATE</button>
            <button className="profileDelete" onClick={() => void remove(profile)} disabled={busy}>DELETE</button>
          </div>
        </article>)}
      </section>}

      {editing && <section className="profileEditor profileEditorImmediate">
        <div className="profileEditorHead"><span>EDIT PROFILE</span><button onClick={closeEdit}>BACK TO PROFILES</button></div>

        {preflight && <div className={`profilePreflight preflight-${preflight.state}`}>
          <div className="profilePreflightHead"><span>RUNTIME PREFLIGHT</span><strong>{preflight.state.toUpperCase()}</strong></div>
          <small>{preflight.reason}{preflight.latency_ms != null ? ` · ${preflight.latency_ms.toFixed(1)} ms` : ''}</small>
          {ownerText && <small className="profilePreflightOwner">PORT OWNER · {ownerText}</small>}
          <button onClick={() => void loadPreflight(editing.id)}>CHECK AGAIN</button>
        </div>}

        <label>NAME<input value={editing.name} onChange={event => updateField('name', event.target.value)} /></label>
        <label>MODEL PATH<input value={editing.model_path} onChange={event => updateField('model_path', event.target.value)} /></label>
        <label>PROJECTOR PATH<input value={editing.projector_path ?? ''} onChange={event => updateField('projector_path', event.target.value || null)} /></label>
        <div className="profileEditorGrid">
          <label>CONTEXT<input type="number" min="1" value={editing.context_size} onChange={event => updateField('context_size', Number(event.target.value))} /></label>
          <label>GPU LAYERS<input type="number" min="0" value={editing.gpu_layers} onChange={event => updateField('gpu_layers', Number(event.target.value))} /></label>
          <label>HOST<input value={editing.host} onChange={event => updateField('host', event.target.value)} /></label>
          <label>PORT<input type="number" min="1" max="65535" value={editing.port} onChange={event => updateField('port', Number(event.target.value))} /></label>
        </div>
        <label>EXTRA ARGS<input value={argsText(editing)} onChange={event => updateField('extra_args', event.target.value.trim() ? event.target.value.trim().split(/\s+/) : [])} /></label>
        <p>Core launch options are owned by VektorDeck. Extra args are for tuning flags such as parallelism, KV-cache types, flash attention, and image-token settings.</p>
        <div className="profileEditorActions"><button className="profilePreview" onClick={() => void loadPreview()} disabled={busy}>PREVIEW SAVED COMMAND</button><button className="profileSave" onClick={() => void save()} disabled={busy}>{busy ? 'SAVING…' : 'SAVE PROFILE'}</button></div>
        {preview && <div className="profileCommandPreview"><div className="profileCommandHead"><span>EXACT SAVED LAUNCH COMMAND</span><button onClick={() => void copyPreview()}>COPY COMMAND</button></div><pre>{preview.display}</pre></div>}
      </section>}
    </aside>
  </>;
}
