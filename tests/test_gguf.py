from __future__ import annotations

import struct
from pathlib import Path

import pytest

from vektordeck.gguf import GGUFError, inspect_gguf, summarize_gguf


def _string(value: str) -> bytes:
    raw = value.encode('utf-8')
    return struct.pack('<Q', len(raw)) + raw


def _entry_string(key: str, value: str) -> bytes:
    return _string(key) + struct.pack('<I', 8) + _string(value)


def _entry_u32(key: str, value: int) -> bytes:
    return _string(key) + struct.pack('<I', 4) + struct.pack('<I', value)


def _entry_u64(key: str, value: int) -> bytes:
    return _string(key) + struct.pack('<I', 10) + struct.pack('<Q', value)


def write_demo_gguf(path: Path) -> None:
    entries = [
        _entry_string('general.architecture', 'qwen2vl'),
        _entry_string('general.name', 'Demo Qwen Vision'),
        _entry_string('general.size_label', '27B'),
        _entry_u32('qwen2vl.context_length', 65536),
        _entry_u64('general.parameter_count', 27_000_000_000),
        _entry_u32('general.file_type', 14),
        _entry_u32('general.quantization_version', 2),
    ]
    payload = (
        b'GGUF'
        + struct.pack('<I', 3)
        + struct.pack('<Q', 321)
        + struct.pack('<Q', len(entries))
        + b''.join(entries)
    )
    path.write_bytes(payload)


def test_inspect_and_summarize_gguf(tmp_path: Path) -> None:
    path = tmp_path / 'demo.gguf'
    write_demo_gguf(path)

    metadata = inspect_gguf(path)
    summary = summarize_gguf(metadata)

    assert metadata.version == 3
    assert metadata.tensor_count == 321
    assert summary['architecture'] == 'qwen2vl'
    assert summary['display_name'] == 'Demo Qwen Vision'
    assert summary['context_length'] == 65536
    assert summary['parameter_count'] == 27_000_000_000
    assert summary['size_label'] == '27B'
    assert summary['file_type'] == 14
    assert summary['quantization_version'] == 2


def test_large_array_is_stream_skipped_not_materialized(tmp_path: Path) -> None:
    path = tmp_path / 'large-array.gguf'
    tokens = [f'token-{index}' for index in range(300)]
    array = (
        _string('tokenizer.ggml.tokens')
        + struct.pack('<I', 9)
        + struct.pack('<I', 8)
        + struct.pack('<Q', len(tokens))
        + b''.join(_string(token) for token in tokens)
    )
    path.write_bytes(
        b'GGUF'
        + struct.pack('<I', 3)
        + struct.pack('<Q', 0)
        + struct.pack('<Q', 1)
        + array
    )

    metadata = inspect_gguf(path)

    assert metadata.values['tokenizer.ggml.tokens'] == {
        'array_items': 300,
        'materialized': False,
    }


def test_invalid_magic_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / 'broken.gguf'
    path.write_bytes(b'NOPE' + b'\x00' * 64)

    with pytest.raises(GGUFError, match='GGUF magic'):
        inspect_gguf(path)


def test_absurd_string_length_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / 'hostile.gguf'
    payload = (
        b'GGUF'
        + struct.pack('<I', 3)
        + struct.pack('<Q', 0)
        + struct.pack('<Q', 1)
        + struct.pack('<Q', 99_999_999)
    )
    path.write_bytes(payload)

    with pytest.raises(GGUFError, match='safety limit'):
        inspect_gguf(path)
