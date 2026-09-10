from __future__ import annotations

import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from .domain import RuntimeState
from .runtime_probe import windows_process_identity

ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
RESERVED_PROFILE_OPTIONS = {
    "-m",
    "--model",
    "-c",
    "--ctx-size",
    "--host",
    "--port",
    "-ngl",
    "--gpu-layers",
    "--mmproj",
    "--cors-origins",
    "--log-file",
}


def _option_name(token: str) -> str:
    return token.split("=", 1)[0]


def _same_path(left: str | Path | None, right: str | Path | None) -> bool:
    if left is None or right is None:
        return False
    return os.path.normcase(os.path.abspath(str(left))) == os.path.normcase(os.path.abspath(str(right)))


def validate_profile_runtime(profile: dict) -> None:
    host = str(profile.get("host", "127.0.0.1")).strip().lower()
    if host not in LOOPBACK_HOSTS:
        raise ValueError(
            "llama.cpp profiles must bind to loopback only: 127.0.0.1, localhost, or ::1"
        )

    blocked = sorted(
        {
            _option_name(str(token))
            for token in profile.get("extra_args", [])
            if _option_name(str(token)) in RESERVED_PROFILE_OPTIONS
        }
    )
    if blocked:
        raise ValueError(
            "extra_args cannot override VektorDeck-managed options: " + ", ".join(blocked)
        )


def build_llama_command(executable: str, profile: dict, log_path: Path | None = None) -> list[str]:
    validate_profile_runtime(profile)

    model_path = Path(profile["model_path"])
    projector_raw = profile.get("projector_path")
    projector_path = Path(projector_raw) if projector_raw else None
    extra_args = [str(arg) for arg in profile.get("extra_args", [])]

    command = [
        executable,
        "-m",
        str(model_path),
        "--ctx-size",
        str(profile["context_size"]),
        "--host",
        str(profile["host"]),
        "--port",
        str(profile["port"]),
        "-ngl",
        str(profile["gpu_layers"]),
    ]
    if projector_path is not None:
        command.extend(["--mmproj", str(projector_path)])

    command.extend(["--cors-origins", "localhost"])
    if log_path is not None:
        command.extend(["--log-file", str(log_path)])

    command.extend(extra_args)
    return command


def _run_llama_text(path: Path | None, argument: str, timeout_seconds: float = 5.0) -> str | None:
    if path is None:
        return None
    target = path.expanduser()
    if not target.is_file():
        return None
    try:
        completed = subprocess.run(
            [str(target), argument],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    output = "\n".join(part.strip() for part in (completed.stdout, completed.stderr) if part.strip())
    return output or None


def inspect_llama_build(path: Path | None, timeout_seconds: float = 4.0) -> str | None:
    output = _run_llama_text(path, "--version", timeout_seconds)
    if not output:
        return None
    return " · ".join(line.strip() for line in output.splitlines() if line.strip())[:240]


def inspect_llama_capabilities(path: Path | None) -> dict[str, bool]:
    help_text = _run_llama_text(path, "--help", 8.0) or ""
    return {
        "parallel": "--parallel" in help_text or "-np" in help_text,
        "cache_type_k": "--cache-type-k" in help_text or "-ctk" in help_text,
        "cache_type_v": "--cache-type-v" in help_text or "-ctv" in help_text,
        "flash_attn": "--flash-attn" in help_text or "-fa" in help_text,
        "image_min_tokens": "--image-min-tokens" in help_text,
        "no_host": "--no-host" in help_text,
    }


def sanitize_log_line(line: str) -> str:
    return ANSI_ESCAPE.sub("", line).rstrip()


class RuntimeManager:
    """Own processes started by this VektorDeck backend instance or safely recovered from a persisted lease."""

    def __init__(self, log_dir: Path | None = None) -> None:
        self._processes: dict[str, subprocess.Popen] = {}
        self._active_llama_profile_id: int | None = None
        self._recovered_llama_pid: int | None = None
        self._recovered_llama_path: str | None = None
        self._log_dir = log_dir.expanduser() if log_dir is not None else None
        self._llama_log_path = self._log_dir / "llama.cpp.log" if self._log_dir is not None else None

    def _live_process(self, runtime_id: str) -> subprocess.Popen | None:
        process = self._processes.get(runtime_id)
        if process is not None and process.poll() is not None:
            self._processes.pop(runtime_id, None)
            if runtime_id == "llama.cpp":
                self._active_llama_profile_id = None
            return None
        return process

    def _recovered_llama_alive(self) -> bool:
        pid = self._recovered_llama_pid
        expected_path = self._recovered_llama_path
        if pid is None or expected_path is None:
            return False
        identity = windows_process_identity(pid)
        if identity.get("owner_pid") != pid or not _same_path(identity.get("owner_path"), expected_path):
            self.clear_recovered_llama()
            return False
        return True

    def recover_llama(self, *, pid: int, profile_id: int, executable_path: str) -> None:
        identity = windows_process_identity(int(pid))
        if identity.get("owner_pid") != int(pid):
            raise ValueError("persisted llama.cpp PID is no longer running")
        if not _same_path(identity.get("owner_path"), executable_path):
            raise ValueError("persisted llama.cpp PID no longer points to the expected executable")
        self._recovered_llama_pid = int(pid)
        self._recovered_llama_path = str(executable_path)
        self._active_llama_profile_id = int(profile_id)

    def clear_recovered_llama(self) -> None:
        self._recovered_llama_pid = None
        self._recovered_llama_path = None
        if self._live_process("llama.cpp") is None:
            self._active_llama_profile_id = None

    def active_llama_profile_id(self) -> int | None:
        if self._live_process("llama.cpp") is not None:
            return self._active_llama_profile_id
        if self._recovered_llama_alive():
            return self._active_llama_profile_id
        return None

    def inspect(self, runtime_id: str, label: str, path: Path | None) -> RuntimeState:
        process = self._live_process(runtime_id)
        recovered = runtime_id == "llama.cpp" and process is None and self._recovered_llama_alive()
        recovered_pid = self._recovered_llama_pid if recovered else None
        running = process is not None or recovered
        pid = process.pid if process else recovered_pid

        if path is None:
            return RuntimeState(
                id=runtime_id,
                label=label,
                configured=False,
                exists=False,
                path=None,
                launchable=False,
                running=running,
                pid=pid,
                recovered=recovered,
            )
        resolved = path.expanduser()
        exists = resolved.is_file()
        return RuntimeState(
            id=runtime_id,
            label=label,
            configured=True,
            exists=exists,
            path=str(resolved),
            launchable=exists and not running,
            running=running,
            pid=pid,
            recovered=recovered,
        )

    def list_runtimes(
        self,
        llama_path: Path | None,
        a1111_path: Path | None,
        hermes_path: Path | None,
    ) -> list[RuntimeState]:
        return [
            self.inspect("llama.cpp", "llama.cpp", llama_path),
            self.inspect("a1111", "AUTOMATIC1111 AMD", a1111_path),
            self.inspect("hermes", "Hermes Desktop", hermes_path),
        ]

    def preview_llama_command(self, path: Path | None, profile: dict) -> list[str]:
        if path is None:
            raise FileNotFoundError("llama.cpp runtime path is not configured")
        target = path.expanduser()
        if not target.is_file():
            raise FileNotFoundError(f"llama.cpp runtime does not exist: {target}")
        return build_llama_command(str(target), profile, self._llama_log_path)

    def launch_a1111(self, path: Path | None) -> RuntimeState:
        state = self.inspect("a1111", "AUTOMATIC1111 AMD", path)
        if state.running:
            return state
        if not state.launchable or state.path is None:
            raise FileNotFoundError("runtime is not launchable: a1111")
        target = Path(state.path)
        creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        if os.name == "nt":
            creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        command = ["cmd.exe", "/c", str(target)] if target.suffix.lower() in {".bat", ".cmd"} else [str(target)]
        process = subprocess.Popen(command, cwd=str(target.parent), creationflags=creationflags)
        self._processes["a1111"] = process
        return self.inspect("a1111", "AUTOMATIC1111 AMD", path)

    def launch_llama(self, path: Path | None, profile: dict) -> RuntimeState:
        state = self.inspect("llama.cpp", "llama.cpp", path)
        if state.running:
            return state
        if not state.launchable or state.path is None:
            raise FileNotFoundError("runtime is not launchable: llama.cpp")

        model_path = Path(profile["model_path"])
        projector_raw = profile.get("projector_path")
        projector_path = Path(projector_raw) if projector_raw else None
        if not model_path.is_file():
            raise FileNotFoundError(f"model file does not exist: {model_path}")
        if projector_path is not None and not projector_path.is_file():
            raise FileNotFoundError(f"projector file does not exist: {projector_path}")

        if self._llama_log_path is not None:
            self._llama_log_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                self._llama_log_path.unlink(missing_ok=True)
            except OSError:
                pass

        command = build_llama_command(state.path, profile, self._llama_log_path)
        creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        if os.name == "nt":
            creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        target = Path(state.path)
        process = subprocess.Popen(command, cwd=str(target.parent), creationflags=creationflags)
        self._processes["llama.cpp"] = process
        self._active_llama_profile_id = int(profile["id"])
        self._recovered_llama_pid = None
        self._recovered_llama_path = None
        return self.inspect("llama.cpp", "llama.cpp", path)

    def read_llama_log(self, lines: int = 200) -> dict[str, object]:
        safe_lines = min(max(int(lines), 1), 1000)
        path = self._llama_log_path
        if path is None or not path.is_file():
            return {"available": False, "path": str(path) if path else None, "lines": []}
        try:
            content = [sanitize_log_line(line) for line in path.read_text(encoding="utf-8", errors="replace").splitlines()]
        except OSError:
            return {"available": False, "path": str(path), "lines": []}
        return {"available": True, "path": str(path), "lines": content[-safe_lines:]}

    def wait_for_llama(self, profile: dict, timeout_seconds: float = 90.0) -> bool:
        host = str(profile.get("host", "127.0.0.1")).strip().lower()
        if host not in LOOPBACK_HOSTS:
            raise ValueError("workspace launch requires a loopback llama.cpp host")
        url_host = f"[{host}]" if ":" in host else host
        url = f"http://{url_host}:{int(profile['port'])}/v1/models"
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self.active_llama_profile_id() is None:
                return False
            try:
                with urllib.request.urlopen(url, timeout=2) as response:
                    if 200 <= response.status < 500:
                        return True
            except (urllib.error.URLError, OSError, TimeoutError):
                pass
            time.sleep(0.5)
        return False

    def launch_hermes(self, path: Path | None) -> RuntimeState:
        state = self.inspect("hermes", "Hermes Desktop", path)
        if state.running:
            return state
        if not state.launchable or state.path is None:
            raise FileNotFoundError("runtime is not launchable: hermes")
        target = Path(state.path)
        creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        if os.name == "nt":
            creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        suffix = target.suffix.lower()
        command = ["cmd.exe", "/c", str(target), "desktop"] if os.name == "nt" and suffix in {".cmd", ".bat"} else [str(target), "desktop"]
        process = subprocess.Popen(command, cwd=str(target.parent), creationflags=creationflags)
        self._processes["hermes"] = process
        return self.inspect("hermes", "Hermes Desktop", path)

    def stop(self, runtime_id: str) -> None:
        process = self._live_process(runtime_id)
        if process is not None:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
            self._processes.pop(runtime_id, None)
            if runtime_id == "llama.cpp":
                self._active_llama_profile_id = None
            return

        if runtime_id == "llama.cpp" and self._recovered_llama_alive():
            pid = self._recovered_llama_pid
            expected_path = self._recovered_llama_path
            if pid is None or expected_path is None:
                return
            identity = windows_process_identity(pid)
            if identity.get("owner_pid") != pid or not _same_path(identity.get("owner_path"), expected_path):
                self.clear_recovered_llama()
                raise RuntimeError("recovered llama.cpp ownership validation failed; process was not stopped")
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            self.clear_recovered_llama()
            return

        if runtime_id == "llama.cpp":
            self.clear_recovered_llama()
