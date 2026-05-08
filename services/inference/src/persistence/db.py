# services/inference/src/persistence/db.py
"""Async PostgreSQL pool used by both the worker and the API."""

from __future__ import annotations

import asyncio
from app_logging import get_logger

import asyncpg
from config import settings

log = get_logger(__name__)


async def create_pool() -> asyncpg.Pool:
    """Open the asyncpg pool, retrying briefly while Postgres is starting."""

    last_error: Exception | None = None
    for attempt in range(1, 11):
        try:
            pool = await asyncpg.create_pool(
                dsn=settings.postgres_dsn,
                min_size=settings.db_min_pool,
                max_size=settings.db_max_pool,
                command_timeout=15,
            )
            # Quick sanity check that the schema is in place.
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            log.info(
                "postgres_pool_ready",
                min_pool=settings.db_min_pool,
                max_pool=settings.db_max_pool,
            )
            return pool
        except (OSError, asyncpg.PostgresError) as exc:
            last_error = exc
            wait = min(2**attempt, 15)
            log.warning(
                "postgres_connection_retry",
                attempt=attempt,
                wait_seconds=wait,
                error=str(exc),
            )
            await asyncio.sleep(wait)

    raise RuntimeError(
        f"Could not connect to Postgres at {settings.postgres_dsn}: {last_error}"
    )


async def close_pool(pool: asyncpg.Pool | None) -> None:
    if pool is None:
        return
    await pool.close()
    log.info("postgres_pool_closed")
