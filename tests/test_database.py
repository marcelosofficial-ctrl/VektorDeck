from pathlib import Path

from vektordeck.database import ModelRepository
from vektordeck.domain import ModelFile


def test_upsert_is_idempotent(tmp_path: Path) -> None:
    repo = ModelRepository(tmp_path / "test.sqlite3")
    repo.initialize()
    model = ModelFile(tmp_path / "a.gguf", "a.gguf", 10, 1, "model")
    repo.upsert_many([model])
    repo.upsert_many([model])
    rows = repo.list_models()
    assert len(rows) == 1
    assert rows[0]["name"] == "a.gguf"
    assert repo.integrity() == "ok"


def test_benchmark_history_persists_with_hardware_evidence(tmp_path: Path) -> None:
    repo = ModelRepository(tmp_path / "test.sqlite3")
    repo.initialize()
    profile = repo.create_profile(
        name="demo",
        model_path=str(tmp_path / "demo.gguf"),
        projector_path=None,
        context_size=8192,
        gpu_layers=99,
        host="127.0.0.1",
        port=8080,
        extra_args=[],
    )
    saved = repo.save_benchmark(
        profile,
        {
            "elapsed_seconds": 2.5,
            "prompt_tokens": 20,
            "completion_tokens": 40,
            "tokens_per_second": 16.0,
            "server_tokens_per_second": 17.5,
        },
        {
            "sample_count": 3,
            "cpu_avg_percent": 44.0,
            "cpu_peak_percent": 61.0,
            "ram_avg_percent": 53.0,
            "ram_peak_percent": 55.0,
            "gpu_avg_percent": 82.0,
            "gpu_peak_percent": 96.0,
            "vram_avg_bytes": 5_000,
            "vram_peak_bytes": 6_000,
            "vram_total_bytes": 16_000,
        },
    )

    assert saved["profile_name"] == "demo"
    assert saved["sample_count"] == 3
    assert saved["gpu_peak_percent"] == 96.0
    history = repo.list_benchmarks()
    assert len(history) == 1
    assert history[0]["server_tokens_per_second"] == 17.5
    assert history[0]["vram_peak_bytes"] == 6_000


def test_profile_management_preserves_benchmark_history(tmp_path: Path) -> None:
    repo = ModelRepository(tmp_path / "test.sqlite3")
    repo.initialize()
    original = repo.create_profile(
        name="everyday",
        model_path=str(tmp_path / "model.gguf"),
        projector_path=str(tmp_path / "vision.gguf"),
        context_size=65536,
        gpu_layers=99,
        host="127.0.0.1",
        port=8080,
        extra_args=["--parallel", "1"],
    )
    assert original["is_default"] is True

    updated = repo.update_profile(
        original["id"],
        name="everyday tuned",
        model_path=original["model_path"],
        projector_path=original["projector_path"],
        context_size=32768,
        gpu_layers=80,
        host="127.0.0.1",
        port=8081,
        extra_args=["--parallel", "1", "--cache-type-k", "q8_0"],
    )
    assert updated is not None
    assert updated["name"] == "everyday tuned"
    assert updated["context_size"] == 32768
    assert updated["gpu_layers"] == 80
    assert updated["port"] == 8081

    duplicate = repo.duplicate_profile(original["id"], "experiment copy")
    assert duplicate is not None
    assert duplicate["name"] == "experiment copy"
    assert duplicate["context_size"] == 32768
    assert duplicate["is_default"] is False

    repo.save_benchmark(
        updated,
        {
            "elapsed_seconds": 1.0,
            "prompt_tokens": 10,
            "completion_tokens": 10,
            "tokens_per_second": 10.0,
            "server_tokens_per_second": 10.0,
        },
    )
    assert repo.delete_profile(original["id"]) is True
    assert repo.get_profile(original["id"]) is None
    assert len(repo.list_benchmarks()) == 1
    assert repo.list_benchmarks()[0]["profile_name"] == "everyday tuned"
    remaining = repo.list_profiles()
    assert len(remaining) == 1
    assert remaining[0]["name"] == "experiment copy"
    assert remaining[0]["is_default"] is True


def test_managed_runtime_lease_persists_and_clears(tmp_path: Path) -> None:
    database = tmp_path / "test.sqlite3"
    repo = ModelRepository(database)
    repo.initialize()
    profile = repo.create_profile(
        name="recoverable",
        model_path=str(tmp_path / "model.gguf"),
        projector_path=None,
        context_size=16384,
        gpu_layers=99,
        host="127.0.0.1",
        port=8080,
        extra_args=["--parallel", "1"],
    )

    saved = repo.set_runtime_lease(
        runtime_id="llama.cpp",
        pid=4321,
        profile_id=profile["id"],
        executable_path=str(tmp_path / "llama-server.exe"),
        host="127.0.0.1",
        port=8080,
        model_path=profile["model_path"],
        command=["llama-server.exe", "-m", profile["model_path"]],
    )
    assert saved["pid"] == 4321
    assert saved["command"][0] == "llama-server.exe"

    reopened = ModelRepository(database)
    reopened.initialize()
    lease = reopened.get_runtime_lease("llama.cpp")
    assert lease is not None
    assert lease["profile_id"] == profile["id"]
    assert lease["port"] == 8080

    reopened.clear_runtime_lease("llama.cpp")
    assert reopened.get_runtime_lease("llama.cpp") is None
