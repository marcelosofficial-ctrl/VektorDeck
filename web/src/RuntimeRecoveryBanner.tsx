import { useEffect, useState } from 'react';
import './runtime-recovery.css';

type Runtime = {
  id: string;
  label: string;
  running: boolean;
  pid: number | null;
  recovered?: boolean;
};

export default function RuntimeRecoveryBanner() {
  const [runtime, setRuntime] = useState<Runtime | null>(null);

  async function refresh() {
    try {
      const response = await fetch('/api/runtimes');
      if (!response.ok) return;
      const runtimes: Runtime[] = await response.json();
      setRuntime(runtimes.find(item => item.id === 'llama.cpp' && item.running && item.recovered) ?? null);
    } catch {
      setRuntime(null);
    }
  }

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => window.clearInterval(timer);
  }, []);

  if (!runtime) return null;

  return <div className="runtimeRecoveryBanner" role="status">
    <span>RUNTIME RECOVERED</span>
    <strong>{runtime.label} · PID {runtime.pid ?? '—'}</strong>
    <small>Ownership restored from a validated local launch record.</small>
  </div>;
}
