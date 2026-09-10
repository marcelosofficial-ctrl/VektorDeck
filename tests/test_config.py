from pathlib import Path

from vektordeck.config import discover_a1111_launcher, discover_image_model_roots


def test_discovers_direct_a1111_launcher(tmp_path: Path) -> None:
    launcher = tmp_path / "webui-user.bat"
    launcher.write_text("echo launch", encoding="utf-8")
    assert discover_a1111_launcher(tmp_path) == launcher


def test_discovers_nested_a1111_launcher(tmp_path: Path) -> None:
    install = tmp_path / "stable-diffusion-amd"
    install.mkdir()
    launcher = install / "webui-user.bat"
    launcher.write_text("echo launch", encoding="utf-8")
    assert discover_a1111_launcher(tmp_path) == launcher


def test_discovers_only_checkpoint_directories(tmp_path: Path) -> None:
    checkpoints = tmp_path / "models" / "Stable-diffusion"
    loras = tmp_path / "models" / "Lora"
    checkpoints.mkdir(parents=True)
    loras.mkdir(parents=True)

    roots = discover_image_model_roots(tmp_path)

    assert checkpoints.resolve() in roots
    assert loras.resolve() not in roots


def test_discovers_checkpoint_roots_across_known_workspace_installs(tmp_path: Path) -> None:
    amd = tmp_path / "stable-diffusion-amd" / "models" / "Stable-diffusion"
    webui = tmp_path / "stable-diffusion-webui" / "models" / "Stable-diffusion"
    amd.mkdir(parents=True)
    webui.mkdir(parents=True)

    roots = discover_image_model_roots(tmp_path)

    assert amd.resolve() in roots
    assert webui.resolve() in roots
    assert len(roots) == 2
