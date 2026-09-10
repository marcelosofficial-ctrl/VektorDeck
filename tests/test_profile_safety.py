from pathlib import Path

from fastapi.testclient import TestClient

from vektordeck.api import create_app
from vektordeck.config import Settings


def _client(tmp_path: Path) -> tuple[TestClient, Path, Path]:
    models = tmp_path / "models"
    models.mkdir()
    model = models / "demo.gguf"
    projector = models / "mmproj-demo.gguf"
    model.write_bytes(b"model")
    projector.write_bytes(b"projector")

    settings = Settings(
        data_dir=tmp_path / "data",
        database_path=tmp_path / "data" / "db.sqlite3",
        model_roots=(models,),
        image_model_roots=(),
        llama_server_path=None,
        a1111_launch_path=None,
        hermes_cli_path=None,
    )
    client = TestClient(create_app(settings))
    client.post("/api/scan")
    return client, model, projector


def _payload(model: Path, projector: Path | None = None) -> dict:
    return {
        "name": "safe profile",
        "model_path": str(model),
        "projector_path": str(projector) if projector else None,
        "context_size": 8192,
        "gpu_layers": 99,
        "host": "127.0.0.1",
        "port": 8080,
        "extra_args": [],
    }


def test_profile_requires_indexed_model_path(tmp_path: Path) -> None:
    client, _, projector = _client(tmp_path)
    outside = tmp_path / "outside.gguf"
    outside.write_bytes(b"outside")

    response = client.post("/api/profiles", json=_payload(outside, projector))

    assert response.status_code == 400
    assert "indexed GGUF language model" in response.json()["detail"]


def test_profile_requires_indexed_projector_path(tmp_path: Path) -> None:
    client, model, _ = _client(tmp_path)
    outside = tmp_path / "mmproj-outside.gguf"
    outside.write_bytes(b"outside")

    response = client.post("/api/profiles", json=_payload(model, outside))

    assert response.status_code == 400
    assert "indexed multimodal projector" in response.json()["detail"]


def test_profile_rejects_non_loopback_host(tmp_path: Path) -> None:
    client, model, projector = _client(tmp_path)
    payload = _payload(model, projector)
    payload["host"] = "0.0.0.0"

    response = client.post("/api/profiles", json=payload)

    assert response.status_code == 400
    assert "loopback" in response.json()["detail"]
