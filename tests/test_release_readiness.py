from __future__ import annotations

from pathlib import Path

from vektordeck.database import ModelRepository
from vektordeck.domain import ModelFile
from vektordeck.model_intelligence import ModelIntelligenceRepository
from vektordeck.release_readiness import assess_release_readiness


def test_release_readiness_blocks_without_core_model_and_profile(tmp_path: Path) -> None:
    database = tmp_path / 'data' / 'db.sqlite3'
    ModelRepository(database).initialize()
    result = assess_release_readiness(
        database_path=database,
        llama_server_path=None,
        a1111_launch_path=None,
        hermes_cli_path=None,
    )
    assert result['status'] == 'BLOCKED'
    assert result['blocking_failures'] >= 2


def test_release_readiness_allows_pending_performance_evidence(tmp_path: Path) -> None:
    database = tmp_path / 'data' / 'db.sqlite3'
    model = tmp_path / 'demo.gguf'
    model.write_bytes(b'GGUF')
    llama = tmp_path / 'llama-server.exe'
    llama.write_bytes(b'exe')

    repo = ModelRepository(database)
    repo.initialize()
    stat = model.stat()
    repo.upsert_many([ModelFile(model.resolve(), model.name, stat.st_size, stat.st_mtime_ns, 'model')])
    repo.create_profile(
        name='Default',
        model_path=str(model.resolve()),
        projector_path=None,
        context_size=4096,
        gpu_layers=1,
        host='127.0.0.1',
        port=8080,
        extra_args=[],
    )

    intelligence = ModelIntelligenceRepository(database)
    intelligence.initialize()

    result = assess_release_readiness(
        database_path=database,
        llama_server_path=llama,
        a1111_launch_path=None,
        hermes_cli_path=None,
    )
    assert result['status'] == 'READY_WITH_NOTES'
    assert result['blocking_failures'] == 0
    evidence = next(item for item in result['checks'] if item['code'] == 'EVIDENCE')
    assert evidence['status'] == 'PENDING'
    assert evidence['blocking'] is False
