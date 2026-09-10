from pathlib import Path

import pytest

import vektordeck.runtime as runtime_module
from vektordeck.runtime import RuntimeManager, build_llama_command, validate_profile_runtime


def _profile(tmp_path: Path) -> dict:
    model = tmp_path / "model.gguf"
    projector = tmp_path / "mmproj.gguf"
    model.write_bytes(b"model")
    projector.write_bytes(b"vision")
    return {
        "id": 1,
        "name": "Qwen local 65K",
        "model_path": str(model),
        "projector_path": str(projector),
        "context_size": 65536,
        "gpu_layers": 99,
        "host": "127.0.0.1",
        "port": 8080,
        "extra_args": [],
    }


def test_build_llama_command_is_deterministic_and_localhost_cors(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    log_path = tmp_path / "logs" / "llama.cpp.log"
    command = build_llama_command("llama-server.exe", profile, log_path)

    assert command[:3] == ["llama-server.exe", "-m", profile["model_path"]]
    assert command[command.index("--ctx-size") + 1] == "65536"
    assert command[command.index("--host") + 1] == "127.0.0.1"
    assert command[command.index("--port") + 1] == "8080"
    assert command[command.index("-ngl") + 1] == "99"
    assert command[command.index("--mmproj") + 1] == profile["projector_path"]
    assert command[command.index("--cors-origins") + 1] == "localhost"
    assert command[command.index("--log-file") + 1] == str(log_path)


def test_tuning_extra_args_remain_allowed(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    profile["extra_args"] = [
        "--parallel",
        "1",
        "--cache-type-k",
        "q8_0",
        "--flash-attn",
        "on",
        "--image-min-tokens",
        "1024",
    ]

    command = build_llama_command("llama-server.exe", profile, tmp_path / "automatic.log")

    assert command[-8:] == profile["extra_args"]
    assert command.count("--host") == 1
    assert command.count("--cors-origins") == 1


def test_non_loopback_profile_is_rejected(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    profile["host"] = "0.0.0.0"

    with pytest.raises(ValueError, match="loopback only"):
        validate_profile_runtime(profile)


def test_core_options_cannot_be_overridden_through_extra_args(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    profile["extra_args"] = ["--host", "0.0.0.0", "--parallel", "1"]

    with pytest.raises(ValueError, match="extra_args cannot override"):
        build_llama_command("llama-server.exe", profile, tmp_path / "automatic.log")


def test_recovered_runtime_requires_exact_process_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    executable = tmp_path / "llama-server.exe"
    executable.write_bytes(b"exe")
    manager = RuntimeManager(tmp_path / "logs")

    monkeypatch.setattr(
        runtime_module,
        "windows_process_identity",
        lambda pid: {"owner_pid": pid, "owner_name": "llama-server", "owner_path": str(executable)},
    )
    manager.recover_llama(pid=4242, profile_id=7, executable_path=str(executable))
    state = manager.inspect("llama.cpp", "llama.cpp", executable)
    assert state.running is True
    assert state.recovered is True
    assert state.pid == 4242
    assert manager.active_llama_profile_id() == 7

    monkeypatch.setattr(
        runtime_module,
        "windows_process_identity",
        lambda pid: {"owner_pid": pid, "owner_name": "python", "owner_path": str(tmp_path / "python.exe")},
    )
    state = manager.inspect("llama.cpp", "llama.cpp", executable)
    assert state.running is False
    assert state.recovered is False
    assert manager.active_llama_profile_id() is None


def test_recovery_rejects_pid_reuse_with_different_executable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    executable = tmp_path / "llama-server.exe"
    executable.write_bytes(b"exe")
    manager = RuntimeManager(tmp_path / "logs")
    monkeypatch.setattr(
        runtime_module,
        "windows_process_identity",
        lambda pid: {"owner_pid": pid, "owner_name": "other", "owner_path": str(tmp_path / "other.exe")},
    )

    with pytest.raises(ValueError, match="expected executable"):
        manager.recover_llama(pid=4242, profile_id=7, executable_path=str(executable))
