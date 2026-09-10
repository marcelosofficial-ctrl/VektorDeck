from __future__ import annotations

from typing import Any


def _values(samples: list[dict[str, Any]], path: tuple[str, ...]) -> list[float]:
    result: list[float] = []
    for sample in samples:
        value: Any = sample
        for key in path:
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(key)
        if isinstance(value, (int, float)):
            result.append(float(value))
    return result


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def _peak(values: list[float]) -> float | None:
    return round(max(values), 1) if values else None


def assess_idle_baseline(samples: list[dict[str, Any]]) -> dict[str, Any]:
    cpu = _values(samples, ("cpu", "utilization_percent"))
    ram = _values(samples, ("memory", "percent"))
    gpu = _values(samples, ("gpu", "utilization_percent"))

    cpu_avg, cpu_peak = _avg(cpu), _peak(cpu)
    ram_avg, ram_peak = _avg(ram), _peak(ram)
    gpu_avg, gpu_peak = _avg(gpu), _peak(gpu)

    reasons: list[str] = []
    if cpu_avg is not None and cpu_avg >= 55:
        reasons.append(f"background CPU averaged {cpu_avg:.1f}% (target <55%)")
    if cpu_peak is not None and cpu_peak >= 75:
        reasons.append(f"background CPU peaked at {cpu_peak:.1f}% (target <75%)")
    if ram_avg is not None and ram_avg >= 70:
        reasons.append(f"baseline RAM averaged {ram_avg:.1f}% (target <70%)")
    if gpu_avg is not None and gpu_avg >= 55:
        reasons.append(f"background GPU averaged {gpu_avg:.1f}% (target <55%)")

    return {
        "ready": not reasons,
        "sample_count": len(samples),
        "cpu_avg_percent": cpu_avg,
        "cpu_peak_percent": cpu_peak,
        "ram_avg_percent": ram_avg,
        "ram_peak_percent": ram_peak,
        "gpu_avg_percent": gpu_avg,
        "gpu_peak_percent": gpu_peak,
        "reasons": reasons,
    }
