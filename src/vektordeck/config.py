from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


A1111_LAUNCHERS = ("webui-user.bat", "webui-user.cmd", "webui.bat", "webui.cmd")
IMAGE_MODEL_DIR_NAMES = {"stable-diffusion", "checkpoints"}
KNOWN_A1111_DIRS = ("stable-diffusion-amd", "stable-diffusion-webui", "stable-diffusion-webui-directml")


def _split_paths(raw: str | None) -> tuple[Path, ...]:
    if not raw:
        return ()
    return tuple(Path(part).expanduser() for part in raw.split(os.pathsep) if part.strip())


def _existing_root(raw: str | None) -> Path | None:
    if not raw:
        return None
    return Path(raw).expanduser()


def _candidate_installs(root: Path) -> tuple[Path, ...]:
    candidates: list[Path] = [root]
    for name in KNOWN_A1111_DIRS:
        child = root / name
        if child.is_dir():
            candidates.append(child)
    try:
        for child in root.iterdir():
            if child.is_dir() and child not in candidates:
                candidates.append(child)
    except OSError:
        pass
    return tuple(candidates)


def discover_a1111_launcher(root: Path | None) -> Path | None:
    """Find an A1111 launch script with bounded discovery first."""
    if root is None or not root.is_dir():
        return None

    for install in _candidate_installs(root):
        for name in A1111_LAUNCHERS:
            candidate = install / name
            if candidate.is_file():
                return candidate

    # Compatibility fallback for unusual nested layouts. This is intentionally
    # only reached when direct/one-level discovery fails.
    matches: list[Path] = []
    try:
        for name in A1111_LAUNCHERS:
            matches.extend(path for path in root.rglob(name) if path.is_file())
    except OSError:
        return None

    if not matches:
        return None
    return min(matches, key=lambda path: (len(path.relative_to(root).parts), str(path).casefold()))


def discover_image_model_roots(root: Path | None) -> tuple[Path, ...]:
    """Locate checkpoint roots without walking the entire install tree."""
    if root is None or not root.is_dir():
        return ()

    found: dict[str, Path] = {}
    for install in _candidate_installs(root):
        likely = (
            install / "models" / "Stable-diffusion",
            install / "models" / "Checkpoints",
            install / "models" / "checkpoints",
            install / "Stable-diffusion",
            install / "Checkpoints",
            install / "checkpoints",
        )
        for path in likely:
            if path.is_dir():
                resolved = path.resolve()
                found[str(resolved).casefold()] = resolved

    if found:
        return tuple(sorted(found.values(), key=lambda path: str(path).casefold()))

    # Compatibility fallback for non-standard installs only.
    try:
        for path in root.rglob("*"):
            if not path.is_dir() or path.name.casefold() not in IMAGE_MODEL_DIR_NAMES:
                continue
            resolved = path.resolve()
            found[str(resolved).casefold()] = resolved
    except OSError:
        return ()

    return tuple(sorted(found.values(), key=lambda path: str(path).casefold()))


def discover_hermes_cli() -> Path | None:
    configured = os.getenv("VEKTORDECK_HERMES_CLI")
    if configured:
        return Path(configured).expanduser()
    detected = shutil.which("hermes")
    return Path(detected) if detected else None


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    database_path: Path
    model_roots: tuple[Path, ...]
    image_model_roots: tuple[Path, ...]
    llama_server_path: Path | None
    a1111_launch_path: Path | None
    hermes_cli_path: Path | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(os.getenv("VEKTORDECK_DATA_DIR", "~/.vektordeck")).expanduser()
        database_path = data_dir / "vektordeck.sqlite3"
        roots = _split_paths(os.getenv("VEKTORDECK_MODEL_ROOTS"))

        a1111_root = _existing_root(os.getenv("VEKTORDECK_A1111_ROOT"))
        explicit_image_roots = _split_paths(os.getenv("VEKTORDECK_IMAGE_MODEL_ROOTS"))
        image_roots = explicit_image_roots or discover_image_model_roots(a1111_root)

        llama = os.getenv("VEKTORDECK_LLAMA_SERVER")
        explicit_a1111 = os.getenv("VEKTORDECK_A1111_LAUNCH")
        a1111_launch = (
            Path(explicit_a1111).expanduser()
            if explicit_a1111
            else discover_a1111_launcher(a1111_root)
        )

        return cls(
            data_dir=data_dir,
            database_path=database_path,
            model_roots=roots,
            image_model_roots=image_roots,
            llama_server_path=Path(llama).expanduser() if llama else None,
            a1111_launch_path=a1111_launch,
            hermes_cli_path=discover_hermes_cli(),
        )
