from __future__ import annotations

import os
import time
from typing import Any

import psutil


def _role(pid: int, name: str) -> str:
    if pid == os.getpid():
        return "vektordeck_backend"
    if pid == 4 or name.casefold() == "system":
        return "system"
    return "user"


def top_processes(limit: int = 8, sample_seconds: float = 0.25) -> list[dict[str, Any]]:
    """Return a bounded, read-only CPU/RAM contaminator snapshot.

    Process CPU is normalized to a whole-machine 0-100 scale. Windows' System
    Idle Process is deliberately excluded because its CPU percentage represents
    unused CPU capacity rather than work that can contaminate a benchmark.
    """
    safe_limit = min(max(int(limit), 1), 20)
    logical_cpus = max(psutil.cpu_count(logical=True) or 1, 1)

    primed: list[psutil.Process] = []
    for process in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            info = process.info
            pid = int(info.get("pid") or process.pid)
            name = str(info.get("name") or "unknown")
            if pid == 0 or name.casefold() == "system idle process":
                continue
            process.cpu_percent(interval=None)
            primed.append(process)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    time.sleep(max(min(float(sample_seconds), 1.0), 0.05))

    rows: list[dict[str, Any]] = []
    for process in primed:
        try:
            info = process.as_dict(attrs=["pid", "name", "memory_info"])
            pid = int(info["pid"])
            name = str(info.get("name") or "unknown")
            raw_cpu = float(process.cpu_percent(interval=None))
            normalized_cpu = raw_cpu / logical_cpus
            memory_info = info.get("memory_info")
            working_set = int(memory_info.rss) if memory_info is not None else 0
            rows.append(
                {
                    "pid": pid,
                    "name": name,
                    "role": _role(pid, name),
                    "cpu_percent": round(normalized_cpu, 1),
                    "memory_bytes": working_set,
                    "memory_mb": round(working_set / (1024 ** 2), 1),
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    rows.sort(
        key=lambda item: (float(item["cpu_percent"]), int(item["memory_bytes"])),
        reverse=True,
    )
    return rows[:safe_limit]
