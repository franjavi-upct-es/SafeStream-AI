# services/inference/tests/test_worker_indexing.py
"""Tests for the worker's best-effort vector indexing logic.

These cover the decision tree in ``InferenceWorker._maybe_index`` without
needing a live Kafka consumer.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest


class _FakeEmbedder:
    def __init__(self) -> None:
        from models.base import ModelInfo

        self.info = ModelInfo(name="fake")

    async def embed(self, text: str) -> Any:
        from models.embeddings import Embedding

        return Embedding(
            vector=[0.1] * 4, inference_latency_ms=1, model=self.info
        )


class _FakeRegistry:
    def __init__(self) -> None:
        self.embedder = _FakeEmbedder()


class _RecordingStore:
    def __init__(self) -> None:
        self.upserts: list[dict[str, Any]] = []

    async def index(self, *, event_id, vector, payload):  # type: ignore[no-untyped-def]
        self.upserts.append(
            {
                "id": event_id,
                "verdict": payload["verdict"],
                "snippet": payload["content_snippet"],
            }
        )


class _BombStore:
    async def index(self, **kwargs: Any) -> None:
        raise RuntimeError("qdrant down")


@pytest.fixture
def fake_repo():  # type: ignore[no-untyped-def]
    class _Repo:
        pass

    return _Repo()


@pytest.fixture
def make_prediction():  # type: ignore[no-untyped-def]
    def _build(scores: dict[str, float]):
        from models.base import ModelInfo, Prediction

        return Prediction(
            scores=scores,
            inference_latency_ms=10,
            model=ModelInfo(name="m"),
        )

    return _build


@pytest.mark.asyncio
async def test_block_verdict_indexed(fake_repo, make_prediction) -> None:  # type: ignore[no-untyped-def]
    from domain.events import ContentEvent
    from workers.consumer import InferenceWorker

    store = _RecordingStore()
    worker = InferenceWorker(
        registry=_FakeRegistry(),  # type: ignore[arg-type]
        repository=fake_repo,
        vector_store=store,  # type: ignore[arg-type]
    )
    event = ContentEvent(content="I hate you")

    await worker._maybe_index(  # noqa: SLF001
        event_id=event.event_id,
        event=event,
        prediction=make_prediction({"toxic": 0.95}),
        verdict="block",
    )

    assert len(store.upserts) == 1
    assert store.upserts[0]["verdict"] == "block"


@pytest.mark.asyncio
async def test_safe_verdict_skipped(fake_repo, make_prediction) -> None:  # type: ignore[no-untyped-def]
    from domain.events import ContentEvent
    from workers.consumer import InferenceWorker

    store = _RecordingStore()
    worker = InferenceWorker(
        registry=_FakeRegistry(),  # type: ignore[arg-type]
        repository=fake_repo,
        vector_store=store,  # type: ignore[arg-type]
    )
    event = ContentEvent(content="have a nice day")

    await worker._maybe_index(  # noqa: SLF001
        event_id=event.event_id,
        event=event,
        prediction=make_prediction({"toxic": 0.05}),
        verdict="safe",
    )

    assert store.upserts == []


@pytest.mark.asyncio
async def test_image_modality_skipped_in_phase3(
    fake_repo, make_prediction
) -> None:  # type: ignore[no-untyped-def]
    from domain.events import ContentEvent
    from workers.consumer import InferenceWorker

    store = _RecordingStore()
    worker = InferenceWorker(
        registry=_FakeRegistry(),  # type: ignore[arg-type]
        repository=fake_repo,
        vector_store=store,  # type: ignore[arg-type]
    )
    event = ContentEvent(modality="image", content_uri="upload://x.png")

    await worker._maybe_index(  # noqa: SLF001
        event_id=event.event_id,
        event=event,
        prediction=make_prediction({"toxic": 0.95}),
        verdict="block",
    )

    assert store.upserts == []


@pytest.mark.asyncio
async def test_long_content_truncated_in_snippet(
    fake_repo, make_prediction
) -> None:  # type: ignore[no-untyped-def]
    from domain.events import ContentEvent
    from workers.consumer import InferenceWorker

    store = _RecordingStore()
    worker = InferenceWorker(
        registry=_FakeRegistry(),  # type: ignore[arg-type]
        repository=fake_repo,
        vector_store=store,  # type: ignore[arg-type]
    )
    event = ContentEvent(content="X" * 500)

    await worker._maybe_index(  # noqa: SLF001
        event_id=event.event_id,
        event=event,
        prediction=make_prediction({"toxic": 0.9}),
        verdict="block",
    )

    snippet = store.upserts[0]["snippet"]
    assert snippet.endswith("...")
    assert len(snippet) <= 250


@pytest.mark.asyncio
async def test_index_errors_are_swallowed(fake_repo, make_prediction) -> None:  # type: ignore[no-untyped-def]
    """Vector store failures must never propagate up the moderation path."""
    from domain.events import ContentEvent
    from workers.consumer import InferenceWorker

    worker = InferenceWorker(
        registry=_FakeRegistry(),  # type: ignore[arg-type]
        repository=fake_repo,
        vector_store=_BombStore(),  # type: ignore[arg-type]
    )

    # Must not raise.
    await worker._maybe_index(  # noqa: SLF001
        event_id=uuid4(),
        event=ContentEvent(content="x"),
        prediction=make_prediction({"toxic": 0.9}),
        verdict="block",
    )


@pytest.mark.asyncio
async def test_no_vector_store_is_noop(fake_repo, make_prediction) -> None:  # type: ignore[no-untyped-def]
    from domain.events import ContentEvent
    from workers.consumer import InferenceWorker

    worker = InferenceWorker(
        registry=_FakeRegistry(),  # type: ignore[arg-type]
        repository=fake_repo,
        vector_store=None,
    )

    # Must not raise.
    await worker._maybe_index(  # noqa: SLF001
        event_id=uuid4(),
        event=ContentEvent(content="x"),
        prediction=make_prediction({"toxic": 0.9}),
        verdict="block",
    )
