from __future__ import annotations

from pathlib import Path

from vektordeck.recommendations import build_recommendation

GIB = 1024 ** 3


def _assets(tmp_path: Path) -> tuple[Path, Path, list[dict]]:
    model = tmp_path / 'Qwen-Demo-IQ3_XS.gguf'
    projector = tmp_path / 'mmproj-Qwen-Demo-bf16.gguf'
    model.write_bytes(b'model')
    projector.write_bytes(b'projector')
    indexed = [
        {'path': str(model), 'name': model.name, 'kind': 'model', 'size_bytes': 11 * GIB},
        {'path': str(projector), 'name': projector.name, 'kind': 'projector', 'size_bytes': 1 * GIB},
    ]
    return model, projector, indexed


def _intelligence(model: Path) -> list[dict]:
    return [{
        'path': str(model),
        'status': 'ok',
        'architecture': 'qwen2vl',
        'display_name': 'Qwen Demo Vision',
        'context_length': 65536,
    }]


def _base_profile(model: Path, projector: Path) -> dict:
    return {
        'id': 1,
        'name': 'Qwen local 65K',
        'model_path': str(model),
        'projector_path': str(projector),
        'context_size': 65536,
        'gpu_layers': 99,
        'host': '127.0.0.1',
        'port': 8080,
        'extra_args': [],
        'is_default': True,
    }


def _run(model: Path, profile: dict, speed: float, *, quality: str = 'healthy') -> dict:
    if quality == 'pressured':
        ram_avg, ram_peak = 96.0, 97.0
    else:
        ram_avg, ram_peak = 70.0, 78.0
    return {
        'profile_id': 1,
        'profile_name': profile['name'],
        'model_path': str(model),
        'sample_count': 10,
        'ram_avg_percent': ram_avg,
        'ram_peak_percent': ram_peak,
        'vram_peak_bytes': 12 * GIB,
        'vram_total_bytes': 16 * GIB,
        'server_tokens_per_second': speed,
        'protocol_version': 2,
        'baseline_ready': True,
        'run_source': 'smart_launch',
    }


def test_32gb_16gb_multimodal_without_clean_evidence_is_experimental(tmp_path: Path) -> None:
    model, projector, indexed = _assets(tmp_path)
    result = build_recommendation(
        model_path=str(model),
        indexed_models=indexed,
        intelligence=_intelligence(model),
        profiles=[_base_profile(model, projector)],
        benchmarks=[],
        total_ram_bytes=32 * GIB,
        total_vram_bytes=16 * GIB,
        capabilities={'image_min_tokens': True},
    )

    assert result['status'] == 'EXPERIMENTAL'
    assert result['source'] == 'HARDWARE_HEURISTIC'
    assert result['profile']['context_size'] == 8192
    assert result['profile']['projector_path'] == str(projector)
    assert result['profile']['extra_args'] == ['--parallel', '1', '--image-min-tokens', '1024']
    assert any('protocol-v2' in reason.lower() for reason in result['reasons'])


def test_pressured_evidence_is_excluded_from_recommendation(tmp_path: Path) -> None:
    model, projector, indexed = _assets(tmp_path)
    profile = _base_profile(model, projector)
    pressured = _run(model, profile, 9.5, quality='pressured')

    result = build_recommendation(
        model_path=str(model),
        indexed_models=indexed,
        intelligence=_intelligence(model),
        profiles=[profile],
        benchmarks=[pressured],
        total_ram_bytes=32 * GIB,
        total_vram_bytes=16 * GIB,
        capabilities={},
    )

    assert result['status'] == 'EXPERIMENTAL'
    assert result['evidence'] is None
    assert any('pressured' in reason.lower() for reason in result['reasons'])


def test_one_clean_protocol_v2_run_is_not_enough(tmp_path: Path) -> None:
    model, projector, indexed = _assets(tmp_path)
    profile = _base_profile(model, projector)
    healthy = _run(model, profile, 8.2)

    result = build_recommendation(
        model_path=str(model),
        indexed_models=indexed,
        intelligence=_intelligence(model),
        profiles=[profile],
        benchmarks=[healthy],
        total_ram_bytes=32 * GIB,
        total_vram_bytes=16 * GIB,
        capabilities={},
    )

    assert result['status'] == 'EXPERIMENTAL'
    assert any('only 1 protocol-v2 trustworthy run' in reason.lower() for reason in result['reasons'])


def test_two_clean_protocol_v2_runs_become_evidence_backed(tmp_path: Path) -> None:
    model, projector, indexed = _assets(tmp_path)
    profile = _base_profile(model, projector)
    healthy_a = _run(model, profile, 8.2)
    healthy_b = _run(model, profile, 8.4)

    result = build_recommendation(
        model_path=str(model),
        indexed_models=indexed,
        intelligence=_intelligence(model),
        profiles=[profile],
        benchmarks=[healthy_a, healthy_b],
        total_ram_bytes=32 * GIB,
        total_vram_bytes=16 * GIB,
        capabilities={},
    )

    assert result['status'] == 'EVIDENCE_BACKED'
    assert result['source'] == 'TRUSTWORTHY_BENCHMARK'
    assert result['evidence']['runs'] == 2
    assert result['evidence']['average_tokens_per_second'] == 8.3
    assert result['profile']['context_size'] == 65536


def test_legacy_healthy_runs_cannot_promote(tmp_path: Path) -> None:
    model, projector, indexed = _assets(tmp_path)
    profile = _base_profile(model, projector)
    legacy = _run(model, profile, 9.0)
    legacy.pop('protocol_version')
    legacy.pop('baseline_ready')
    legacy.pop('run_source')

    result = build_recommendation(
        model_path=str(model),
        indexed_models=indexed,
        intelligence=_intelligence(model),
        profiles=[profile],
        benchmarks=[legacy, dict(legacy)],
        total_ram_bytes=32 * GIB,
        total_vram_bytes=16 * GIB,
        capabilities={},
    )

    assert result['status'] == 'EXPERIMENTAL'
    assert any('lack protocol-v2' in reason.lower() for reason in result['reasons'])


def test_missing_model_is_blocked(tmp_path: Path) -> None:
    missing = tmp_path / 'missing-Q4_K_M.gguf'
    result = build_recommendation(
        model_path=str(missing),
        indexed_models=[{'path': str(missing), 'name': missing.name, 'kind': 'model', 'size_bytes': 1}],
        intelligence=[],
        profiles=[],
        benchmarks=[],
        total_ram_bytes=32 * GIB,
        total_vram_bytes=16 * GIB,
        capabilities={},
    )
    assert result['status'] == 'BLOCKED'
    assert result['profile'] is None
