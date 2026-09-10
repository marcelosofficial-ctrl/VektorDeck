from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .benchmark_protocol import BenchmarkProtocolRepository
from .config import Settings
from .database import ModelRepository
from .model_intelligence import ModelIntelligenceRepository
from .recommendations import build_recommendation
from .runtime import inspect_llama_capabilities
from .telemetry import TelemetryService


class RecommendationCreate(BaseModel):
    model_path: str


def build_recommendations_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix='/api/recommendations', tags=['recommendations'])
    models = ModelRepository(settings.database_path)
    intelligence = ModelIntelligenceRepository(settings.database_path)
    protocols = BenchmarkProtocolRepository(settings.database_path)
    intelligence.initialize()
    protocols.initialize()
    telemetry = TelemetryService()
    capabilities = inspect_llama_capabilities(settings.llama_server_path)

    def benchmark_evidence() -> list[dict]:
        protocol_by_id = {
            int(item['benchmark_id']): item
            for item in protocols.list_recent(limit=200)
        }
        runs: list[dict] = []
        for run in models.list_benchmarks(limit=100):
            merged = dict(run)
            protocol = protocol_by_id.get(int(run['id']))
            if protocol:
                merged.update({
                    'protocol_version': protocol.get('protocol_version'),
                    'run_source': protocol.get('run_source'),
                    'baseline_ready': protocol.get('baseline_ready'),
                    'baseline_cpu_avg_percent': protocol.get('baseline_cpu_avg_percent'),
                    'baseline_cpu_peak_percent': protocol.get('baseline_cpu_peak_percent'),
                    'baseline_ram_avg_percent': protocol.get('baseline_ram_avg_percent'),
                    'baseline_gpu_avg_percent': protocol.get('baseline_gpu_avg_percent'),
                })
            runs.append(merged)
        return runs

    def recommendation_for(model_path: str) -> dict:
        snapshot = telemetry.snapshot(cached_gpu_only=False)
        return build_recommendation(
            model_path=model_path,
            indexed_models=models.list_models(),
            intelligence=intelligence.list_all(),
            profiles=models.list_profiles(),
            benchmarks=benchmark_evidence(),
            total_ram_bytes=snapshot.get('memory', {}).get('total_bytes'),
            total_vram_bytes=snapshot.get('gpu', {}).get('vram_total_bytes'),
            capabilities=capabilities,
        )

    @router.get('')
    def recommendation(model_path: str) -> dict:
        result = recommendation_for(model_path)
        if result.get('status') == 'BLOCKED':
            raise HTTPException(status_code=409, detail='; '.join(result.get('reasons', [])))
        return result

    @router.post('/profile', status_code=201)
    def create_recommended_profile(payload: RecommendationCreate) -> dict:
        result = recommendation_for(payload.model_path)
        profile = result.get('profile')
        if result.get('status') == 'BLOCKED' or not isinstance(profile, dict):
            raise HTTPException(status_code=409, detail='recommendation is not launchable')

        try:
            created = models.create_profile(
                name=str(profile['name']),
                model_path=str(profile['model_path']),
                projector_path=str(profile['projector_path']) if profile.get('projector_path') else None,
                context_size=int(profile['context_size']),
                gpu_layers=int(profile['gpu_layers']),
                host=str(profile['host']),
                port=int(profile['port']),
                extra_args=[str(item) for item in profile.get('extra_args', [])],
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail='suggested profile name already exists; refresh recommendation') from exc

        return {
            'created': created,
            'recommendation_status': result['status'],
            'recommendation_source': result['source'],
            'reasons': result['reasons'],
        }

    return router
