# services/inference/src/api/routes_health.py
"""Liveness and readiness endpoints.

``/healthz`` is cheap and always 200 once the process is up. Container
orchestrators use it to decide whether to restart.

``/readyz`` is more expensive: it reports whether the requested models loaded
and whether Postgres is reachable. The compose stack waits on this before
routing traffic.
"""

from __future__ import annotations

from api.schemas import HealthResponse, ReadinessResponse
from config import settings
from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    return HealthResponse(status="ok", service=settings.service_name)


@router.get("/readyz", response_model=ReadinessResponse)
async def readyz(request: Request) -> ReadinessResponse:
    registry = getattr(request.app.state, "models", None)
    pool = getattr(request.app.state, "db_pool", None)
    vector_store = getattr(request.app.state, "vector_store", None)

    db_ok = False
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            db_ok = True
        except Exception:  # noqa: BLE001 - readiness must never raise
            db_ok = False

    vector_ok = False
    if vector_store is not None:
        try:
            # collection_exists is a cheap RPC against Qdrant
            await vector_store._client.collection_exists(  # noqa: SLF001
                vector_store.collection
            )
            vector_ok = True
        except Exception:  # noqa: BLE001 - readiness must never raise
            vector_ok = False

    text_loaded = bool(registry and registry.text is not None)
    vision_loaded = bool(registry and registry.vision is not None)
    embedder_loaded = bool(registry and registry.embedder is not None)

    overall = "ok"
    if settings.enable_text and not text_loaded:
        overall = "degraded"
    if settings.enable_vision and not vision_loaded:
        overall = "degraded"
    if settings.enable_embeddings and not embedder_loaded:
        overall = "degraded"
    if not db_ok:
        overall = "degraded"
    if settings.enable_embeddings and not vector_ok:
        overall = "degraded"

    return ReadinessResponse(
        status=overall,
        text_model_loaded=text_loaded,
        vision_model_loaded=vision_loaded,
        embedder_loaded=embedder_loaded,
        database_reachable=db_ok,
        vector_store_reachable=vector_ok,
    )
