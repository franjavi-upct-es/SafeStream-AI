# services/inference/tests/conftest.py
"""Shared pytest fixtures.

The unit tests run without live Kafka, Postgres or Qdrant. Heavy ML
dependencies (transformers, sentence_transformers) are stubbed at import
time so the module graph still resolves.

Run with::

    pytest services/inference/tests
"""

from __future__ import annotations

import sys
import types
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest


# ---------------------------------------------------------------------------
# Stub heavy ML libraries before any application code imports them.
# ---------------------------------------------------------------------------
def _install_ml_stubs() -> None:
    if "transformers" not in sys.modules:
        fake = types.ModuleType("transformers")

        def _pipeline(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("transformers is stubbed in the test suite")

        fake.pipeline = _pipeline
        sys.modules["transformers"] = fake

    if "sentence_transformers" not in sys.modules:
        fake = types.ModuleType("sentence_transformers")

        class _SentenceTransformer:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                raise RuntimeError(
                    "sentence_transformers is stubbed in the test suite"
                )

        fake.SentenceTransformer = _SentenceTransformer
        sys.modules["sentence_transformers"] = fake


_install_ml_stubs()


# ---------------------------------------------------------------------------
# Settings: force the service to skip real infra, before importing modules
# that read settings at import time.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _disable_external_dependencies() -> None:
    """Make every test boot with all heavy machinery off."""
    import config

    config.settings.enable_text = False
    config.settings.enable_vision = False
    config.settings.enable_embeddings = False
    config.settings.worker_enabled = False
    config.settings.broadcaster_enabled = False
    config.settings.api_keys = []
    config.settings.cors_origins = ["*"]


# ---------------------------------------------------------------------------
# Fake asyncpg connection pool.
# ---------------------------------------------------------------------------
class FakeConnection:
    """Minimal stand-in for an asyncpg connection.

    Routes are matched by a discriminating substring so individual tests
    can override behaviour without re-implementing the whole class.
    """

    def __init__(
        self,
        *,
        fetch: Callable[[str, tuple[Any, ...]], list[dict[str, Any]]]
        | None = None,
        fetchrow: Callable[[str, tuple[Any, ...]], dict[str, Any] | None]
        | None = None,
        fetchval: Callable[[str, tuple[Any, ...]], Any] | None = None,
        execute: Callable[[str, tuple[Any, ...]], None] | None = None,
    ) -> None:
        self._fetch = fetch
        self._fetchrow = fetchrow
        self._fetchval = fetchval
        self._execute = execute

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        if self._fetch is None:
            return []
        return self._fetch(query, args)

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        if self._fetchrow is None:
            return None
        return self._fetchrow(query, args)

    async def fetchval(self, query: str, *args: Any) -> Any:
        if self._fetchval is None:
            if "SELECT 1" in query:
                return 1
            return None
        return self._fetchval(query, args)

    async def execute(self, query: str, *args: Any) -> None:
        if self._execute is None:
            return None
        return self._execute(query, args)

    async def transaction(self) -> FakeTransaction:  # pragma: no cover
        return FakeTransaction()


class FakeTransaction:
    async def __aenter__(self) -> FakeTransaction:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None


class FakePool:
    """An asyncpg.Pool look-alike whose ``acquire()`` is an async CM."""

    def __init__(self, conn: FakeConnection | None = None) -> None:
        self._conn = conn or FakeConnection()

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[FakeConnection]:
        yield self._conn


@pytest.fixture
def fake_pool() -> FakePool:
    return FakePool()


# ---------------------------------------------------------------------------
# FastAPI app factory bound to fakes.
# ---------------------------------------------------------------------------
@pytest.fixture
def app(fake_pool: FakePool):  # type: ignore[no-untyped-def]
    """Build a fully wired FastAPI app with the lifespan bypassed.

    We don't run the real lifespan because it tries to talk to Kafka and
    Postgres. Instead, we mount every router and seed ``app.state``
    manually with fakes the tests can swap.
    """
    from api.deps import limiter
    from api.routes_audits import router as audits_router
    from api.routes_classify import router as classify_router
    from api.routes_events import router as events_router
    from api.routes_health import router as health_router
    from api.routes_metrics import router as metrics_router
    from api.routes_search import router as search_router
    from api.routes_stream import router as stream_router
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from prometheus_fastapi_instrumentator import Instrumentator
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from slowapi.middleware import SlowAPIMiddleware

    application = FastAPI()
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.state.limiter = limiter
    application.add_exception_handler(
        RateLimitExceeded,
        _rate_limit_exceeded_handler,
    )
    application.add_middleware(SlowAPIMiddleware)

    # Match production wiring so /metrics is testable. We clear the
    # default prometheus_client registry between tests because the
    # in-flight gauge collector registers itself there even when we pass
    # a custom registry to the Instrumentator, and pytest reuses the
    # same Python process across tests.
    from prometheus_client import REGISTRY

    for collector in list(REGISTRY._collector_to_names):  # noqa: SLF001
        try:
            REGISTRY.unregister(collector)
        except KeyError:
            pass

    Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        should_instrument_requests_inprogress=True,
        excluded_handlers=["/metrics", "/healthz"],
        inprogress_name="safestream_inflight_requests",
        inprogress_labels=True,
    ).instrument(application).expose(
        application,
        endpoint="/metrics",
        include_in_schema=False,
    )

    application.include_router(health_router)
    application.include_router(events_router)
    application.include_router(audits_router)
    application.include_router(metrics_router)
    application.include_router(search_router)
    application.include_router(classify_router)
    application.include_router(stream_router)

    # Default state - tests override as needed.
    class _FakeRegistry:
        text = None
        vision = None
        embedder = None

    application.state.models = _FakeRegistry()
    application.state.db_pool = fake_pool
    application.state.vector_store = None

    return application


@pytest.fixture
async def client(app):  # type: ignore[no-untyped-def]
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Convenience builders.
# ---------------------------------------------------------------------------
@pytest.fixture
def utc_now() -> datetime:
    return datetime.now(UTC)


@pytest.fixture
def event_uuid() -> UUID:
    return uuid4()
