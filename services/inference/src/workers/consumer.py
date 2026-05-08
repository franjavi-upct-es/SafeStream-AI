# services/inference/src/workers/consumer.py
"""Background worker that drives the asynchronous moderation pipeline.

For every message arriving on ``content.text.raw`` (and
``content.image.raw`` when vision is enabled) the worker:

  1. Validates the JSON envelope against ``ContentEvent``.
  2. Runs the appropriate classifier.
  3. Persists the event + prediction in Postgres (single transaction).
  4. Re-emits a compact result record on ``predictions.results`` for any
     downstream consumer (the WebSocket gateway in Phase 4 will subscribe
     here).

A bounded set of inference tasks is processed concurrently so a slow model
call does not stall consumption of the whole partition.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, ConsumerRecord
from aiokafka.errors import KafkaConnectionError
from app_logging import get_logger
from config import settings
from domain.events import ContentEvent
from domain.verdict import Verdict, derive_verdict
from models.base import Prediction
from models.embeddings import TextEmbedder
from models.registry import ModelRegistry
from persistence.repository import ModerationRepository
from persistence.vector_store import VectorStore
from pydantic import ValidationError

log = get_logger(__name__)

# Maximum length of the content snippet attached to each Qdrant point.
# Keeps payloads small while still making search results readable.
_SNIPPET_LIMIT = 240


class InferenceWorker:
    def __init__(
        self,
        *,
        registry: ModelRegistry,
        repository: ModerationRepository,
        vector_store: VectorStore | None = None,
    ) -> None:
        self._registry = registry
        self._repository = repository
        self._vector_store = vector_store
        self._index_verdicts: frozenset[str] = frozenset(
            settings.index_verdicts
        )
        self._consumer: AIOKafkaConsumer | None = None
        self._producer: AIOKafkaProducer | None = None
        self._semaphore = asyncio.Semaphore(settings.worker_concurrency)
        self._stop = asyncio.Event()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def start(self) -> None:
        topics = [settings.kafka_topic_text_in]
        if settings.enable_vision:
            topics.append(settings.kafka_topic_image_in)

        self._consumer = AIOKafkaConsumer(
            *topics,
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id=settings.kafka_consumer_group,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            value_deserializer=lambda v: v,  # we handle JSON ourselves
        )
        # The same producer publishes results and DLQ records. Both topics
        # are partitioned by event id so retries land on the same partition.
        self._producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            client_id=f"{settings.kafka_consumer_group}-results",
            acks=1,
            linger_ms=5,
        )

        await self._connect_with_retry()
        log.info(
            "worker_started",
            topics=topics,
            group=settings.kafka_consumer_group,
            concurrency=settings.worker_concurrency,
            max_retries=settings.worker_max_retries,
            dlq_topic=settings.kafka_topic_dlq,
        )

    async def stop(self) -> None:
        self._stop.set()
        if self._consumer is not None:
            await self._consumer.stop()
        if self._producer is not None:
            await self._producer.stop()
        log.info("worker_stopped")

    async def _connect_with_retry(self) -> None:
        last_error: Exception | None = None
        for attempt in range(1, 11):
            try:
                await self._consumer.start()  # type: ignore[union-attr]
                await self._producer.start()  # type: ignore[union-attr]
                return
            except KafkaConnectionError as exc:
                last_error = exc
                wait = min(2**attempt, 15)
                log.warning(
                    "worker_kafka_retry",
                    attempt=attempt,
                    wait_seconds=wait,
                    error=str(exc),
                )
                await asyncio.sleep(wait)
        raise RuntimeError(f"Worker could not connect to Kafka: {last_error}")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    async def run(self) -> None:
        assert self._consumer is not None, "Call start() first."
        try:
            async for record in self._consumer:
                if self._stop.is_set():
                    break
                # Spawn a bounded task so slow inference doesn't block polling.
                await self._semaphore.acquire()
                task = asyncio.create_task(self._process(record))
                task.add_done_callback(lambda _: self._semaphore.release())
        except asyncio.CancelledError:
            log.info("worker_cancelled")
            raise
        except Exception:
            log.exception("worker_loop_crashed")
            raise

    # ------------------------------------------------------------------
    # Per-message handler
    # ------------------------------------------------------------------
    async def _process(self, record: ConsumerRecord) -> None:
        attempts = self._attempt_count(record) + 1
        try:
            event = self._parse(record)
        except ValidationError as exc:
            # Permanent failure: a malformed payload will never improve on
            # retry. Park it on the DLQ and commit so the partition unblocks.
            log.warning(
                "event_invalid",
                topic=record.topic,
                offset=record.offset,
                error=exc.errors(),
            )
            await self._send_to_dlq(
                record, reason="validation_error", attempts=attempts
            )
            await self._commit(record)
            return

        try:
            prediction = await self._infer(event)
        except NotImplementedError as exc:
            # Modality / configuration mismatch - won't be fixed by a retry.
            log.warning(
                "event_unhandled",
                event_id=str(event.event_id),
                reason=str(exc),
            )
            await self._send_to_dlq(
                record, reason=f"unhandled: {exc}", attempts=attempts
            )
            await self._commit(record)
            return
        except Exception:
            # Transient failure (model OOM, network glitch, etc). Bump the
            # attempt counter; if we've blown the budget, send to DLQ.
            log.exception(
                "inference_failed",
                event_id=str(event.event_id),
                topic=record.topic,
                offset=record.offset,
                attempts=attempts,
            )
            if attempts >= settings.worker_max_retries:
                await self._send_to_dlq(
                    record,
                    reason="inference_max_retries_exceeded",
                    attempts=attempts,
                )
                await self._commit(record)
            # else: don't commit. Kafka will redeliver after the consumer
            # rebalances or the broker times out the in-flight offset.
            return

        verdict = derive_verdict(prediction.scores)

        try:
            event_id = await self._repository.record_event_with_prediction(
                event=event,
                prediction=prediction,
                verdict=verdict,
            )
        except Exception:
            log.exception("persist_failed", event_id=str(event.event_id))
            return

        await self._publish_result(
            event_id=event_id,
            event=event,
            prediction=prediction,
            verdict=verdict,
        )
        await self._commit(record)

        # Indexing is best-effort: a failure here must not stop the pipeline.
        # The Kafka offset has already been committed; the SQL row is the
        # source of truth and a periodic backfill job can re-index later.
        await self._maybe_index(
            event_id=event_id,
            event=event,
            prediction=prediction,
            verdict=verdict,
        )

        log.info(
            "event_processed",
            event_id=str(event_id),
            modality=event.modality,
            verdict=verdict,
            latency_ms=prediction.inference_latency_ms,
        )

    def _parse(self, record: ConsumerRecord) -> ContentEvent:
        return ContentEvent.model_validate_json(record.value)

    async def _infer(self, event: ContentEvent) -> Prediction:
        if event.modality == "text":
            if self._registry.text is None:
                raise NotImplementedError("Text model not loaded")
            if not event.content:
                raise NotImplementedError("Text event without content")
            return await self._registry.text.classify(event.content)

        if event.modality == "image":
            if self._registry.vision is None:
                raise NotImplementedError("Vision model not loaded")
            if not event.content_uri:
                raise NotImplementedError(
                    "Image events must carry content_uri (Phase 2 supports "
                    "URI-based payloads only)"
                )
            # Phase 2 ships URI-only image events; the URI fetcher lands in
            # the same patch as the image producer (currently unimplemented).
            raise NotImplementedError(
                "Image fetch from URI is not implemented yet; use the REST "
                "endpoint for image classification in Phase 2."
            )

        raise NotImplementedError(f"Unknown modality: {event.modality!r}")

    async def _publish_result(
        self,
        *,
        event_id: UUID,
        event: ContentEvent,
        prediction: Prediction,
        verdict: Verdict,
    ) -> None:
        assert self._producer is not None
        message: dict[str, Any] = {
            "event_id": str(event_id),
            "source_id": event.source_id,
            "modality": event.modality,
            "verdict": verdict,
            "scores": prediction.scores,
            "model": {
                "name": prediction.model.name,
                "version": prediction.model.version,
            },
            "inference_latency_ms": prediction.inference_latency_ms,
            "predicted_at": datetime.now(UTC).isoformat(),
        }
        await self._producer.send_and_wait(
            settings.kafka_topic_predictions_out,
            key=str(event_id).encode("utf-8"),
            value=json.dumps(message).encode("utf-8"),
        )

    async def _commit(self, record: ConsumerRecord) -> None:
        assert self._consumer is not None
        # aiokafka commits asynchronously; this awaits the borker ack.
        await self._consumer.commit()

    # ------------------------------------------------------------------
    # Dead-letter handling
    # ------------------------------------------------------------------
    _RETRY_HEADER = "x-safestream-attempts"
    _REASON_HEADER = "x-safestream-dlq-reason"
    _ORIGIN_HEADER = "x-safestream-origin-topic"

    def _attempt_count(self, record: ConsumerRecord) -> int:
        """Read the retry counter set by previous failed attempts."""
        if not record.headers:
            return 0
        for key, raw in record.headers:
            if key == self._RETRY_HEADER:
                try:
                    return int(raw.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    return 0
        return 0

    async def _send_to_dlq(
        self,
        record: ConsumerRecord,
        *,
        reason: str,
        attempts: int,
    ) -> None:
        """Forward a failing record to the dead-letter topic.

        The DLQ payload is the original record value verbatim so an
        operator can replay it once the underlying problem is fixed.
        """
        assert self._producer is not None
        headers = [
            (self._RETRY_HEADER, str(attempts).encode("utf-8")),
            (self._REASON_HEADER, reason.encode("utf-8")[:512]),
            (self._ORIGIN_HEADER, record.topic.encode("utf-8")),
        ]
        try:
            await self._producer.send_and_wait(
                settings.kafka_topic_dlq,
                value=record.value,
                key=record.key,
                headers=headers,
            )
            log.warning(
                "event_dead_lettered",
                origin_topic=record.topic,
                offset=record.offset,
                reason=reason,
                attempts=attempts,
            )
        except Exception:
            # If the DLQ itself is broken we cannot do much beyond logging
            # — better to keep the partition unblocked than to spin forever.
            log.exception("dlq_publish_failed", reason=reason)

    # ------------------------------------------------------------------
    # Best-effort vector indexing
    # ------------------------------------------------------------------
    async def _maybe_index(
        self,
        *,
        event_id: UUID,
        event: ContentEvent,
        prediction: Prediction,
        verdict: Verdict,
    ) -> None:
        """Embed the event content and upsert into Qdrant when warranted.

        Skipped silently when:
          * the embedder or vector store is not configured,
          * the verdict is not in INDEX_VERDICTS,
          * the event has no embeddable text yet (image events without OCR).

        Failures are logged and swallowed.
        """

        if self._vector_store is None:
            return
        embedder: TextEmbedder | None = self._registry.embedder
        if embedder is None:
            return
        if verdict not in self._index_verdicts:
            return
        # Phase 3 only embeds text. Image events become searchable in a
        # later phase that adds CLIP-style joint embeddings.
        if event.modality != "text" or not event.content:
            return

        try:
            embedding = await embedder.embed(event.content)
        except Exception:
            log.exception("embed_failed", event_id=str(event_id))
            return

        snippet = event.content[:_SNIPPET_LIMIT]
        if len(event.content) > _SNIPPET_LIMIT:
            snippet += "..."

        payload = {
            "event_id": str(event_id),
            "source_id": event.source_id,
            "modality": event.modality,
            "verdict": verdict,
            "scores": prediction.scores,
            "top_scores": (
                max(prediction.scores.values()) if prediction.scores else 0.0
            ),
            "model_name": prediction.model.name,
            "model_version": prediction.model.version,
            "content_snippet": snippet,
            "predicted_at": datetime.now(UTC).isoformat(),
        }

        try:
            await self._vector_store.index(
                event_id=event_id,
                vector=embedding.vector,
                payload=payload,
            )
            log.info(
                "event_indexed",
                event_id=str(event_id),
                verdict=verdict,
                embed_latency_ms=embedding.inference_latency_ms,
            )
        except Exception:
            log.exception("index_failed", event_id=str(event_id))
