from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _url_host(host: str) -> str:
    normalized = host.strip().lower()
    if normalized not in LOOPBACK_HOSTS:
        raise ValueError("runtime preflight only supports loopback hosts")
    return f"[{normalized}]" if ":" in normalized else normalized


def tcp_port_open(host: str, port: int, timeout_seconds: float = 0.35) -> bool:
    normalized = host.strip().lower()
    if normalized not in LOOPBACK_HOSTS:
        raise ValueError("runtime preflight only supports loopback hosts")
    connect_host = "127.0.0.1" if normalized == "localhost" else normalized
    family = socket.AF_INET6 if ":" in connect_host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.settimeout(timeout_seconds)
    try:
        return sock.connect_ex((connect_host, int(port))) == 0
    except OSError:
        return False
    finally:
        sock.close()


def windows_process_identity(pid: int) -> dict[str, Any]:
    """Return process identity without starting PowerShell on normal polling paths."""
    if os.name != "nt" or int(pid) <= 0:
        return {"owner_pid": None, "owner_name": None, "owner_path": None}

    process_query_limited_information = 0x1000
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        open_process = kernel32.OpenProcess
        open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        open_process.restype = wintypes.HANDLE
        query_image = kernel32.QueryFullProcessImageNameW
        query_image.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        query_image.restype = wintypes.BOOL
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL

        handle = open_process(process_query_limited_information, False, int(pid))
        if not handle:
            return {"owner_pid": None, "owner_name": None, "owner_path": None}
        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not query_image(handle, 0, buffer, ctypes.byref(size)):
                return {"owner_pid": int(pid), "owner_name": None, "owner_path": None}
            path = buffer.value
            return {
                "owner_pid": int(pid),
                "owner_name": Path(path).stem if path else None,
                "owner_path": path or None,
            }
        finally:
            close_handle(handle)
    except (AttributeError, OSError, TypeError, ValueError):
        return {"owner_pid": None, "owner_name": None, "owner_path": None}


def _windows_port_owner(port: int) -> dict[str, Any]:
    if os.name != "nt":
        return {"owner_pid": None, "owner_name": None, "owner_path": None}

    script = f"""
$connection = Get-NetTCPConnection -State Listen -LocalPort {int(port)} -ErrorAction SilentlyContinue | Select-Object -First 1
if ($connection) {{ [int]$connection.OwningProcess }}
"""
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        raw = completed.stdout.strip()
        if completed.returncode != 0 or not raw:
            return {"owner_pid": None, "owner_name": None, "owner_path": None}
        return windows_process_identity(int(raw.splitlines()[-1]))
    except (OSError, subprocess.SubprocessError, TypeError, ValueError):
        return {"owner_pid": None, "owner_name": None, "owner_path": None}


def probe_llama_service(profile: dict, timeout_seconds: float = 0.75) -> dict[str, Any]:
    host = str(profile.get("host", "127.0.0.1"))
    port = int(profile["port"])
    if not tcp_port_open(host, port):
        return {
            "occupied": False,
            "llama_compatible": False,
            "latency_ms": None,
            "models": [],
            "owner_pid": None,
            "owner_name": None,
            "owner_path": None,
        }

    owner = _windows_port_owner(port)
    started = time.perf_counter()
    try:
        url = f"http://{_url_host(host)}:{port}/v1/models"
        with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        models = payload.get("data", []) if isinstance(payload, dict) else []
        return {
            "occupied": True,
            "llama_compatible": True,
            "latency_ms": latency_ms,
            "models": models,
            **owner,
        }
    except (
        urllib.error.URLError,
        OSError,
        TimeoutError,
        json.JSONDecodeError,
        ValueError,
    ):
        return {
            "occupied": True,
            "llama_compatible": False,
            "latency_ms": None,
            "models": [],
            **owner,
        }
