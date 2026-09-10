from pathlib import Path

from fastapi.testclient import TestClient

import vektordeck.api as api_module
import vektordeck.runtime as runtime_module
from vektordeck.api import create_app
from vektordeck.config import Settings
from vektordeck.database import ModelRepository


def test_health_scan_runtimes_profiles_telemetry_and_logs(tmp_path: Path) -> None:
    models = tmp_path / "models"
    images = tmp_path / "images"
    models.mkdir()
    images.mkdir()
    model = models / "demo.gguf"
    projector = models / "mmproj-demo.gguf"
    llama_server = tmp_path / "llama-server.exe"
    model.write_bytes(b"demo")
    projector.write_bytes(b"vision")
    llama_server.write_bytes(b"not-a-real-executable")
    (images / "dream.safetensors").write_bytes(b"image")

    settings = Settings(
        data_dir=tmp_path / "data",
        database_path=tmp_path / "data" / "db.sqlite3",
        model_roots=(models,),
        image_model_roots=(images,),
        llama_server_path=llama_server,
        a1111_launch_path=None,
        hermes_cli_path=None,
    )
    client = TestClient(create_app(settings))

    root = client.get("/").json()
    assert root["name"] == "VektorDeck API"
    assert root["docs"] == "/docs"
    assert root["telemetry"] == "/api/telemetry"
    assert client.get("/api/health").json()["database"] == "ok"

    telemetry = client.get("/api/telemetry").json()
    assert telemetry["platform"]
    assert "utilization_percent" in telemetry["cpu"]
    assert "percent" in telemetry["memory"]
    assert "utilization_percent" in telemetry["gpu"]

    runtimes = client.get("/api/runtimes").json()
    assert [item["id"] for item in runtimes] == ["llama.cpp", "a1111", "hermes"]
    assert runtimes[0]["recovered"] is False

    logs = client.get("/api/runtimes/llama.cpp/logs?lines=25").json()
    assert logs["available"] is False
    assert logs["lines"] == []
    assert logs["path"].endswith("llama.cpp.log")

    scan = client.post("/api/scan").json()
    assert scan["discovered"] == 3

    indexed = client.get("/api/models").json()
    assert {item["kind"] for item in indexed} == {"model", "projector", "checkpoint"}

    response = client.post(
        "/api/profiles",
        json={
            "name": "test profile",
            "model_path": str(model),
            "projector_path": str(projector),
            "context_size": 8192,
            "gpu_layers": 99,
            "host": "127.0.0.1",
            "port": 8080,
            "extra_args": ["--parallel", "1"],
        },
    )
    assert response.status_code == 201
    created = response.json()
    assert created["name"] == "test profile"
    assert created["is_default"] is True

    preview = client.get(f"/api/profiles/{created['id']}/preview")
    assert preview.status_code == 200
    preview_data = preview.json()
    assert preview_data["command"][0] == str(llama_server)
    assert "--cors-origins" in preview_data["command"]
    assert "--parallel" in preview_data["command"]

    unsafe_host = client.post(
        "/api/profiles",
        json={
            "name": "unsafe host",
            "model_path": str(model),
            "context_size": 8192,
            "gpu_layers": 99,
            "host": "0.0.0.0",
            "port": 8080,
        },
    )
    assert unsafe_host.status_code == 400

    unsafe_args = client.post(
        "/api/profiles",
        json={
            "name": "unsafe args",
            "model_path": str(model),
            "context_size": 8192,
            "gpu_layers": 99,
            "host": "127.0.0.1",
            "port": 8080,
            "extra_args": ["--host", "0.0.0.0"],
        },
    )
    assert unsafe_args.status_code == 400

    duplicate_name = client.post(
        "/api/profiles",
        json={
            "name": "test profile",
            "model_path": str(model),
            "context_size": 8192,
            "gpu_layers": 99,
            "host": "127.0.0.1",
            "port": 8080,
        },
    )
    assert duplicate_name.status_code == 409

    updated = client.put(
        f"/api/profiles/{created['id']}",
        json={
            "name": "edited profile",
            "model_path": str(model),
            "projector_path": None,
            "context_size": 16384,
            "gpu_layers": 80,
            "host": "127.0.0.1",
            "port": 8081,
            "extra_args": ["--parallel", "1"],
        },
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "edited profile"
    assert updated.json()["context_size"] == 16384
    assert updated.json()["gpu_layers"] == 80

    copied = client.post(
        f"/api/profiles/{created['id']}/duplicate",
        json={"name": "experiment copy"},
    )
    assert copied.status_code == 201
    copied_profile = copied.json()
    assert copied_profile["name"] == "experiment copy"
    assert copied_profile["context_size"] == 16384
    assert copied_profile["is_default"] is False

    defaulted = client.post(f"/api/profiles/{copied_profile['id']}/default")
    assert defaulted.status_code == 200
    assert defaulted.json()["is_default"] is True
    profiles = client.get("/api/profiles").json()
    assert sum(1 for profile in profiles if profile["is_default"]) == 1
    assert profiles[0]["name"] == "experiment copy"

    deleted = client.delete(f"/api/profiles/{created['id']}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    remaining = client.get("/api/profiles").json()
    assert len(remaining) == 1
    assert remaining[0]["name"] == "experiment copy"


def test_app_recovers_only_valid_persisted_llama_ownership(tmp_path: Path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    database = data_dir / "db.sqlite3"
    llama_server = tmp_path / "llama-server.exe"
    model = tmp_path / "model.gguf"
    llama_server.write_bytes(b"exe")
    model.write_bytes(b"model")

    repo = ModelRepository(database)
    repo.initialize()
    profile = repo.create_profile(
        name="recover me",
        model_path=str(model),
        projector_path=None,
        context_size=8192,
        gpu_layers=99,
        host="127.0.0.1",
        port=8080,
        extra_args=[],
    )
    repo.set_runtime_lease(
        runtime_id="llama.cpp",
        pid=4242,
        profile_id=profile["id"],
        executable_path=str(llama_server),
        host=profile["host"],
        port=profile["port"],
        model_path=profile["model_path"],
        command=[str(llama_server), "-m", profile["model_path"]],
    )

    identity = {
        "owner_pid": 4242,
        "owner_name": "llama-server",
        "owner_path": str(llama_server),
    }
    monkeypatch.setattr(runtime_module, "windows_process_identity", lambda pid: identity)
    monkeypatch.setattr(
        api_module,
        "probe_llama_service",
        lambda profile, timeout_seconds=0.75: {
            "occupied": True,
            "llama_compatible": True,
            "latency_ms": 1.0,
            "models": [],
            **identity,
        },
    )

    settings = Settings(
        data_dir=data_dir,
        database_path=database,
        model_roots=(tmp_path,),
        image_model_roots=(),
        llama_server_path=llama_server,
        a1111_launch_path=None,
        hermes_cli_path=None,
    )
    client = TestClient(create_app(settings))
    llama = client.get("/api/runtimes").json()[0]
    assert llama["running"] is True
    assert llama["recovered"] is True
    assert llama["pid"] == 4242
    assert client.get("/api/llama/active").json()["profile_id"] == profile["id"]


def test_app_discards_stale_runtime_lease(tmp_path: Path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    database = data_dir / "db.sqlite3"
    llama_server = tmp_path / "llama-server.exe"
    model = tmp_path / "model.gguf"
    llama_server.write_bytes(b"exe")
    model.write_bytes(b"model")

    repo = ModelRepository(database)
    repo.initialize()
    profile = repo.create_profile(
        name="stale",
        model_path=str(model),
        projector_path=None,
        context_size=8192,
        gpu_layers=99,
        host="127.0.0.1",
        port=8080,
        extra_args=[],
    )
    repo.set_runtime_lease(
        runtime_id="llama.cpp",
        pid=9999,
        profile_id=profile["id"],
        executable_path=str(llama_server),
        host=profile["host"],
        port=profile["port"],
        model_path=profile["model_path"],
        command=[str(llama_server)],
    )
    monkeypatch.setattr(
        api_module,
        "probe_llama_service",
        lambda profile, timeout_seconds=0.75: {
            "occupied": False,
            "llama_compatible": False,
            "latency_ms": None,
            "models": [],
            "owner_pid": None,
            "owner_name": None,
            "owner_path": None,
        },
    )

    settings = Settings(
        data_dir=data_dir,
        database_path=database,
        model_roots=(tmp_path,),
        image_model_roots=(),
        llama_server_path=llama_server,
        a1111_launch_path=None,
        hermes_cli_path=None,
    )
    TestClient(create_app(settings))
    assert ModelRepository(database).get_runtime_lease("llama.cpp") is None
