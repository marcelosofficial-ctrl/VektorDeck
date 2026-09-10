from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException

from .config import Settings
from .database import ModelRepository
from .model_compatibility import profile_readiness, projector_pairing_hints
from .model_intelligence import ModelIntelligenceRepository


def _norm(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def build_model_intelligence_router(settings: Settings) -> APIRouter:
    router = APIRouter(tags=["model-intelligence"])
    models = ModelRepository(settings.database_path)
    intelligence = ModelIntelligenceRepository(settings.database_path)
    intelligence.initialize()

    def enriched_items() -> list[dict]:
        indexed = {_norm(str(item['path'])): item for item in models.list_models()}
        results: list[dict] = []
        for item in intelligence.list_all():
            indexed_item = indexed.get(_norm(str(item['path'])))
            results.append({
                **item,
                'kind': indexed_item.get('kind') if indexed_item else 'unknown',
                'indexed_name': indexed_item.get('name') if indexed_item else Path(str(item['path'])).name,
            })
        return results

    @router.get('/api/model-intelligence')
    def list_model_intelligence() -> list[dict]:
        return enriched_items()

    @router.get('/api/model-intelligence/item')
    def model_intelligence_item(path: str) -> dict:
        item = next((candidate for candidate in enriched_items() if _norm(str(candidate['path'])) == _norm(path)), None)
        if item is None:
            raise HTTPException(status_code=404, detail='model intelligence not found')
        return item

    @router.get('/api/model-intelligence/pairings')
    def model_pairings() -> list[dict]:
        return projector_pairing_hints(models.list_models())

    @router.get('/api/model-intelligence/profiles')
    def profile_compatibility() -> list[dict]:
        indexed = models.list_models()
        metadata = intelligence.list_all()
        return [profile_readiness(profile, indexed, metadata) for profile in models.list_profiles()]

    @router.get('/api/model-intelligence/profiles/{profile_id}')
    def profile_compatibility_item(profile_id: int) -> dict:
        profile = models.get_profile(profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail='launch profile not found')
        return profile_readiness(profile, models.list_models(), intelligence.list_all())

    @router.post('/api/model-intelligence/scan')
    def scan_model_intelligence() -> dict:
        indexed = models.list_models()
        candidates = [item for item in indexed if item.get('kind') in {'model', 'projector'}]
        inspected = 0
        cached = 0
        errors = 0
        results: list[dict] = []

        for item in candidates:
            path = Path(str(item['path']))
            if path.suffix.lower() != '.gguf' or not path.is_file():
                continue
            existing = intelligence.get(str(path.resolve()))
            unchanged = bool(
                existing
                and int(existing['modified_ns']) == int(item['modified_ns'])
                and int(existing['size_bytes']) == int(item['size_bytes'])
            )
            result = intelligence.inspect_if_needed(
                path,
                modified_ns=int(item['modified_ns']),
                size_bytes=int(item['size_bytes']),
            )
            enriched = {**result, 'kind': item.get('kind', 'unknown'), 'indexed_name': item.get('name', path.name)}
            if unchanged:
                cached += 1
            else:
                inspected += 1
            if result.get('status') == 'error':
                errors += 1
            results.append(enriched)

        return {
            'candidates': len(candidates),
            'inspected': inspected,
            'cached': cached,
            'errors': errors,
            'results': results,
            'pairings': projector_pairing_hints(indexed),
            'profiles': [profile_readiness(profile, indexed, results) for profile in models.list_profiles()],
        }

    return router
