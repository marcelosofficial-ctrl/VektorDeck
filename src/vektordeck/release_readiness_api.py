from __future__ import annotations

from fastapi import APIRouter

from .config import Settings
from .release_readiness import assess_release_readiness


def build_release_readiness_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/release-readiness", tags=["release-readiness"])

    @router.get("")
    def release_readiness() -> dict:
        return assess_release_readiness(
            database_path=settings.database_path,
            llama_server_path=settings.llama_server_path,
            a1111_launch_path=settings.a1111_launch_path,
            hermes_cli_path=settings.hermes_cli_path,
        )

    return router
