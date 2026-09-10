from __future__ import annotations

from pathlib import Path

from vektordeck.benchmark_protocol import BenchmarkProtocolRepository


def test_protocol_v2_persists_baseline_and_contaminators(tmp_path: Path) -> None:
    database = tmp_path / 'data.sqlite3'
    repository = BenchmarkProtocolRepository(database)
    repository.initialize()

    saved = repository.save(
        42,
        run_source='smart_launch',
        baseline={
            'ready': True,
            'sample_count': 6,
            'cpu_avg_percent': 12.5,
            'cpu_peak_percent': 20.0,
            'ram_avg_percent': 40.0,
            'ram_peak_percent': 42.0,
            'gpu_avg_percent': 8.0,
            'gpu_peak_percent': 12.0,
            'reasons': [],
        },
        contaminators=[{'pid': 100, 'name': 'demo', 'cpu_percent': 3.2, 'memory_mb': 200.0}],
    )

    assert saved['benchmark_id'] == 42
    assert saved['protocol_version'] == 2
    assert saved['run_source'] == 'smart_launch'
    assert saved['baseline_ready'] is True
    assert saved['baseline_sample_count'] == 6
    assert saved['baseline_cpu_avg_percent'] == 12.5
    assert saved['contaminators'][0]['name'] == 'demo'

    reopened = BenchmarkProtocolRepository(database)
    assert reopened.get(42) == saved


def test_protocol_source_falls_back_to_manual(tmp_path: Path) -> None:
    repository = BenchmarkProtocolRepository(tmp_path / 'data.sqlite3')
    repository.initialize()
    saved = repository.save(1, run_source='unknown', baseline={'ready': False, 'sample_count': 0})
    assert saved['run_source'] == 'manual'
    assert saved['baseline_ready'] is False
