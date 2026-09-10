from pathlib import Path

from vektordeck.scanner import classify_gguf, scan_roots


def test_projector_classification() -> None:
    assert classify_gguf(Path("mmproj-Qwen3-VL-Q8_0.gguf")) == "projector"
    assert classify_gguf(Path("Qwen3-8B-Q4_K_M.gguf")) == "model"


def test_scan_discovers_and_deduplicates(tmp_path: Path) -> None:
    model = tmp_path / "models" / "Qwen.gguf"
    model.parent.mkdir()
    model.write_bytes(b"gguf")
    results = scan_roots((tmp_path, tmp_path / "models"))
    assert len(results) == 1
    assert results[0].name == "Qwen.gguf"
