from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .domain import ModelFile

SCHEMA = """
CREATE TABLE IF NOT EXISTS model_files (
    path TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
    modified_ns INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('model','projector','checkpoint','unknown')),
    first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_model_files_kind ON model_files(kind);
CREATE INDEX IF NOT EXISTS idx_model_files_name ON model_files(name);

CREATE TABLE IF NOT EXISTS launch_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    runtime_id TEXT NOT NULL DEFAULT 'llama.cpp',
    model_path TEXT NOT NULL,
    projector_path TEXT,
    context_size INTEGER NOT NULL CHECK(context_size > 0),
    gpu_layers INTEGER NOT NULL CHECK(gpu_layers >= 0),
    host TEXT NOT NULL DEFAULT '127.0.0.1',
    port INTEGER NOT NULL CHECK(port BETWEEN 1 AND 65535),
    extra_args_json TEXT NOT NULL DEFAULT '[]',
    is_default INTEGER NOT NULL DEFAULT 0 CHECK(is_default IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS managed_runtimes (
    runtime_id TEXT PRIMARY KEY,
    pid INTEGER NOT NULL CHECK(pid > 0),
    profile_id INTEGER,
    executable_path TEXT NOT NULL,
    host TEXT,
    port INTEGER,
    model_path TEXT,
    command_json TEXT NOT NULL DEFAULT '[]',
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS benchmark_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL,
    profile_name TEXT NOT NULL,
    model_path TEXT NOT NULL,
    elapsed_seconds REAL NOT NULL CHECK(elapsed_seconds >= 0),
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    tokens_per_second REAL,
    server_tokens_per_second REAL,
    sample_count INTEGER,
    cpu_avg_percent REAL,
    cpu_peak_percent REAL,
    ram_avg_percent REAL,
    ram_peak_percent REAL,
    gpu_avg_percent REAL,
    gpu_peak_percent REAL,
    vram_avg_bytes INTEGER,
    vram_peak_bytes INTEGER,
    vram_total_bytes INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_benchmark_runs_profile ON benchmark_runs(profile_id, created_at DESC);
"""

BENCHMARK_EVIDENCE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("sample_count", "INTEGER"),
    ("cpu_avg_percent", "REAL"),
    ("cpu_peak_percent", "REAL"),
    ("ram_avg_percent", "REAL"),
    ("ram_peak_percent", "REAL"),
    ("gpu_avg_percent", "REAL"),
    ("gpu_peak_percent", "REAL"),
    ("vram_avg_bytes", "INTEGER"),
    ("vram_peak_bytes", "INTEGER"),
    ("vram_total_bytes", "INTEGER"),
)


class ModelRepository:
    def __init__(self, database_path: Path):
        self.database_path = database_path

    def connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as db:
            db.executescript(SCHEMA)
            columns = {row[1] for row in db.execute("PRAGMA table_info(model_files)")}
            if "kind" not in columns:
                raise RuntimeError("model_files schema is missing kind column")

            profile_columns = {row[1] for row in db.execute("PRAGMA table_info(launch_profiles)")}
            if "is_default" not in profile_columns:
                db.execute("ALTER TABLE launch_profiles ADD COLUMN is_default INTEGER NOT NULL DEFAULT 0")

            benchmark_columns = {row[1] for row in db.execute("PRAGMA table_info(benchmark_runs)")}
            for name, column_type in BENCHMARK_EVIDENCE_COLUMNS:
                if name not in benchmark_columns:
                    db.execute(f"ALTER TABLE benchmark_runs ADD COLUMN {name} {column_type}")

            default_count = db.execute("SELECT COUNT(*) FROM launch_profiles WHERE is_default = 1").fetchone()[0]
            if default_count == 0:
                preferred = db.execute(
                    "SELECT id FROM launch_profiles WHERE name = 'Qwen local 65K' ORDER BY id LIMIT 1"
                ).fetchone()
                if preferred is None:
                    preferred = db.execute("SELECT id FROM launch_profiles ORDER BY id LIMIT 1").fetchone()
                if preferred is not None:
                    db.execute("UPDATE launch_profiles SET is_default = 1 WHERE id = ?", (preferred[0],))
            elif default_count > 1:
                keep = db.execute("SELECT id FROM launch_profiles WHERE is_default = 1 ORDER BY id LIMIT 1").fetchone()
                db.execute("UPDATE launch_profiles SET is_default = 0")
                if keep is not None:
                    db.execute("UPDATE launch_profiles SET is_default = 1 WHERE id = ?", (keep[0],))

    def upsert_many(self, models: list[ModelFile]) -> int:
        with self.connect() as db:
            for model in models:
                db.execute(
                    """
                    INSERT INTO model_files(path, name, size_bytes, modified_ns, kind)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(path) DO UPDATE SET
                      name=excluded.name,
                      size_bytes=excluded.size_bytes,
                      modified_ns=excluded.modified_ns,
                      kind=excluded.kind,
                      last_seen_at=CURRENT_TIMESTAMP
                    """,
                    (str(model.path), model.name, model.size_bytes, model.modified_ns, model.kind),
                )
        return len(models)

    def list_models(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT path, name, size_bytes, modified_ns, kind, first_seen_at, last_seen_at "
                "FROM model_files ORDER BY kind, name COLLATE NOCASE"
            ).fetchall()
            return [dict(row) for row in rows]

    def create_profile(
        self,
        *,
        name: str,
        model_path: str,
        projector_path: str | None,
        context_size: int,
        gpu_layers: int,
        host: str,
        port: int,
        extra_args: list[str] | None = None,
    ) -> dict:
        with self.connect() as db:
            existing = db.execute("SELECT COUNT(*) FROM launch_profiles").fetchone()[0]
            cursor = db.execute(
                """
                INSERT INTO launch_profiles(
                    name, runtime_id, model_path, projector_path,
                    context_size, gpu_layers, host, port, extra_args_json, is_default
                ) VALUES (?, 'llama.cpp', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    model_path,
                    projector_path,
                    context_size,
                    gpu_layers,
                    host,
                    port,
                    json.dumps(extra_args or []),
                    1 if existing == 0 else 0,
                ),
            )
            profile_id = int(cursor.lastrowid)
        profile = self.get_profile(profile_id)
        if profile is None:
            raise RuntimeError("failed to reload launch profile")
        return profile

    def list_profiles(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT id, name, runtime_id, model_path, projector_path,
                       context_size, gpu_layers, host, port, extra_args_json, is_default,
                       created_at, updated_at
                FROM launch_profiles
                ORDER BY is_default DESC, name COLLATE NOCASE
                """
            ).fetchall()
        return [self._profile_dict(row) for row in rows]

    def get_profile(self, profile_id: int) -> dict | None:
        with self.connect() as db:
            row = db.execute(
                """
                SELECT id, name, runtime_id, model_path, projector_path,
                       context_size, gpu_layers, host, port, extra_args_json, is_default,
                       created_at, updated_at
                FROM launch_profiles WHERE id = ?
                """,
                (profile_id,),
            ).fetchone()
        return self._profile_dict(row) if row else None

    @staticmethod
    def _profile_dict(row: sqlite3.Row) -> dict:
        result = dict(row)
        result["extra_args"] = json.loads(result.pop("extra_args_json"))
        result["is_default"] = bool(result.get("is_default"))
        return result

    def update_profile(
        self,
        profile_id: int,
        *,
        name: str,
        model_path: str,
        projector_path: str | None,
        context_size: int,
        gpu_layers: int,
        host: str,
        port: int,
        extra_args: list[str] | None = None,
    ) -> dict | None:
        with self.connect() as db:
            cursor = db.execute(
                """
                UPDATE launch_profiles
                SET name = ?, model_path = ?, projector_path = ?, context_size = ?,
                    gpu_layers = ?, host = ?, port = ?, extra_args_json = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    name,
                    model_path,
                    projector_path,
                    context_size,
                    gpu_layers,
                    host,
                    port,
                    json.dumps(extra_args or []),
                    profile_id,
                ),
            )
            if cursor.rowcount == 0:
                return None
        return self.get_profile(profile_id)

    def set_default_profile(self, profile_id: int) -> dict | None:
        with self.connect() as db:
            exists = db.execute("SELECT id FROM launch_profiles WHERE id = ?", (profile_id,)).fetchone()
            if exists is None:
                return None
            db.execute("UPDATE launch_profiles SET is_default = 0 WHERE is_default = 1")
            db.execute(
                "UPDATE launch_profiles SET is_default = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (profile_id,),
            )
        return self.get_profile(profile_id)

    def duplicate_profile(self, profile_id: int, new_name: str) -> dict | None:
        source = self.get_profile(profile_id)
        if source is None:
            return None
        return self.create_profile(
            name=new_name,
            model_path=source["model_path"],
            projector_path=source["projector_path"],
            context_size=int(source["context_size"]),
            gpu_layers=int(source["gpu_layers"]),
            host=source["host"],
            port=int(source["port"]),
            extra_args=list(source["extra_args"]),
        )

    def delete_profile(self, profile_id: int) -> bool:
        with self.connect() as db:
            row = db.execute("SELECT is_default FROM launch_profiles WHERE id = ?", (profile_id,)).fetchone()
            if row is None:
                return False
            was_default = bool(row[0])
            db.execute("DELETE FROM launch_profiles WHERE id = ?", (profile_id,))
            if was_default:
                replacement = db.execute("SELECT id FROM launch_profiles ORDER BY id LIMIT 1").fetchone()
                if replacement is not None:
                    db.execute("UPDATE launch_profiles SET is_default = 1 WHERE id = ?", (replacement[0],))
        return True

    def set_runtime_lease(
        self,
        *,
        runtime_id: str,
        pid: int,
        profile_id: int | None,
        executable_path: str,
        host: str | None,
        port: int | None,
        model_path: str | None,
        command: list[str],
    ) -> dict:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO managed_runtimes(
                    runtime_id, pid, profile_id, executable_path, host, port,
                    model_path, command_json, started_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(runtime_id) DO UPDATE SET
                    pid=excluded.pid,
                    profile_id=excluded.profile_id,
                    executable_path=excluded.executable_path,
                    host=excluded.host,
                    port=excluded.port,
                    model_path=excluded.model_path,
                    command_json=excluded.command_json,
                    started_at=CURRENT_TIMESTAMP,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    runtime_id,
                    int(pid),
                    profile_id,
                    executable_path,
                    host,
                    port,
                    model_path,
                    json.dumps(command),
                ),
            )
        lease = self.get_runtime_lease(runtime_id)
        if lease is None:
            raise RuntimeError("failed to reload managed runtime record")
        return lease

    def get_runtime_lease(self, runtime_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute(
                """
                SELECT runtime_id, pid, profile_id, executable_path, host, port,
                       model_path, command_json, started_at, updated_at
                FROM managed_runtimes WHERE runtime_id = ?
                """,
                (runtime_id,),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["command"] = json.loads(result.pop("command_json"))
        return result

    def clear_runtime_lease(self, runtime_id: str) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM managed_runtimes WHERE runtime_id = ?", (runtime_id,))

    def save_benchmark(self, profile: dict, result: dict, evidence: dict | None = None) -> dict:
        evidence = evidence or {}
        with self.connect() as db:
            cursor = db.execute(
                """
                INSERT INTO benchmark_runs(
                    profile_id, profile_name, model_path, elapsed_seconds,
                    prompt_tokens, completion_tokens, tokens_per_second,
                    server_tokens_per_second, sample_count,
                    cpu_avg_percent, cpu_peak_percent, ram_avg_percent, ram_peak_percent,
                    gpu_avg_percent, gpu_peak_percent, vram_avg_bytes, vram_peak_bytes,
                    vram_total_bytes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(profile["id"]),
                    str(profile["name"]),
                    str(profile["model_path"]),
                    float(result["elapsed_seconds"]),
                    result.get("prompt_tokens"),
                    result.get("completion_tokens"),
                    result.get("tokens_per_second"),
                    result.get("server_tokens_per_second"),
                    evidence.get("sample_count"),
                    evidence.get("cpu_avg_percent"),
                    evidence.get("cpu_peak_percent"),
                    evidence.get("ram_avg_percent"),
                    evidence.get("ram_peak_percent"),
                    evidence.get("gpu_avg_percent"),
                    evidence.get("gpu_peak_percent"),
                    evidence.get("vram_avg_bytes"),
                    evidence.get("vram_peak_bytes"),
                    evidence.get("vram_total_bytes"),
                ),
            )
            benchmark_id = int(cursor.lastrowid)
            row = db.execute("SELECT * FROM benchmark_runs WHERE id = ?", (benchmark_id,)).fetchone()
        if row is None:
            raise RuntimeError("failed to reload benchmark result")
        return dict(row)

    def list_benchmarks(self, limit: int = 20) -> list[dict]:
        safe_limit = min(max(int(limit), 1), 100)
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT *
                FROM benchmark_runs
                ORDER BY id DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def integrity(self) -> str:
        with self.connect() as db:
            row = db.execute("PRAGMA integrity_check").fetchone()
            return str(row[0])
