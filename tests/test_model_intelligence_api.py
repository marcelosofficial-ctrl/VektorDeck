from __future__ import annotations

import struct
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from vektordeck.config import Settings
from vektordeck.database import ModelRepository
from vektordeck.domain import ModelFile
from vektordeck.model_intelligence_api import build_model_intelligence_router


def _string(value: str) -> bytes:
    raw = value.encode('utf-8')
    return struct.pack('<Q', len(raw)) + raw


def _entry_string(key: str, value: str) -> bytes:
    return _string(key) + struct.pack('<I', 8) + _string(value)


def _entry_u32(key: str, value: int) -> bytes:
    return _string(key) + struct.pack('<I', 4) + struct.pack('<I', value)


def write_demo_gguf(path: Path) -> None:
    entries = [
        _entry_string('general.architecture', 'qwen2'),
        _entry_string('general.name', 'API Demo'),
        _entry_u32('qwen2.context_length', 8192),
    ]
    path.write_bytes(
        b'GGUF'
        + struct.pack('<I', 3)
        + struct.pack('<Q', 42)
        + struct.pack('<Q', len(entries))
        + b''.join(entries)
    )


def test_model_intelligence_scan_list_and_profile_readiness(tmp_path: Path) -> None:
    database = tmp_path / 'data' / 'db.sqlite3'
    model = tmp_path / 'demo-Q4_K_M.gguf'
    write_demo_gguf(model)
    stat = model.stat()

    repository = ModelRepository(database)
    repository.initialize()
    repository.upsert_many([
        ModelFile(model.resolve(), model.name, stat.st_size, stat.st_mtime_ns, 'model')
    ])
    profile = repository.create_profile(
        name='Demo profile',
        model_path=str(model.resolve()),
        projector_path=None,
        context_size=4096,
        gpu_layers=99,
        host='127.0.0.1',
        port=8080,
        extra_args=[],
    )

    settings = Settings(
        data_dir=tmp_path / 'data',
        database_path=database,
        model_roots=(tmp_path,),
        image_model_roots=(),
        llama_server_path=None,
        a1111_launch_path=None,
        hermes_cli_path=None,
    )
    app = FastAPI()
    app.include_router(build_model_intelligence_router(settings))
    client = TestClient(app)

    first = client.post('/api/model-intelligence/scan')
    assert first.status_code == 200
    payload = first.json()
    assert payload['candidates'] == 1
    assert payload['inspected'] == 1
    assert payload['errors'] == 0
    assert payload['results'][0]['architecture'] == 'qwen2'
    assert payload['profiles'][0]['status'] == 'READY'
    assert payload['profiles'][0]['quantization_hint'] == 'Q4_K_M'

    second = client.post('/api/model-intelligence/scan').json()
    assert second['cached'] == 1
    assert second['inspected'] == 0

    listed = client.get('/api/model-intelligence').json()
    assert len(listed) == 1
    assert listed[0]['display_name'] == 'API Demo'

    readiness = client.get(f"/api/model-intelligence/profiles/{profile['id']}")
    assert readiness.status_code == 200
    ready_payload = readiness.json()
    assert ready_payload['status'] == 'READY'
    assert ready_payload['advertised_context'] == 8192
    assert ready_payload['requested_context'] == 4096

    pairings = client.get('/api/model-intelligence/pairings')
    assert pairings.status_code == 200
    assert pairings.json()[0]['recommended_projector'] is None
