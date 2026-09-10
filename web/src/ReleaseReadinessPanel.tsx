import { useEffect, useState } from 'react';
import './release-readiness.css';

type Check = {
  code: string;
  label: string;
  status: 'PASS' | 'WARN' | 'PENDING' | 'FAIL';
  detail: string;
  blocking: boolean;
};

type Readiness = {
  status: 'READY' | 'READY_WITH_NOTES' | 'BLOCKED';
  checks: Check[];
  blocking_failures: number;
  notes: number;
  summary: string;
};

async function jsonResponse(response: Response) {
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail ?? `HTTP ${response.status}`);
  return data;
}

export default function ReleaseReadinessPanel() {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<Readiness | null>(null);
  const [message, setMessage] = useState('Release readiness has not been checked yet.');
  const [busy, setBusy] = useState(false);
  const [lastChecked, setLastChecked] = useState<string | null>(null);

  async function refresh() {
    if (busy) return;
    setBusy(true);
    setMessage('Checking installation state…');
    try {
      const payload: Readiness = await fetch('/api/release-readiness', { cache: 'no-store' }).then(jsonResponse);
      setData(payload);
      setMessage(payload.summary);
      setLastChecked(new Date().toLocaleString());
    } catch (error) {
      setData(null);
      setMessage(error instanceof Error ? error.message : 'Could not evaluate release readiness.');
      setLastChecked(new Date().toLocaleString());
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (open && data === null && !busy) void refresh();
  }, [open]);

  return <>
    <button className="releaseReadinessToggle" onClick={() => setOpen(value => !value)} aria-expanded={open}>
      READINESS
    </button>

    <aside className={`releaseReadinessDrawer ${open ? 'releaseReadinessOpen' : ''}`} aria-hidden={!open} aria-busy={busy}>
      <div className="releaseReadinessHeader">
        <div><span>RELEASE STATUS</span><strong>Readiness Check</strong></div>
        <button onClick={() => setOpen(false)} aria-label="Close readiness">×</button>
      </div>

      <div className={`releaseReadinessMessage ${busy ? 'releaseReadinessMessageBusy' : ''}`}>
        <span>{message}</span>
        {lastChecked && <small>Last checked {lastChecked}</small>}
      </div>

      {data && <>
        <section className={`releaseReadinessHero status${data.status}`}>
          <span>INSTALLATION STATUS</span>
          <strong>{data.status.replaceAll('_', ' ')}</strong>
          <small>{data.blocking_failures} blocking issue(s) · {data.notes} note(s)</small>
        </section>

        <section className="releaseReadinessChecks">
          {data.checks.map(check => <article key={check.code} className={`readinessCheck check${check.status}`}>
            <div><span>{check.status}</span><strong>{check.label}</strong>{check.blocking && <b>CORE</b>}</div>
            <small>{check.detail}</small>
          </article>)}
        </section>
      </>}

      <div className="releaseReadinessActions">
        <button onClick={() => void refresh()} disabled={busy}>{busy ? 'CHECKING…' : 'RUN READINESS CHECK'}</button>
      </div>
    </aside>
  </>;
}
