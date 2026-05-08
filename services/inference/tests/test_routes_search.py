# services/inference/tests/test_routes_search.py
"""POST /v1/search/semantic route."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

import pytest


class _FakeEmbedder:
    """Returns a deterministic vector based on the query text."""

    def __init__(self) -> None:
        from models.base import ModelInfo

        self.info = ModelInfo(name="fake-embedder")
        self.dim = 4

    async def embed(self, text: str) -> Any:
        from models.embeddings import Embedding

        v = [0.0, 0.0, 0.0, 0.0]
        if "hate" in text.lower():
            v[0] = 1.0
        elif "love" in text.lower():
            v[1] = 1.0
        else:
            v[2] = 1.0
        return Embedding(vector=v, inference_latency_ms=1, model=self.info)


class _FakeVectorStore:
    """Records the search call so tests can assert filter forwarding."""

    collection = "test"
    vector_size = 4

    class _FakeClient:
        async def collection_exists(self, _name: str) -> bool:
            return True

    def __init__(self) -> None:
        self._client = self._FakeClient()
        self.last_search: dict[str, Any] | None = None

    async def search(
        self,
        *,
        vector: Sequence[float],
        limit: int,
        verdicts: Any,
        min_score: float | None,
    ) -> list[Any]:
        from persistence.vector_store import SearchHit

        self.last_search = {
            "vector": list(vector),
            "limit": limit,
            "verdicts": list(verdicts) if verdicts else None,
            "min_score": min_score,
        }
        return [
            SearchHit(
                event_id=UUID("11111111-1111-1111-1111-111111111111"),
                score=0.93,
                payload={
                    "verdict": "block",
                    "modality": "text",
                    "source_id": "src-1",
                    "content_snippet": "i hate you",
                    "predicted_at": "2026-04-26T12:00:00+00:00",
                    "model_name": "unitary/toxic-bert",
                },
            ),
            SearchHit(
                event_id=UUID("22222222-2222-2222-2222-222222222222"),
                score=0.74,
                payload={
                    "verdict": "review",
                    "modality": "text",
                    "content_snippet": "i dislike you",
                },
            ),
        ]


@pytest.mark.asyncio
async def test_semantic_search_503_when_embedder_disabled(app, client) -> None:  # type: ignore[no-untyped-def]
    app.state.models.embedder = None
    app.state.vector_store = _FakeVectorStore()

    response = await client.post("/v1/search/semantic", json={"query": "hi"})

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_semantic_search_503_when_store_unavailable(app, client) -> None:  # type: ignore[no-untyped-def]
    app.state.models.embedder = _FakeEmbedder()
    app.state.vector_store = None

    response = await client.post("/v1/search/semantic", json={"query": "hi"})

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_semantic_search_forwards_filters(app, client) -> None:  # type: ignore[no-untyped-def]
    store = _FakeVectorStore()
    app.state.models.embedder = _FakeEmbedder()
    app.state.vector_store = store

    response = await client.post(
        "/v1/search/semantic",
        json={
            "query": "I hate you so much",
            "limit": 5,
            "verdicts": ["block", "review"],
            "min_score": 0.5,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    assert body["results"][0]["verdict"] == "block"
    # Filters must reach the store unchanged.
    assert store.last_search is not None
    assert store.last_search["limit"] == 5
    assert store.last_search["min_score"] == 0.5
    assert store.last_search["verdicts"] == ["block", "review"]
    # Embedder produced the "hate" vector.
    assert store.last_search["vector"] == [1.0, 0.0, 0.0, 0.0]


@pytest.mark.asyncio
async def test_semantic_search_rejects_empty_query(client) -> None:  # type: ignore[no-untyped-def]
    response = await client.post("/v1/search/semantic", json={"query": ""})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_semantic_search_rejects_unknown_verdict(client) -> None:  # type: ignore[no-untyped-def]
    response = await client.post(
        "/v1/search/semantic",
        json={"query": "hi", "verdicts": ["unknown"]},
    )
    assert response.status_code == 422
