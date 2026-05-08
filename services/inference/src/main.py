# services/inference/src/main.py
"""FastAPI application factory.

The lifespan context handles the heavy work that has to happen exactly once
per process:

  * load the requested ML models into RAM,
  * open the asyncpg pool,
  * launch the Kafka consumer task,

and the corresponding teardown in reverse order.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from app_logging import configure_logging, get_logger

from api.deps import limiter
from api.routes_audits import router as audits_router
from api.routes_classify import router as classify_router
from api.routes_events import router as events_router
from api.routes_health import router as health_router
from api.routes_metrics import router as metrics_router
from api.routes_search import router as search_router
from api.routes_stream import router as stream_router
from config import settings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from models.registry import build_registry
from persistence.db import close_pool, create_pool
from persistence.repository import ModerationRepository
from persistence.vector_store import create_vector_store
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from tracing import instrument_app, setup_tracing
from workers.broadcaster import PredictionBroadcaster
from workers.connection_manager import ConnectionManager
from workers.consumer import InferenceWorker

configure_logging()
setup_tracing()
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info(
        "service_starting",
        service=settings.service_name,
        text_enabled=settings.enable_text,
        vision_enabled=settings.enable_vision,
        embeddings_enabled=settings.enable_embeddings,
        worker_enabled=settings.worker_enabled,
        broadcaster_enabled=settings.broadcaster_enabled,
    )

    # 1. Models (synchronous load - downloads weights on first run).
    app.state.models = build_registry()

    # 2. Database pool.
    app.state.db_pool = await create_pool()
    repository = ModerationRepository(app.state.db_pool)

    # 3. Vector store (best-effort - search returns 503 if unavailable).
    app.state.vector_store = await create_vector_store()

    # 4. WebSocket connection manager (always created, even if broadcaster
    #    is disabled - the route still accepts clients, they just see no
    #    events).
    app.state.ws_manager = ConnectionManager()

    # 5. Kafka worker (moderation pipeline).
    worker_task: asyncio.Task[None] | None = None
    worker: InferenceWorker | None = None
    if settings.worker_enabled:
        worker = InferenceWorker(
            registry=app.state.models,
            repository=repository,
            vector_store=app.state.vector_store,
        )
        await worker.start()
        worker_task = asyncio.create_task(worker.run(), name="kafka-worker")
        app.state.worker = worker
        app.state.worker_task = worker_task
    else:
        log.warning("worker_disabled_by_config")
        app.state.worker = None
        app.state.worker_task = None

    # 6. Broadcaster (Kafka -> WebSocket fan-out).
    broadcaster_task: asyncio.Task[None] | None = None
    broadcaster: PredictionBroadcaster | None = None
    if settings.broadcaster_enabled:
        broadcaster = PredictionBroadcaster(app.state.ws_manager)
        await broadcaster.start()
        broadcaster_task = asyncio.create_task(
            broadcaster.run(),
            name="kafka-broadcaster",
        )
        app.state.broadcaster = broadcaster
        app.state.broadcaster_task = broadcaster_task
    else:
        log.warning("broadcaster_disabled_by_config")
        app.state.broadcaster = None
        app.state.broadcaster_task = None

    try:
        yield
    finally:
        log.info("service_stopping")

        # Reverse-order teardown.
        if broadcaster_task is not None and broadcaster is not None:
            broadcaster_task.cancel()
            try:
                await broadcaster_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 - teardown
                pass
            await broadcaster.stop()

        if worker_task is not None and worker is not None:
            worker_task.cancel()
            try:
                await worker_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 - teardown
                pass
            await worker.stop()

        await app.state.ws_manager.close_all()
        if app.state.vector_store is not None:
            await app.state.vector_store.aclose()
        await close_pool(app.state.db_pool)
        await app.state.models.aclose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="SafeStream AI - Inference Service",
        version="0.4.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )

    # CORS (the dashboard calls /api/* through nginx but dev mode hits us
    # directly from Vite at 5173).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Rate limiting wiring (slowapi).
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    # Prometheus: histogram of request durations + counter of in-progress
    # requests, scoped per route. Mount BEFORE include_router so the
    # instrumentator wraps every endpoint we register below. Exposed at
    # /metrics by default; the path is excluded from its own measurements
    # to avoid measuring scraping itself.
    Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        should_instrument_requests_inprogress=True,
        excluded_handlers=["/metrics", "/healthz"],
        inprogress_name="safestream_inflight_requests",
        inprogress_labels=True,
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

    app.include_router(health_router)
    app.include_router(classify_router)
    app.include_router(search_router)
    app.include_router(events_router)
    app.include_router(audits_router)
    app.include_router(metrics_router)
    app.include_router(stream_router)

    # Wrap the fully-routed app with OpenTelemetry so route templates
    # appear as span names instead of raw URL paths.
    instrument_app(app)

    return app


app = create_app()
