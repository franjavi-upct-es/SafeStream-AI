# services/inference/src/cli.py
"""Single binary, three roles.

Run as a module:

  * ``python -m cli api``         - FastAPI HTTP server only
  * ``python -m cli worker``      - Kafka moderation worker
  * ``python -m cli broadcaster`` - Kafka -> WebSocket fan-out

The legacy ``uvicorn main:app`` entry point still works for
backwards compatibility and runs everything in one process when
``WORKER_ENABLED`` and ``BROADCASTER_ENABLED`` are true.

Splitting the roles into separate containers lets us scale them
independently and stops a slow worker from starving the API event loop.
"""

from __future__ import annotations

import asyncio
import signal
import sys
from typing import NoReturn

import config
import uvicorn
from app_logging import configure_logging, get_logger
from tracing import setup_tracing

configure_logging()
setup_tracing()
log = get_logger("cli")


def _run_api() -> NoReturn:
    """Start uvicorn for the HTTP API.

    The worker and broadcaster lifespan flags are forced off so that the
    API process never spawns those background tasks even if the env vars
    are set. The dedicated worker/broadcaster commands handle them.
    """
    config.settings.worker_enabled = False
    config.settings.broadcaster_enabled = False
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        log_config=None,  # we already configured structlog
    )
    sys.exit(0)


async def _run_worker() -> None:
    """Standalone Kafka moderation worker.

    The worker still needs the model registry, the database pool and the
    optional vector store - reuses the same lifecycle the API would
    build, just without the FastAPI app on top.
    """
    from models.registry import build_registry
    from persistence.db import close_pool, create_pool
    from persistence.repository import ModerationRepository
    from persistence.vector_store import create_vector_store
    from workers.consumer import InferenceWorker

    log.info("worker_process_starting")
    registry = build_registry()
    pool = await create_pool()
    repo = ModerationRepository(pool)
    vector_store = await create_vector_store()

    worker = InferenceWorker(
        registry=registry,
        repository=repo,
        vector_store=vector_store,
    )
    await worker.start()
    task = asyncio.create_task(worker.run(), name="kafka-worker")

    stop = asyncio.Event()

    def _request_stop(signum: int) -> None:
        log.info("worker_signal_received", signum=signum)
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _request_stop, sig)

    await stop.wait()

    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):  # noqa: BLE001
        pass
    await worker.stop()
    if vector_store is not None:
        await vector_store.aclose()
    await close_pool(pool)
    await registry.aclose()
    log.info("worker_process_stopped")
