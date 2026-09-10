from __future__ import annotations

from pathlib import Path

from vektordeck.model_compatibility import (
    filename_quantization,
    profile_readiness,
    projector_pairing_hints,
)


def test_filename_quantization_detection() -> None:
    assert filename_quantization('Qwen-27B-IQ3_XS.gguf') == 'IQ3_XS'
    assert filename_quantization('model.Q4_K_M.gguf') == 'Q4_K_M'
    assert filename_quantization('model-bf16.gguf') == 'BF16'
    assert filename_quantization('plain.gguf') is None


def test_projector_pairing_prefers_same_folder(tmp_path: Path) -> None:
    family = tmp_path / 'QwenVision'
    family.mkdir()
    model = family / 'Qwen-27B-IQ3_XS.gguf'
    projector = family / 'mmproj-Qwen-27B-bf16.gguf'
    other = tmp_path / 'mmproj-other.gguf'

    hints = projector_pairing_hints([
        {'path': str(model), 'name': model.name, 'kind': 'model'},
        {'path': str(projector), 'name': projector.name, 'kind': 'projector'},
        {'path': str(other), 'name': other.name, 'kind': 'projector'},
    ])

    assert len(hints) == 1
    recommended = hints[0]['recommended_projector']
    assert recommended is not None
    assert recommended['path'] == str(projector)
    assert 'same folder' in recommended['reasons']


def test_profile_readiness_ready_when_assets_and_context_match(tmp_path: Path) -> None:
    model = tmp_path / 'Qwen-27B-IQ3_XS.gguf'
    projector = tmp_path / 'mmproj-Qwen-27B-bf16.gguf'
    model.write_bytes(b'x')
    projector.write_bytes(b'x')
    indexed = [
        {'path': str(model), 'kind': 'model'},
        {'path': str(projector), 'kind': 'projector'},
    ]
    intelligence = [{
        'path': str(model),
        'status': 'ok',
        'architecture': 'qwen2vl',
        'context_length': 65536,
    }]
    profile = {
        'id': 1,
        'name': 'Qwen local',
        'model_path': str(model),
        'projector_path': str(projector),
        'context_size': 32768,
        'host': '127.0.0.1',
    }

    result = profile_readiness(profile, indexed, intelligence)
    assert result['status'] == 'READY'
    assert result['quantization_hint'] == 'IQ3_XS'
    assert result['architecture'] == 'qwen2vl'


def test_profile_readiness_warns_when_context_exceeds_metadata(tmp_path: Path) -> None:
    model = tmp_path / 'model-Q4_K_M.gguf'
    model.write_bytes(b'x')
    result = profile_readiness(
        {
            'id': 2,
            'name': 'Too large',
            'model_path': str(model),
            'projector_path': None,
            'context_size': 65536,
            'host': '127.0.0.1',
        },
        [{'path': str(model), 'kind': 'model'}],
        [{'path': str(model), 'status': 'ok', 'architecture': 'llama', 'context_length': 8192}],
    )
    assert result['status'] == 'WARN'
    assert any('advertises 8,192' in reason['message'] for reason in result['reasons'])


def test_profile_readiness_blocks_missing_assets(tmp_path: Path) -> None:
    model = tmp_path / 'missing.gguf'
    result = profile_readiness(
        {
            'id': 3,
            'name': 'Missing',
            'model_path': str(model),
            'projector_path': None,
            'context_size': 8192,
            'host': '127.0.0.1',
        },
        [],
        [],
    )
    assert result['status'] == 'BLOCKED'
