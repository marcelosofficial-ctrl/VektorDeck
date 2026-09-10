from __future__ import annotations

from .api import app
from .benchmark_protocol_api import build_benchmark_protocol_router
from .config import Settings
from .model_intelligence_api import build_model_intelligence_router
from .recommendations_api import build_recommendations_router
from .release_readiness_api import build_release_readiness_router

_settings = Settings.from_env()
app.include_router(build_model_intelligence_router(_settings))
app.include_router(build_recommendations_router(_settings))
app.include_router(build_benchmark_protocol_router(_settings))
app.include_router(build_release_readiness_router(_settings))
