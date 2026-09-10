from __future__ import annotations

import ctypes
import json
import os
import platform
import subprocess
import threading
import time
from pathlib import Path
from typing import Any


class _FileTime(ctypes.Structure):
    _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]

    def value(self) -> int:
        return (self.high << 32) | self.low


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("length", ctypes.c_uint32),
        ("memory_load", ctypes.c_uint32),
        ("total_phys", ctypes.c_uint64),
        ("avail_phys", ctypes.c_uint64),
        ("total_page_file", ctypes.c_uint64),
        ("avail_page_file", ctypes.c_uint64),
        ("total_virtual", ctypes.c_uint64),
        ("avail_virtual", ctypes.c_uint64),
        ("avail_extended_virtual", ctypes.c_uint64),
    ]


def _configured_vram_bytes() -> int | None:
    raw = os.getenv("VEKTORDECK_GPU_VRAM_GB")
    if not raw:
        return None
    try:
        gib = float(raw)
    except ValueError:
        return None
    if gib <= 0:
        return None
    return int(gib * 1024 ** 3)


class TelemetryService:
    """Best-effort local telemetry with no mandatory third-party dependency."""

    def __init__(self, gpu_cache_seconds: float = 3.0) -> None:
        self._lock = threading.Lock()
        self._last_cpu_times = self._windows_cpu_times() if os.name == "nt" else None
        self._gpu_cache_seconds = gpu_cache_seconds
        self._gpu_cached_at = 0.0
        self._gpu_cache: dict[str, Any] = self._empty_gpu()
        self._configured_vram_total = _configured_vram_bytes()

    @staticmethod
    def _empty_gpu() -> dict[str, Any]:
        return {
            "name": None,
            "utilization_percent": None,
            "vram_used_bytes": None,
            "vram_total_bytes": None,
            "source": None,
        }

    @staticmethod
    def _windows_cpu_times() -> tuple[int, int, int] | None:
        if os.name != "nt":
            return None
        idle = _FileTime()
        kernel = _FileTime()
        user = _FileTime()
        ok = ctypes.windll.kernel32.GetSystemTimes(
            ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
        )
        if not ok:
            return None
        return idle.value(), kernel.value(), user.value()

    def _cpu_percent(self) -> float | None:
        if os.name != "nt":
            try:
                load_1m = os.getloadavg()[0]
                cpus = max(os.cpu_count() or 1, 1)
                return round(min(max(load_1m / cpus * 100.0, 0.0), 100.0), 1)
            except (AttributeError, OSError):
                return None

        current = self._windows_cpu_times()
        previous = self._last_cpu_times
        self._last_cpu_times = current
        if current is None or previous is None:
            return None

        idle_delta = current[0] - previous[0]
        kernel_delta = current[1] - previous[1]
        user_delta = current[2] - previous[2]
        total = kernel_delta + user_delta
        if total <= 0:
            return 0.0
        busy = max(total - idle_delta, 0)
        return round(min(busy / total * 100.0, 100.0), 1)

    @staticmethod
    def _windows_memory() -> dict[str, int | float | None]:
        status = _MemoryStatusEx()
        status.length = ctypes.sizeof(_MemoryStatusEx)
        ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        if not ok:
            return {"total_bytes": None, "used_bytes": None, "percent": None}
        used = int(status.total_phys - status.avail_phys)
        return {
            "total_bytes": int(status.total_phys),
            "used_bytes": used,
            "percent": round(float(status.memory_load), 1),
        }

    @staticmethod
    def _linux_memory() -> dict[str, int | float | None]:
        meminfo = Path("/proc/meminfo")
        if not meminfo.is_file():
            return {"total_bytes": None, "used_bytes": None, "percent": None}
        values: dict[str, int] = {}
        try:
            for line in meminfo.read_text(encoding="utf-8").splitlines():
                key, raw = line.split(":", 1)
                values[key] = int(raw.strip().split()[0]) * 1024
        except (OSError, ValueError, IndexError):
            return {"total_bytes": None, "used_bytes": None, "percent": None}
        total = values.get("MemTotal")
        available = values.get("MemAvailable")
        if not total or available is None:
            return {"total_bytes": total, "used_bytes": None, "percent": None}
        used = max(total - available, 0)
        return {
            "total_bytes": total,
            "used_bytes": used,
            "percent": round(used / total * 100.0, 1),
        }

    def _memory(self) -> dict[str, int | float | None]:
        if os.name == "nt":
            return self._windows_memory()
        return self._linux_memory()

    @staticmethod
    def _sample_windows_gpu() -> dict[str, Any]:
        if os.name != "nt":
            return TelemetryService._empty_gpu()

        script = r"""
$ErrorActionPreference = 'SilentlyContinue'
$controllers = @(Get-CimInstance Win32_VideoController | Where-Object { $_.Name })
$gpu = $controllers | Where-Object { $_.Name -match 'Radeon|AMD' } | Select-Object -First 1
if (-not $gpu) { $gpu = $controllers | Select-Object -First 1 }
$usageSamples = @((Get-Counter '\GPU Engine(*)\Utilization Percentage').CounterSamples)
$gpuUtil = $usageSamples | Measure-Object CookedValue -Maximum
$memorySamples = @((Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage').CounterSamples)
$dedicated = $memorySamples | Measure-Object CookedValue -Sum
$reportedTotal = 0
if ($gpu -and $gpu.AdapterRAM) { $reportedTotal = [uint64]$gpu.AdapterRAM }
if ($reportedTotal -lt 8589934592) { $reportedTotal = 0 }
[pscustomobject]@{
  name = if ($gpu) { [string]$gpu.Name } else { $null }
  utilization = if ($gpuUtil.Count -gt 0) { [double]$gpuUtil.Maximum } else { $null }
  used = if ($dedicated.Count -gt 0) { [uint64][math]::Max($dedicated.Sum, 0) } else { $null }
  total = if ($reportedTotal -gt 0) { [uint64]$reportedTotal } else { $null }
} | ConvertTo-Json -Compress
"""
        try:
            completed = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True,
                text=True,
                timeout=8,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if completed.returncode != 0 or not completed.stdout.strip():
                return TelemetryService._empty_gpu()
            payload = json.loads(completed.stdout.strip())
            utilization = payload.get("utilization")
            if utilization is not None:
                utilization = round(min(max(float(utilization), 0.0), 100.0), 1)
            return {
                "name": payload.get("name"),
                "utilization_percent": utilization,
                "vram_used_bytes": int(payload["used"]) if payload.get("used") is not None else None,
                "vram_total_bytes": int(payload["total"]) if payload.get("total") is not None else None,
                "source": "windows-performance-counters",
            }
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError, TypeError, ValueError):
            return TelemetryService._empty_gpu()

    @staticmethod
    def _has_useful_gpu_sample(sample: dict[str, Any]) -> bool:
        return any(
            sample.get(key) is not None
            for key in ("name", "utilization_percent", "vram_used_bytes", "vram_total_bytes")
        )

    def _apply_configured_capacity(self, sample: dict[str, Any]) -> dict[str, Any]:
        if sample.get("vram_total_bytes") is None and self._configured_vram_total is not None:
            sample["vram_total_bytes"] = self._configured_vram_total
            source = sample.get("source") or "configured-capacity"
            if "configured-capacity" not in source:
                source += "+configured-capacity"
            sample["source"] = source
        return sample

    def _gpu(self, *, cached_only: bool = False) -> dict[str, Any]:
        if os.name != "nt":
            return self._empty_gpu()
        now = time.monotonic()
        if cached_only or now - self._gpu_cached_at < self._gpu_cache_seconds:
            return self._apply_configured_capacity(dict(self._gpu_cache))

        sample = self._sample_windows_gpu()
        if self._has_useful_gpu_sample(sample):
            self._gpu_cache = sample
        self._gpu_cache = self._apply_configured_capacity(self._gpu_cache)
        self._gpu_cached_at = now
        return dict(self._gpu_cache)

    def snapshot(self, *, cached_gpu_only: bool = False) -> dict[str, Any]:
        with self._lock:
            return {
                "timestamp": time.time(),
                "platform": platform.system(),
                "cpu": {
                    "utilization_percent": self._cpu_percent(),
                    "logical_processors": os.cpu_count(),
                },
                "memory": self._memory(),
                "gpu": self._gpu(cached_only=cached_gpu_only),
            }
