# services/inference/src/persistence/vector_store.py
"""Qdrant client used by the worker (writes) and the search API (reads).

Two design notes worth surfacing:

  1. **Idempotent init.** ``ensure_collection`` is safe to call repeatedly.
     If a collection already exists with a different vector size we raise -
     mixing dimensions inside one collection produces silently bad results.

  2. **Best-effort indexing.** The worker calls ``index`` after the SQL
     write has succeeded and the Kafka offset has been committed. A failure
     here logs a warning and moves on; moderation must not stop because the
     vector store is unhealthy.
"""

import asyncio
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app_logging import get_logger
from config import settings
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SearchHit:
    """A single semantic search result."""

    event_id: UUID
    score: float
    payload: dict[str, Any]


class VectorStore:
    """Thin async wrapper around the Qdrant client."""

    def __init__(
        self,
        *,
        url: str,
        api_key: str,
        collection: str,
        vector_size: int,
    ) -> None:
        self._client = AsyncQdrantClient(url=url, api_key=api_key)
        self._collection = collection
        self._vector_size = vector_size

    @property
    def collection(self) -> str:
        return self._collection

    @property
    def vector_size(self) -> int:
        return self._vector_size

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def ensure_collection(self) -> None:
        """Create the collection if it does not already exist (idempotent)."""

        exists = await self._client.collection_exists(self._collection)
        if exists:
            info = await self._client.get_collection(self._collection)
            existing_size = info.config.params.vectors.size
            if existing_size != self._vector_size:
                raise RuntimeError(
                    f"Qdrant collection {self._collection!r} already exists "
                    f"with vector size {existing_size}, but the embedder "
                    f"produces {self._vector_size}-dim vectors. Drop the "
                    f"collection or change EMBEDDING_DIM to match."
                )
            log.info(
                "qdrant_collection_ready",
                collection=self._collection,
                size=existing_size,
            )
            return

        await self._client.create_collection(
            collection_name=self._collection,
            vectors_config=qmodels.VectorParams(
                size=self._vector_size,
                distance=qmodels.Distance.COSINE,
            ),
        )
        # Index the payload fields used in filters so queries don't fall back
        # to a full scan
        for field_name, field_schema in (
            ("verdict", qmodels.PayloadSchemaType.KEYWORD),
            ("modality", qmodels.PayloadSchemaType.KEYWORD),
        ):
            await self._client.create_payload_index(
                collection_name=self._collection,
                field_name=field_name,
                field_schema=field_schema,
            )
        log.info(
            "qdrant_collection_created",
            collection=self._collection,
            size=self._vector_size,
        )

    async def aclose(self) -> None:
        await self._client.close()

    # ------------------------------------------------------------------
    # Write path (worker)
    # ------------------------------------------------------------------
    async def index(
        self,
        *,
        event_id: UUID,
        vector: Sequence[float],
        payload: dict[str, Any],
    ) -> None:
        """Upsert a single point. Validates the vector size up front."""

        if len(vector) != self._vector_size:
            raise ValueError(
                f"Vector dimension mismatch: got {len(vector)}, "
                f"expected {self._vector_size}"
            )

        point = qmodels.PointStruct(
            id=str(event_id),
            vector=list(vector),
            payload=payload,
        )
        await self._client.upsert(
            collection_name=self._collection,
            points=[point],
            wait=False,  # don't block the worker on disk fsync
        )

    # ------------------------------------------------------------------
    # Read path (search endpoint)
    # ------------------------------------------------------------------
    async def search(
        self,
        *,
        vector: Sequence[float],
        limit: int = 10,
        verdicts: Iterable[str] | None = None,
        min_score: float | None = None,
    ) -> list[SearchHit]:
        """Cosine-similarity search with optional verdict filter."""

        if len(vector) != self._vector_size:
            raise ValueError(
                f"Query vector dimension mismatch: got {len(vector)}, "
                f"expected {self._vector_size}"
            )

        query_filter: qmodels.Filter | None = None
        verdicts_list = list(verdicts or [])
        if verdicts_list:
            query_filter = qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="verdict",
                        match=qmodels.MatchAny(any=verdicts_list),
                    )
                ]
            )

        response = await self._client.query_points(
            collection_name=self._collection,
            query=list(vector),
            limit=limit,
            with_payload=True,
            query_filter=query_filter,
            score_threshold=min_score,
        )

        hits: list[SearchHit] = []
        for point in response.points:
            try:
                event_uuid = UUID(str(point.id))
            except (ValueError, TypeError):
                # Skip non-UUID points (shouldn't happen, but be defensive)
                continue
            hits.append(
                SearchHit(
                    event_id=event_uuid,
                    score=float(point.score),
                    payload=dict(point.payload or {}),
                )
            )
        return hits


async def create_vector_store() -> VectorStore | None:
    """Build the store and try to initialize the collection.

    On failure the function returns ``None`` instead of raising. The lifespan
    treats that as "search is unavailable but the rest of the service runs".
    """

    if not settings.enable_embeddings:
        log.info("vector_store_disabled")
        return None

    store = VectorStore(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
        collection=settings.qdrant_collection,
        vector_size=settings.embedding_dim,
    )

    last_error: Exception | None = None
    for attempt in range(1, 8):
        try:
            await store.ensure_collection()
            return store
        except Exception as exc:  # noqa: BLE001 - we degrade on any error
            last_error = exc
            wait = min(2**attempt, 10)
            log.warning(
                "qdrant_init_retry",
                attempt=attempt,
                wait_seconds=wait,
                error=str(exc),
            )
            await asyncio.sleep(wait)

    log.error(
        "qdrant_unavailable",
        error=str(last_error),
        action="search_endpoint_will_return_503",
    )
    await store.aclose()
    return None
