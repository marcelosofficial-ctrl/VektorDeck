from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from vektordeck import recommendations_api
from vektordeck.config import Settings
from vektordeck.database import ModelRepository
from vektordeck.domain import ModelFile

GIB = 1024 ** 3


class FakeTelemetryService:
    def snapshot(self, *, cached_gpu_only: bool = False) -> dict:
        return {
            'memory': {'total_bytes': 32 * GIB, 'used_bytes': 8 * GIB, 'percent': 25.0},
            'gpu': {'vram_total_bytes': 16 * GIB, 'vram_used_bytes': 2 * GIB},
        }


def test_recommendation_api_creates_non_default_suggested_profile(tmp_path: Path, monkeypatch) -> None:
    database = tmp_path / 'data' / 'db.sqlite3'
    model = tmp_path / 'Qwen-Demo-IQ3_XS.gguf'
    projector = tmp_path / 'mmproj-Qwen-Demo-bf16.gguf'
    model.write_bytes(b'model')
    projector.write_bytes(b'projector')

    repo = ModelRepository(database)
    repo.initialize()
    model_stat = model.stat()
    projector_stat = projector.stat()
    repo.upsert_many([
        ModelFile(model.resolve(), model.name, 11 * GIB, model_stat.st_mtime_ns, 'model'),
        ModelFile(projector.resolve(), projector.name, 1 * GIB, projector_stat.st_mtime_ns, 'projector'),
    ])
    original = repo.create_profile(
        name='Everyday',
        model_path=str(model.resolve()),
        projector_path=str(projector.resolve()),
        context_size=65536,
        gpu_layers=99,
        host='127.0.0.1',
        port=8080,
        extra_args=[],
    )
    assert original['is_default'] is True

    settings = Settings(
        data_dir=tmp_path / 'data',
        database_path=database,
        model_roots=(tmp_path,),
        image_model_roots=(),
        llama_server_path=None,
        a1111_launch_path=None,
        hermes_cli_path=None,
    )

    monkeypatch.setattr(recommendations_api, 'TelemetryService', FakeTelemetryService)
    monkeypatch.setattr(
        recommendations_api,
        'inspect_llama_capabilities',
        lambda path: {'image_min_tokens': True},
    )

    app = FastAPI()
    app.include_router(recommendations_api.build_recommendations_router(settings))
    client = TestClient(app)

    response = client.get('/api/recommendations', params={'model_path': str(model.resolve())})
    assert response.status_code == 200
    suggested = response.json()
    assert suggested['status'] == 'EXPERIMENTAL'
    assert suggested['source'] == 'HARDWARE_HEURISTIC'
    assert suggested['profile']['context_size'] == 8192
    assert suggested['profile']['projector_path'] == str(projector.resolve())
    assert suggested['profile']['extra_args'] == ['--parallel', '1', '--image-min-tokens', '1024']

    created_response = client.post('/api/recommendations/profile', json={'model_path': str(model.resolve())})
    assert created_response.status_code == 201
    created = created_response.json()['created']
    assert created['id'] != original['id']
    assert created['is_default'] is False
    assert created['context_size'] == 8192

    profiles = repo.list_profiles()
    assert len(profiles) == 2
    assert sum(1 for profile in profiles if profile['is_default']) == 1
    assert next(profile for profile in profiles if profile['is_default'])['id'] == original['id']
