from __future__ import annotations

import os
import time

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from . import __version__
from .benchmark import check_llama_health, run_benchmark
from .config import Settings
from .database import ModelRepository
from .evidence import TelemetryEvidenceRecorder
from .preflight import assess_idle_baseline
from .profiles_api import build_profile_router
from .quality import classify_benchmark, llama_advisories
from .runtime import RuntimeManager, inspect_llama_build, inspect_llama_capabilities
from .runtime_probe import probe_llama_service
from .scanner import scan_roots
from .telemetry import TelemetryService


class ScanResult(BaseModel):
    discovered: int
    indexed: int


class LaunchResult(BaseModel):
    id: str
    label: str
    running: bool
    pid: int | None


class WorkspaceLaunchResult(BaseModel):
    llama_pid: int | None
    hermes_pid: int | None
    ready: bool


def _same_path(left: str | None, right: str | None) -> bool:
    if left is None or right is None:
        return False
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    repository = ModelRepository(settings.database_path)
    repository.initialize()
    manager = RuntimeManager(settings.data_dir / "logs")
    telemetry = TelemetryService()
    llama_build_fallback = inspect_llama_build(settings.llama_server_path)
    llama_capabilities = inspect_llama_capabilities(settings.llama_server_path)

    def recover_persisted_llama() -> bool:
        lease = repository.get_runtime_lease("llama.cpp")
        if lease is None:
            return False
        profile_id = lease.get("profile_id")
        if profile_id is None:
            repository.clear_runtime_lease("llama.cpp")
            return False
        profile = repository.get_profile(int(profile_id))
        expected_executable = str(settings.llama_server_path) if settings.llama_server_path else None
        if (
            profile is None
            or expected_executable is None
            or not _same_path(str(lease.get("executable_path")), expected_executable)
            or str(lease.get("host")) != str(profile.get("host"))
            or int(lease.get("port") or 0) != int(profile.get("port") or 0)
            or not _same_path(str(lease.get("model_path")), str(profile.get("model_path")))
        ):
            repository.clear_runtime_lease("llama.cpp")
            return False

        probe = probe_llama_service(profile)
        if (
            not probe.get("occupied")
            or not probe.get("llama_compatible")
            or int(probe.get("owner_pid") or 0) != int(lease.get("pid") or 0)
            or not _same_path(probe.get("owner_path"), expected_executable)
        ):
            repository.clear_runtime_lease("llama.cpp")
            return False

        try:
            manager.recover_llama(
                pid=int(lease["pid"]),
                profile_id=int(profile["id"]),
                executable_path=expected_executable,
            )
        except ValueError:
            repository.clear_runtime_lease("llama.cpp")
            return False
        return True

    recover_persisted_llama()

    app = FastAPI(title="VektorDeck", version=__version__)
    app.include_router(build_profile_router(repository, manager, settings.llama_server_path))

    def persist_llama_lease(profile: dict, pid: int | None) -> None:
        if pid is None or settings.llama_server_path is None:
            return
        command = manager.preview_llama_command(settings.llama_server_path, profile)
        repository.set_runtime_lease(
            runtime_id="llama.cpp",
            pid=int(pid),
            profile_id=int(profile["id"]),
            executable_path=str(settings.llama_server_path),
            host=str(profile["host"]),
            port=int(profile["port"]),
            model_path=str(profile["model_path"]),
            command=command,
        )

    def reconcile_llama_lease() -> None:
        lease = repository.get_runtime_lease("llama.cpp")
        if lease is None:
            return
        if manager.active_llama_profile_id() is None:
            repository.clear_runtime_lease("llama.cpp")

    def stop_managed_runtime(runtime_id: str) -> None:
        try:
            manager.stop(runtime_id)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if runtime_id == "llama.cpp":
            repository.clear_runtime_lease("llama.cpp")

    def llama_preflight_state(profile: dict) -> dict:
        active_profile_id = manager.active_llama_profile_id()
        if active_profile_id is not None:
            state = manager.inspect("llama.cpp", "llama.cpp", settings.llama_server_path)
            return {
                "state": "managed" if active_profile_id == int(profile["id"]) else "blocked",
                "occupied": True,
                "llama_compatible": True,
                "managed": True,
                "recovered": state.recovered,
                "active_profile_id": active_profile_id,
                "latency_ms": None,
                "owner_pid": state.pid,
                "owner_name": "VektorDeck",
                "owner_path": state.path,
                "reason": (
                    "this profile is already running under VektorDeck"
                    if active_profile_id == int(profile["id"])
                    else "another VektorDeck-managed llama.cpp profile is already running"
                ),
            }

        probe = probe_llama_service(profile)
        if not probe["occupied"]:
            state = "free"
            reason = "profile port is free"
        elif probe["llama_compatible"]:
            state = "external"
            reason = "a llama-compatible server is already listening on this profile port"
        else:
            state = "blocked"
            reason = "another process is already listening on this profile port"

        return {
            "state": state,
            "managed": False,
            "recovered": False,
            "active_profile_id": None,
            "reason": reason,
            **probe,
        }

    def owner_suffix(preflight: dict) -> str:
        pid = preflight.get("owner_pid")
        name = preflight.get("owner_name")
        if pid is None and not name:
            return ""
        if pid is not None and name:
            return f" Owner: {name} (PID {pid})."
        if pid is not None:
            return f" Owner PID: {pid}."
        return f" Owner: {name}."

    def require_launchable_profile(profile: dict) -> None:
        preflight = llama_preflight_state(profile)
        if preflight["state"] == "free":
            return
        if preflight["state"] == "managed" and preflight["active_profile_id"] == int(profile["id"]):
            return
        suffix = owner_suffix(preflight)
        if preflight["state"] == "external":
            raise HTTPException(
                status_code=409,
                detail=(
                    f"port {profile['port']} already has an external llama-compatible server. "
                    "VektorDeck will not replace or stop a process it does not own."
                    f"{suffix}"
                ),
            )
        raise HTTPException(
            status_code=409,
            detail=(
                f"port {profile['port']} is blocked by another process; choose another port or stop that process first."
                f"{suffix}"
            ),
        )

    @app.get("/")
    def root() -> dict:
        return {
            "name": "VektorDeck API",
            "version": __version__,
            "status": "ok",
            "ui": "http://localhost:5173/",
            "docs": "/docs",
            "health": "/api/health",
            "telemetry": "/api/telemetry",
        }

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "version": __version__, "database": repository.integrity()}

    @app.get("/api/telemetry")
    def telemetry_snapshot() -> dict:
        return telemetry.snapshot()

    @app.get("/api/runtimes")
    def runtimes() -> list[dict]:
        states = [
            state.__dict__
            for state in manager.list_runtimes(
                settings.llama_server_path,
                settings.a1111_launch_path,
                settings.hermes_cli_path,
            )
        ]
        reconcile_llama_lease()
        return states

    @app.get("/api/runtime")
    def runtime_compat() -> dict:
        return runtimes()[0]

    @app.get("/api/runtimes/llama.cpp/logs")
    def llama_logs(lines: int = 200) -> dict:
        payload = manager.read_llama_log(lines=lines)
        payload["advisories"] = llama_advisories(payload.get("lines", []))
        return payload

    @app.get("/api/llama/active")
    def llama_active() -> dict:
        reconcile_llama_lease()
        return {"profile_id": manager.active_llama_profile_id()}

    @app.get("/api/llama/capabilities")
    def llama_capability_snapshot() -> dict:
        return {"build": llama_build_fallback, "capabilities": llama_capabilities}

    @app.get("/api/llama/preflight/{profile_id}")
    def llama_preflight(profile_id: int) -> dict:
        profile = repository.get_profile(profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="launch profile not found")
        try:
            return llama_preflight_state(profile)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/optimizer/preflight")
    def optimizer_preflight() -> dict:
        active = [state for state in runtimes() if state["running"]]
        if active:
            return {
                "ready": False,
                "sample_count": 0,
                "reasons": ["stop all VektorDeck-managed AI runtimes before optimizer preflight"],
                "active_runtimes": [item["id"] for item in active],
            }

        samples: list[dict] = []
        for index in range(6):
            samples.append(telemetry.snapshot(cached_gpu_only=True))
            if index < 5:
                time.sleep(0.75)
        result = assess_idle_baseline(samples)
        result["active_runtimes"] = []
        return result

    @app.post("/api/runtimes/a1111/launch", response_model=LaunchResult)
    def launch_a1111() -> LaunchResult:
        try:
            state = manager.launch_a1111(settings.a1111_launch_path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return LaunchResult(id=state.id, label=state.label, running=state.running, pid=state.pid)

    @app.post("/api/runtimes/hermes/launch", response_model=LaunchResult)
    def launch_hermes() -> LaunchResult:
        try:
            state = manager.launch_hermes(settings.hermes_cli_path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return LaunchResult(id=state.id, label=state.label, running=state.running, pid=state.pid)

    @app.post("/api/runtimes/llama.cpp/launch/{profile_id}", response_model=LaunchResult)
    def launch_llama(profile_id: int) -> LaunchResult:
        profile = repository.get_profile(profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="launch profile not found")
        require_launchable_profile(profile)
        try:
            state = manager.launch_llama(settings.llama_server_path, profile)
            if not manager.wait_for_llama(profile):
                stop_managed_runtime("llama.cpp")
                raise HTTPException(status_code=504, detail="llama.cpp did not become ready in time")
            persist_llama_lease(profile, state.pid)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return LaunchResult(id=state.id, label=state.label, running=state.running, pid=state.pid)

    @app.get("/api/llama/health/{profile_id}")
    def llama_health(profile_id: int) -> dict:
        profile = repository.get_profile(profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="launch profile not found")
        if manager.active_llama_profile_id() != profile_id:
            return {"online": False, "latency_ms": None, "models": [], "active_profile_match": False}
        try:
            result = check_llama_health(profile)
            if result.get("build_info") is None and llama_build_fallback:
                result["build_info"] = llama_build_fallback
                result["build_info_source"] = "executable"
            return {**result, "active_profile_match": True}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/benchmarks/{profile_id}")
    def benchmark_profile(profile_id: int) -> dict:
        profile = repository.get_profile(profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="launch profile not found")
        if manager.active_llama_profile_id() != profile_id:
            raise HTTPException(status_code=409, detail="selected profile is not the active llama.cpp profile")
        health = check_llama_health(profile)
        if not health["online"]:
            raise HTTPException(status_code=409, detail="llama.cpp is not responding for this profile")

        recorder = TelemetryEvidenceRecorder(lambda: telemetry.snapshot(cached_gpu_only=True), interval_seconds=1.0)
        recorder.start()
        try:
            result = run_benchmark(profile)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        finally:
            evidence = recorder.stop()
        saved = repository.save_benchmark(profile, result, evidence)
        return {**saved, **classify_benchmark(saved), "response_preview": result["response_preview"]}

    @app.get("/api/benchmarks")
    def benchmark_history(limit: int = 20) -> list[dict]:
        return [{**run, **classify_benchmark(run)} for run in repository.list_benchmarks(limit=limit)]

    @app.post("/api/workspace/launch/{profile_id}", response_model=WorkspaceLaunchResult)
    def launch_workspace(profile_id: int) -> WorkspaceLaunchResult:
        profile = repository.get_profile(profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="launch profile not found")
        require_launchable_profile(profile)
        try:
            llama = manager.launch_llama(settings.llama_server_path, profile)
            if not manager.wait_for_llama(profile):
                stop_managed_runtime("llama.cpp")
                raise HTTPException(status_code=504, detail="llama.cpp did not become ready in time")
            persist_llama_lease(profile, llama.pid)
            hermes = manager.launch_hermes(settings.hermes_cli_path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return WorkspaceLaunchResult(llama_pid=llama.pid, hermes_pid=hermes.pid, ready=True)

    @app.post("/api/workspace/stop")
    def stop_workspace() -> dict:
        manager.stop("hermes")
        stop_managed_runtime("llama.cpp")
        return {"running": False}

    @app.post("/api/runtimes/{runtime_id}/stop")
    def stop_runtime(runtime_id: str) -> dict:
        if runtime_id not in {"llama.cpp", "a1111", "hermes"}:
            raise HTTPException(status_code=404, detail="unknown runtime")
        stop_managed_runtime(runtime_id) if runtime_id == "llama.cpp" else manager.stop(runtime_id)
        return {"id": runtime_id, "running": False}

    @app.get("/api/models")
    def models() -> list[dict]:
        return repository.list_models()

    @app.post("/api/scan", response_model=ScanResult)
    def scan() -> ScanResult:
        discovered = scan_roots(settings.model_roots, settings.image_model_roots)
        return ScanResult(discovered=len(discovered), indexed=repository.upsert_many(discovered))

    return app


app = create_app()
