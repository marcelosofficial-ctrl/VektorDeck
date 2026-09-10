from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .gguf import GGUFError, inspect_gguf, summarize_gguf

SCHEMA = """
CREATE TABLE IF NOT EXISTS model_intelligence (
    path TEXT PRIMARY KEY,
    modified_ns INTEGER NOT NULL,
    size_bytes INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('ok','error')),
    error TEXT,
    gguf_version INTEGER,
    tensor_count INTEGER,
    metadata_count INTEGER,
    architecture TEXT,
    display_name TEXT,
    context_length INTEGER,
    parameter_count INTEGER,
    size_label TEXT,
    file_type INTEGER,
    quantization_version INTEGER,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    inspected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class ModelIntelligenceRepository:
    def __init__(self, database_path: Path):
        self.database_path = database_path

    def connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        with self.connect() as db:
            db.executescript(SCHEMA)

    def get(self, path: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM model_intelligence WHERE path = ?", (path,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["metadata"] = json.loads(result.pop("metadata_json") or "{}")
        return result

    def list_all(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM model_intelligence ORDER BY path COLLATE NOCASE").fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
            results.append(item)
        return results

    def inspect_if_needed(self, path: Path, *, modified_ns: int, size_bytes: int) -> dict[str, Any]:
        resolved = str(path.resolve())
        cached = self.get(resolved)
        if cached and cached["modified_ns"] == int(modified_ns) and cached["size_bytes"] == int(size_bytes):
            return cached

        try:
            summary = summarize_gguf(inspect_gguf(path))
            payload = {
                "status": "ok",
                "error": None,
                **summary,
            }
        except (OSError, GGUFError, ValueError) as exc:
            payload = {
                "status": "error",
                "error": str(exc)[:500],
                "gguf_version": None,
                "tensor_count": None,
                "metadata_count": None,
                "architecture": None,
                "display_name": None,
                "context_length": None,
                "parameter_count": None,
                "size_label": None,
                "file_type": None,
                "quantization_version": None,
                "metadata": {},
            }

        with self.connect() as db:
            db.execute(
                """
                INSERT INTO model_intelligence(
                    path, modified_ns, size_bytes, status, error, gguf_version,
                    tensor_count, metadata_count, architecture, display_name,
                    context_length, parameter_count, size_label, file_type,
                    quantization_version, metadata_json, inspected_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(path) DO UPDATE SET
                    modified_ns=excluded.modified_ns,
                    size_bytes=excluded.size_bytes,
                    status=excluded.status,
                    error=excluded.error,
                    gguf_version=excluded.gguf_version,
                    tensor_count=excluded.tensor_count,
                    metadata_count=excluded.metadata_count,
                    architecture=excluded.architecture,
                    display_name=excluded.display_name,
                    context_length=excluded.context_length,
                    parameter_count=excluded.parameter_count,
                    size_label=excluded.size_label,
                    file_type=excluded.file_type,
                    quantization_version=excluded.quantization_version,
                    metadata_json=excluded.metadata_json,
                    inspected_at=CURRENT_TIMESTAMP
                """,
                (
                    resolved,
                    int(modified_ns),
                    int(size_bytes),
                    payload["status"],
                    payload["error"],
                    payload["gguf_version"],
                    payload["tensor_count"],
                    payload["metadata_count"],
                    payload["architecture"],
                    payload["display_name"],
                    payload["context_length"],
                    payload["parameter_count"],
                    payload["size_label"],
                    payload["file_type"],
                    payload["quantization_version"],
                    json.dumps(payload["metadata"], ensure_ascii=False),
                ),
            )
        result = self.get(resolved)
        if result is None:
            raise RuntimeError("failed to persist model intelligence")
        return result
