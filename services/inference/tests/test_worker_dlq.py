# services/inference/tests/test_worker_dlq.py
"""Behaviour around malformed payloads, retry budgets, and the DLQ.

These exercise the worker's ``_process`` decision tree directly; we don't
spin up a broker. The aiokafka producer is mocked so we can assert what
got published where.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from config import settings


class _Record:
    """ConsumerRecord stand-in. Only fields the worker reads."""

    def __init__(
        self,
        *,
        value: bytes,
        topic: str = "content.text.raw",
        key: bytes | None = None,
        headers: list[tuple[str, bytes]] | None = None,
        offset: int = 0,
    ) -> None:
        self.value = value
        self.topic = topic
        self.key = key
        self.headers = headers or []
        self.offset = offset


class _FakeRegistry:
    """Configurable registry that lets us inject inference behaviour."""

    text: Any = None
    vision = None
    embedder = None


def _make_text_classifier(*, raises: Exception | None = None):  # type: ignore[no-untyped-def]
    from models.base import ModelInfo, Prediction

    class _Classifier:
        info = ModelInfo(name="m")

        async def classify(self, _text: str):  # type: ignore[no-untyped-def]
            if raises is not None:
                raise raises
            return Prediction(
                scores={"toxic": 0.05},
                inference_latency_ms=1,
                model=self.info,
            )

    return _Classifier()


def _build_worker(text_classifier=None):  # type: ignore[no-untyped-def]
    from workers.consumer import InferenceWorker

    registry = _FakeRegistry()
    if text_classifier is not None:
        registry.text = text_classifier

    class _Repo:
        record_event_with_prediction = AsyncMock(return_value=uuid4())

    worker = InferenceWorker(
        registry=registry,  # type: ignore[arg-type]
        repository=_Repo(),  # type: ignore[arg-type]
        vector_store=None,
    )
    # Mock the producer + consumer so we can assert without a broker.
    worker._producer = AsyncMock()  # noqa: SLF001
    worker._consumer = AsyncMock()  # noqa: SLF001
    return worker


@pytest.mark.asyncio
async def test_malformed_payload_goes_to_dlq_and_commits() -> None:
    worker = _build_worker()
    record = _Record(value=b"not-json")

    await worker._process(record)  # noqa: SLF001

    # Sent to the DLQ once.
    worker._producer.send_and_wait.assert_awaited_once()  # noqa: SLF001
    args, kwargs = worker._producer.send_and_wait.await_args  # noqa: SLF001
    assert args[0] == settings.kafka_topic_dlq
    assert kwargs["value"] == b"not-json"
    # Headers carry the failure reason and attempt count.
    headers = dict(kwargs["headers"])
    assert headers["x-safestream-attempts"] == b"1"
    assert headers["x-safestream-dlq-reason"].startswith(b"validation_error")
    # Offset committed - partition stays unblocked.
    worker._consumer.commit.assert_awaited()  # noqa: SLF001


@pytest.mark.asyncio
async def test_unhandled_modality_goes_to_dlq() -> None:
    """Image events without a vision model get parked, not retried forever."""
    worker = _build_worker()  # text disabled, vision disabled
    payload = json.dumps(
        {
            "event_id": str(uuid4()),
            "modality": "image",
            "content_uri": "upload://x.png",
        }
    ).encode("utf-8")

    await worker._process(_Record(value=payload))  # noqa: SLF001

    worker._producer.send_and_wait.assert_awaited_once()  # noqa: SLF001
    _args, kwargs = worker._producer.send_and_wait.await_args  # noqa: SLF001
    headers = dict(kwargs["headers"])
    assert headers["x-safestream-dlq-reason"].startswith(b"unhandled")
    worker._consumer.commit.assert_awaited()  # noqa: SLF001


@pytest.mark.asyncio
async def test_transient_failure_under_budget_does_not_commit() -> None:
    """Inference failures within the retry budget leave the offset uncommitted."""
    bad_classifier = _make_text_classifier(raises=RuntimeError("OOM"))
    worker = _build_worker(text_classifier=bad_classifier)
    payload = json.dumps(
        {"event_id": str(uuid4()), "modality": "text", "content": "hi"}
    ).encode("utf-8")

    await worker._process(_Record(value=payload))  # noqa: SLF001

    # Neither DLQ nor commit at attempt 1 (default budget = 3).
    worker._producer.send_and_wait.assert_not_awaited()  # noqa: SLF001
    worker._consumer.commit.assert_not_awaited()  # noqa: SLF001


@pytest.mark.asyncio
async def test_transient_failure_over_budget_goes_to_dlq() -> None:
    """When ``attempts`` reaches the budget the record is parked."""
    bad_classifier = _make_text_classifier(raises=RuntimeError("OOM"))
    worker = _build_worker(text_classifier=bad_classifier)
    payload = json.dumps(
        {"event_id": str(uuid4()), "modality": "text", "content": "hi"}
    ).encode("utf-8")
    # Pretend the broker has redelivered this record twice already.
    headers = [("x-safestream-attempts", b"2")]
    record = _Record(value=payload, headers=headers)

    await worker._process(record)  # noqa: SLF001

    # Attempt 3 == default budget -> DLQ + commit.
    worker._producer.send_and_wait.assert_awaited_once()  # noqa: SLF001
    _args, kwargs = worker._producer.send_and_wait.await_args  # noqa: SLF001
    out_headers = dict(kwargs["headers"])
    assert out_headers["x-safestream-attempts"] == b"3"
    assert (
        out_headers["x-safestream-dlq-reason"]
        == b"inference_max_retries_exceeded"
    )
    worker._consumer.commit.assert_awaited()  # noqa: SLF001


@pytest.mark.asyncio
async def test_attempt_count_handles_missing_and_garbage_headers() -> None:
    worker = _build_worker()

    # Missing headers -> 0
    assert worker._attempt_count(_Record(value=b"x")) == 0  # noqa: SLF001

    # Non-numeric value -> 0 (treated as fresh)
    bad = _Record(value=b"x", headers=[("x-safestream-attempts", b"oops")])
    assert worker._attempt_count(bad) == 0  # noqa: SLF001

    # Numeric -> parsed
    good = _Record(value=b"x", headers=[("x-safestream-attempts", b"5")])
    assert worker._attempt_count(good) == 5  # noqa: SLF001
