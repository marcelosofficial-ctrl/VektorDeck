from vektordeck.evidence import summarize_snapshots


def test_summarize_snapshots_preserves_average_and_peak_evidence() -> None:
    summary = summarize_snapshots([
        {
            "cpu": {"utilization_percent": 20.0},
            "memory": {"percent": 50.0},
            "gpu": {"utilization_percent": 70.0, "vram_used_bytes": 4_000, "vram_total_bytes": 16_000},
        },
        {
            "cpu": {"utilization_percent": 40.0},
            "memory": {"percent": 60.0},
            "gpu": {"utilization_percent": 90.0, "vram_used_bytes": 6_000, "vram_total_bytes": 16_000},
        },
    ])

    assert summary["sample_count"] == 2
    assert summary["cpu_avg_percent"] == 30.0
    assert summary["cpu_peak_percent"] == 40.0
    assert summary["ram_avg_percent"] == 55.0
    assert summary["ram_peak_percent"] == 60.0
    assert summary["gpu_avg_percent"] == 80.0
    assert summary["gpu_peak_percent"] == 90.0
    assert summary["vram_avg_bytes"] == 5_000
    assert summary["vram_peak_bytes"] == 6_000
    assert summary["vram_total_bytes"] == 16_000


def test_summarize_snapshots_tolerates_missing_gpu_values() -> None:
    summary = summarize_snapshots([
        {
            "cpu": {"utilization_percent": 10.0},
            "memory": {"percent": 30.0},
            "gpu": {"utilization_percent": None, "vram_used_bytes": None, "vram_total_bytes": None},
        }
    ])

    assert summary["sample_count"] == 1
    assert summary["gpu_avg_percent"] is None
    assert summary["vram_peak_bytes"] is None
