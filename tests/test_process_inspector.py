from __future__ import annotations

from vektordeck.process_inspector import top_processes


def test_top_processes_returns_bounded_read_only_snapshot() -> None:
    rows = top_processes(limit=3, sample_seconds=0.05)
    assert len(rows) <= 3
    for row in rows:
        assert set(row) == {'pid', 'name', 'role', 'cpu_percent', 'memory_bytes', 'memory_mb'}
        assert isinstance(row['pid'], int)
        assert isinstance(row['name'], str)
        assert row['role'] in {'user', 'system', 'vektordeck_backend'}
        assert row['pid'] != 0
        assert row['name'].casefold() != 'system idle process'
        assert row['cpu_percent'] >= 0
        assert row['memory_bytes'] >= 0
        assert row['memory_mb'] >= 0
