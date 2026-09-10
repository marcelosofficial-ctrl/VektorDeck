from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .benchmark_protocol import ALLOWED_SOURCES, BenchmarkProtocolRepository
from .config import Settings
from .database import ModelRepository
from .process_inspector import top_processes


class BenchmarkProtocolCreate(BaseModel):
    run_source: str = Field(default="manual")
    baseline: dict[str, Any]
    contaminators: list[dict[str, Any]] = Field(default_factory=list)


def build_benchmark_protocol_router(settings: Settings) -> APIRouter:
    router = APIRouter(tags=["benchmark-protocol"])
    protocols = BenchmarkProtocolRepository(settings.database_path)
    protocols.initialize()
    benchmarks = ModelRepository(settings.database_path)

    @router.get("/api/processes/top")
    def process_snapshot(limit: int = 8) -> dict[str, Any]:
        return {"processes": top_processes(limit=limit)}

    @router.post("/api/benchmark-protocol/{benchmark_id}", status_code=201)
    def save_protocol(benchmark_id: int, payload: BenchmarkProtocolCreate) -> dict[str, Any]:
        if payload.run_source not in ALLOWED_SOURCES:
            raise HTTPException(
                status_code=400,
                detail=f"run_source must be one of: {', '.join(sorted(ALLOWED_SOURCES))}",
            )
        if not any(int(run["id"]) == int(benchmark_id) for run in benchmarks.list_benchmarks(limit=100)):
            raise HTTPException(status_code=404, detail="benchmark run not found")
        return protocols.save(
            benchmark_id,
            run_source=payload.run_source,
            baseline=payload.baseline,
            contaminators=payload.contaminators,
        )

    @router.get("/api/benchmark-protocol/{benchmark_id}")
    def protocol(benchmark_id: int) -> dict[str, Any]:
        result = protocols.get(benchmark_id)
        if result is None:
            raise HTTPException(status_code=404, detail="benchmark protocol record not found")
        return result

    @router.get("/api/benchmark-protocol")
    def protocol_history(limit: int = 100) -> list[dict[str, Any]]:
        return protocols.list_recent(limit=limit)

    return router
