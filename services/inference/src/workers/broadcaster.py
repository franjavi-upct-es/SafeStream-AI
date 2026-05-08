# services/inference/src/workers/broadcaster.py
"""Bridges Kafka -> WebSocket.

A separate consumer (its own group, ``BROADCASTER_CONSUMER_GROUP``) reads
from ``predictions.results`` and forwards every record verbatim to every
connected dashboard client through a ``ConnectionManager``.

Running this as its own consumer group means:
  * The broadcaster does not affect the moderation worker's offsets.
  * Restarting the API server does not replay the moderation pipeline.
  * Multiple replicas can eventually share the broadcaster load (each
    partition still goes to one replica per group).
"""

import asyncio
from app_logging import get_logger

from aiokafka import AIOKafkaConsumer
from aiokafka.errors import KafkaConnectionError
from config import settings
from workers.connection_manager import ConnectionManager

log = get_logger(__name__)


class PredictionBroadcaster:
    """Consume from Kafka, broadcast to WS clients."""

    def __init__(self, manager: ConnectionManager) -> None:
        self._manager = manager
        self._consumer: AIOKafkaConsumer | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        self._consumer = AIOKafkaConsumer(
            settings.kafka_topic_predictions_out,
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id=settings.broadcaster_consumer_group,
            enable_auto_commit=True,
            auto_commit_interval_ms=2000,
            auto_offset_reset="latest",  # only forward live traffic
            value_deserializer=lambda v: v,
        )
        await self._connect_with_retry()
        log.info(
            "broadcaster_started",
            topic=settings.kafka_topic_predictions_out,
            group=settings.broadcaster_consumer_group,
        )

    async def stop(self) -> None:
        self._stop.set()
        if self._consumer is not None:
            await self._consumer.stop()
        log.info("broadcaster_stopped")

    async def _connect_with_retry(self) -> None:
        last_error: Exception | None = None
        for attempt in range(1, 11):
            try:
                await self._consumer.start()  # type: ignore[union-attr]
                return
            except KafkaConnectionError as exc:
                last_error = exc
                wait = min(2**attempt, 15)
                log.warning(
                    "broadcaster_kafka_retry",
                    attempt=attempt,
                    wait_seconds=wait,
                    error=str(exc),
                )
                await asyncio.sleep(wait)
        raise RuntimeError(
            f"Broadcaster could not connect to Kafka: {last_error}"
        )

    async def run(self) -> None:
        assert self._consumer is not None, "Call start() first."
        try:
            async for record in self._consumer:
                if self._stop.is_set():
                    break
                # Skip the broadcast cost when no one is listening.
                if self._manager.size == 0:
                    continue
                try:
                    text = record.value.decode("utf-8")
                except UnicodeDecodeError:
                    log.warning("broadcaster_skipped_non_utf8")
                    continue
                await self._manager.broadcast(text)
        except asyncio.CancelledError:
            log.info("broadcaster_cancelled")
            raise
        except Exception:
            log.exception("broadcaster_loop_crashed")
            raise
