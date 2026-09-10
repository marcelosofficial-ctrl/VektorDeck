from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from vektordeck.benchmark_protocol_api import build_benchmark_protocol_router
from vektordeck.config import Settings
from vektordeck.database import ModelRepository


def test_protocol_api_attaches_context_to_existing_benchmark(tmp_path: Path) -> None:
    database = tmp_path / 'data' / 'db.sqlite3'
    repository = ModelRepository(database)
    repository.initialize()
    profile = repository.create_profile(
        name='Demo',
        model_path=str(tmp_path / 'demo.gguf'),
        projector_path=None,
        context_size=4096,
        gpu_layers=0,
        host='127.0.0.1',
        port=8080,
        extra_args=[],
    )
    run = repository.save_benchmark(
        profile,
        {
            'elapsed_seconds': 1.0,
            'prompt_tokens': 10,
            'completion_tokens': 10,
            'tokens_per_second': 10.0,
            'server_tokens_per_second': 10.0,
        },
        {'sample_count': 2, 'ram_avg_percent': 40.0, 'ram_peak_percent': 45.0},
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
    app.include_router(build_benchmark_protocol_router(settings))
    client = TestClient(app)

    response = client.post(
        f"/api/benchmark-protocol/{run['id']}",
        json={
            'run_source': 'smart_launch',
            'baseline': {
                'ready': True,
                'sample_count': 6,
                'cpu_avg_percent': 10.0,
                'cpu_peak_percent': 15.0,
                'ram_avg_percent': 35.0,
                'ram_peak_percent': 36.0,
                'gpu_avg_percent': 5.0,
                'gpu_peak_percent': 7.0,
                'reasons': [],
            },
            'contaminators': [],
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload['protocol_version'] == 2
    assert payload['run_source'] == 'smart_launch'
    assert payload['baseline_ready'] is True

    history = client.get('/api/benchmark-protocol').json()
    assert history[0]['benchmark_id'] == run['id']
