from __future__ import annotations

from typing import Any


def classify_benchmark(run: dict[str, Any]) -> dict[str, Any]:
    """Classify benchmark evidence using explicit memory-headroom rules."""
    samples = int(run.get("sample_count") or 0)
    if samples <= 0:
        return {"quality": "UNVERIFIED", "quality_reasons": ["legacy run has no hardware evidence"]}

    reasons: list[str] = []
    ram_avg = run.get("ram_avg_percent")
    ram_peak = run.get("ram_peak_percent")
    vram_peak = run.get("vram_peak_bytes")
    vram_total = run.get("vram_total_bytes")
    vram_ratio = None
    if isinstance(vram_peak, (int, float)) and isinstance(vram_total, (int, float)) and vram_total > 0:
        vram_ratio = float(vram_peak) / float(vram_total) * 100.0

    pressured = False
    tight = False
    if isinstance(ram_avg, (int, float)) and ram_avg >= 90:
        pressured = True; reasons.append(f"RAM averaged {ram_avg:.1f}%")
    elif isinstance(ram_avg, (int, float)) and ram_avg >= 85:
        tight = True; reasons.append(f"RAM averaged {ram_avg:.1f}%")

    if isinstance(ram_peak, (int, float)) and ram_peak >= 95:
        pressured = True; reasons.append(f"RAM peaked at {ram_peak:.1f}%")
    elif isinstance(ram_peak, (int, float)) and ram_peak >= 90:
        tight = True; reasons.append(f"RAM peaked at {ram_peak:.1f}%")

    if vram_ratio is not None and vram_ratio >= 97:
        pressured = True; reasons.append(f"VRAM peaked at {vram_ratio:.1f}%")
    elif vram_ratio is not None and vram_ratio >= 90:
        tight = True; reasons.append(f"VRAM peaked at {vram_ratio:.1f}%")

    if pressured:
        quality = "PRESSURED"
    elif tight:
        quality = "TIGHT"
    else:
        quality = "HEALTHY"; reasons.append("memory headroom remained within benchmark thresholds")
    return {"quality": quality, "quality_reasons": reasons}


def llama_advisories(lines: list[str]) -> list[dict[str, str]]:
    """Convert known llama.cpp log messages into concise, explainable advisories."""
    text = "\n".join(lines).lower()
    advisories: list[dict[str, str]] = []

    if "require at minimum 1024 image tokens" in text or "--image-min-tokens 1024" in text:
        advisories.append({
            "severity": "RECOMMENDED",
            "code": "VISION_IMAGE_TOKENS",
            "title": "Increase Qwen-VL image token floor",
            "detail": "llama.cpp recommends --image-min-tokens 1024 for reliable grounding tasks with this multimodal model.",
        })

    if "n_gpu_layers already set by user" in text and "failed to fit params to free device memory" in text:
        advisories.append({
            "severity": "INFO",
            "code": "GPU_LAYER_AUTOFIT_DISABLED",
            "title": "GPU layer count is manually pinned",
            "detail": "ngl 99 prevents llama.cpp from automatically reducing GPU layers to fit current free device memory. The model loaded, so this is informational unless launches start failing.",
        })

    if "server default port will be changed to :9931" in text:
        advisories.append({
            "severity": "INFO",
            "code": "FUTURE_PORT_CHANGE",
            "title": "Future llama.cpp default port change",
            "detail": "VektorDeck already supplies an explicit profile port, so this upstream default change should not affect saved profiles.",
        })

    return advisories
