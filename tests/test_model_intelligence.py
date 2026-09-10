from __future__ import annotations

import struct
from pathlib import Path

from vektordeck.model_intelligence import ModelIntelligenceRepository


def _string(value: str) -> bytes:
    raw = value.encode('utf-8')
    return struct.pack('<Q', len(raw)) + raw


def _entry_string(key: str, value: str) -> bytes:
    return _string(key) + struct.pack('<I', 8) + _string(value)


def write_demo_gguf(path: Path) -> None:
    entries = [
        _entry_string('general.architecture', 'llama'),
        _entry_string('general.name', 'Cached Demo'),
    ]
    path.write_bytes(
        b'GGUF'
        + struct.pack('<I', 3)
        + struct.pack('<Q', 10)
        + struct.pack('<Q', len(entries))
        + b''.join(entries)
    )


def test_model_intelligence_is_cached_for_unchanged_file(tmp_path: Path) -> None:
    database = tmp_path / 'data.sqlite3'
    repo = ModelIntelligenceRepository(database)
    repo.initialize()
    model = tmp_path / 'demo.gguf'
    write_demo_gguf(model)
    stat = model.stat()

    first = repo.inspect_if_needed(model, modified_ns=stat.st_mtime_ns, size_bytes=stat.st_size)
    second = repo.inspect_if_needed(model, modified_ns=stat.st_mtime_ns, size_bytes=stat.st_size)

    assert first['status'] == 'ok'
    assert first['architecture'] == 'llama'
    assert second['path'] == first['path']
    assert second['inspected_at'] == first['inspected_at']
    assert len(repo.list_all()) == 1


def test_malformed_gguf_is_recorded_as_error_not_exception(tmp_path: Path) -> None:
    database = tmp_path / 'data.sqlite3'
    repo = ModelIntelligenceRepository(database)
    repo.initialize()
    model = tmp_path / 'broken.gguf'
    model.write_bytes(b'broken')
    stat = model.stat()

    result = repo.inspect_if_needed(model, modified_ns=stat.st_mtime_ns, size_bytes=stat.st_size)

    assert result['status'] == 'error'
    assert 'GGUF magic' in result['error']
    assert len(repo.list_all()) == 1
