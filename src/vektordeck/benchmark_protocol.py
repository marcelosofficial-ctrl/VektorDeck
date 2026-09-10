from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS benchmark_protocol (
    benchmark_id INTEGER PRIMARY KEY,
    protocol_version INTEGER NOT NULL DEFAULT 2,
    run_source TEXT NOT NULL,
    baseline_ready INTEGER NOT NULL CHECK(baseline_ready IN (0, 1)),
    baseline_sample_count INTEGER NOT NULL DEFAULT 0,
    baseline_cpu_avg_percent REAL,
    baseline_cpu_peak_percent REAL,
    baseline_ram_avg_percent REAL,
    baseline_ram_peak_percent REAL,
    baseline_gpu_avg_percent REAL,
    baseline_gpu_peak_percent REAL,
    baseline_reasons_json TEXT NOT NULL DEFAULT '[]',
    contaminators_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

ALLOWED_SOURCES = {"smart_launch", "optimizer", "manual"}


class BenchmarkProtocolRepository:
    def __init__(self, database_path: Path):
        self.database_path = database_path

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(SCHEMA)

    def save(
        self,
        benchmark_id: int,
        *,
        run_source: str,
        baseline: dict[str, Any],
        contaminators: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        source = run_source if run_source in ALLOWED_SOURCES else "manual"
        contaminators = contaminators or []
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO benchmark_protocol(
                    benchmark_id, protocol_version, run_source, baseline_ready,
                    baseline_sample_count, baseline_cpu_avg_percent,
                    baseline_cpu_peak_percent, baseline_ram_avg_percent,
                    baseline_ram_peak_percent, baseline_gpu_avg_percent,
                    baseline_gpu_peak_percent, baseline_reasons_json,
                    contaminators_json
                ) VALUES (?, 2, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(benchmark_id) DO UPDATE SET
                    protocol_version=2,
                    run_source=excluded.run_source,
                    baseline_ready=excluded.baseline_ready,
                    baseline_sample_count=excluded.baseline_sample_count,
                    baseline_cpu_avg_percent=excluded.baseline_cpu_avg_percent,
                    baseline_cpu_peak_percent=excluded.baseline_cpu_peak_percent,
                    baseline_ram_avg_percent=excluded.baseline_ram_avg_percent,
                    baseline_ram_peak_percent=excluded.baseline_ram_peak_percent,
                    baseline_gpu_avg_percent=excluded.baseline_gpu_avg_percent,
                    baseline_gpu_peak_percent=excluded.baseline_gpu_peak_percent,
                    baseline_reasons_json=excluded.baseline_reasons_json,
                    contaminators_json=excluded.contaminators_json
                """,
                (
                    int(benchmark_id),
                    source,
                    1 if baseline.get("ready") else 0,
                    int(baseline.get("sample_count") or 0),
                    baseline.get("cpu_avg_percent"),
                    baseline.get("cpu_peak_percent"),
                    baseline.get("ram_avg_percent"),
                    baseline.get("ram_peak_percent"),
                    baseline.get("gpu_avg_percent"),
                    baseline.get("gpu_peak_percent"),
                    json.dumps(list(baseline.get("reasons") or [])),
                    json.dumps(contaminators[:12]),
                ),
            )
        stored = self.get(int(benchmark_id))
        if stored is None:
            raise RuntimeError("failed to reload benchmark protocol record")
        return stored

    def get(self, benchmark_id: int) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM benchmark_protocol WHERE benchmark_id = ?",
                (int(benchmark_id),),
            ).fetchone()
        return self._decode(row) if row else None

    def list_recent(self, limit: int = 100) -> list[dict[str, Any]]:
        safe_limit = min(max(int(limit), 1), 200)
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM benchmark_protocol ORDER BY benchmark_id DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        return [self._decode(row) for row in rows]

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["baseline_ready"] = bool(result["baseline_ready"])
        result["baseline_reasons"] = json.loads(result.pop("baseline_reasons_json"))
        result["contaminators"] = json.loads(result.pop("contaminators_json"))
        return result
