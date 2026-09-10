from vektordeck.quality import classify_benchmark, llama_advisories


def test_unverified_without_evidence() -> None:
    result = classify_benchmark({"sample_count": 0})
    assert result["quality"] == "UNVERIFIED"


def test_pressured_when_ram_is_saturated() -> None:
    result = classify_benchmark(
        {
            "sample_count": 12,
            "ram_avg_percent": 95.1,
            "ram_peak_percent": 97.0,
            "vram_peak_bytes": 14_310_000_000,
            "vram_total_bytes": 16 * 1024**3,
        }
    )
    assert result["quality"] == "PRESSURED"
    assert any("RAM averaged" in reason for reason in result["quality_reasons"])


def test_healthy_with_headroom() -> None:
    result = classify_benchmark(
        {
            "sample_count": 10,
            "ram_avg_percent": 62.0,
            "ram_peak_percent": 71.0,
            "vram_peak_bytes": 10 * 1024**3,
            "vram_total_bytes": 16 * 1024**3,
        }
    )
    assert result["quality"] == "HEALTHY"


def test_llama_advisories_are_actionable() -> None:
    advisories = llama_advisories(
        [
            "Qwen-VL models require at minimum 1024 image tokens to function correctly on grounding tasks",
            "failed to fit params to free device memory: n_gpu_layers already set by user to 99, abort",
            "NOTICE: server default port will be changed to :9931 in a future release",
        ]
    )
    titles = {item["title"] for item in advisories}
    assert "Increase Qwen-VL image token floor" in titles
    assert "GPU layer count is manually pinned" in titles
    assert "Future llama.cpp default port change" in titles
