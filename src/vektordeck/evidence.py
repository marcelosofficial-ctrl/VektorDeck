from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any


def _numeric(values: list[Any]) -> list[float]:
    return [float(value) for value in values if isinstance(value, (int, float))]


def _average(values: list[Any]) -> float | None:
    numbers = _numeric(values)
    return round(sum(numbers) / len(numbers), 2) if numbers else None


def _peak(values: list[Any]) -> float | None:
    numbers = _numeric(values)
    return round(max(numbers), 2) if numbers else None


def summarize_snapshots(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    cpu = [sample.get("cpu", {}).get("utilization_percent") for sample in snapshots]
    ram = [sample.get("memory", {}).get("percent") for sample in snapshots]
    gpu = [sample.get("gpu", {}).get("utilization_percent") for sample in snapshots]
    vram_used = [sample.get("gpu", {}).get("vram_used_bytes") for sample in snapshots]
    vram_total = [sample.get("gpu", {}).get("vram_total_bytes") for sample in snapshots]

    numeric_vram = _numeric(vram_used)
    numeric_totals = _numeric(vram_total)
    return {
        "sample_count": len(snapshots),
        "cpu_avg_percent": _average(cpu),
        "cpu_peak_percent": _peak(cpu),
        "ram_avg_percent": _average(ram),
        "ram_peak_percent": _peak(ram),
        "gpu_avg_percent": _average(gpu),
        "gpu_peak_percent": _peak(gpu),
        "vram_avg_bytes": int(round(sum(numeric_vram) / len(numeric_vram))) if numeric_vram else None,
        "vram_peak_bytes": int(max(numeric_vram)) if numeric_vram else None,
        "vram_total_bytes": int(max(numeric_totals)) if numeric_totals else None,
    }


class TelemetryEvidenceRecorder:
    """Sample existing VektorDeck telemetry while a benchmark is running."""

    def __init__(self, snapshot: Callable[[], dict[str, Any]], interval_seconds: float = 1.0) -> None:
        self._snapshot = snapshot
        self._interval_seconds = max(interval_seconds, 0.2)
        self._stop = threading.Event()
        self._samples: list[dict[str, Any]] = []
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="vektordeck-benchmark-evidence", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._samples.append(self._snapshot())
            except Exception:
                # Evidence is supplemental. A telemetry failure must never abort inference.
                pass
            if self._stop.wait(self._interval_seconds):
                break

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
        return summarize_snapshots(self._samples)
