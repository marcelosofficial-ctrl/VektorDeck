from __future__ import annotations

from pathlib import Path

from .domain import ModelFile, ModelKind

PROJECTOR_MARKERS = ("mmproj", "projector", "vision-proj", "vision_projector")
IMAGE_EXTENSIONS = {".safetensors", ".ckpt"}


def classify_model_file(path: Path) -> ModelKind:
    name = path.name.lower()
    suffix = path.suffix.lower()
    if suffix == ".gguf":
        if any(marker in name for marker in PROJECTOR_MARKERS):
            return "projector"
        return "model"
    if suffix in IMAGE_EXTENSIONS:
        return "checkpoint"
    return "unknown"


def classify_gguf(path: Path) -> ModelKind:
    return classify_model_file(path)


def _scan_extensions(roots: tuple[Path, ...], extensions: set[str]) -> dict[str, ModelFile]:
    found: dict[str, ModelFile] = {}
    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.suffix.lower() not in extensions or not path.is_file():
                continue
            try:
                stat = path.stat()
                resolved = path.resolve()
            except OSError:
                continue
            key = str(resolved).casefold()
            found[key] = ModelFile(
                path=resolved,
                name=resolved.name,
                size_bytes=stat.st_size,
                modified_ns=stat.st_mtime_ns,
                kind=classify_model_file(resolved),
            )
    return found


def scan_roots(
    roots: tuple[Path, ...],
    image_roots: tuple[Path, ...] = (),
) -> list[ModelFile]:
    found = _scan_extensions(roots, {".gguf"})
    found.update(_scan_extensions(image_roots, IMAGE_EXTENSIONS))
    return sorted(found.values(), key=lambda item: (item.kind, item.name.casefold()))
