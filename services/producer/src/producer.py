# services/producer/src/producer.py
"""Asynchronous Kafka producer that simulates the UGC firehose.

Reads rows from a Jigsaw-shaped CSV at ``DATASET_PATH`` and publishes one
``ContentEvent`` per row onto Kafka, paced at ``EVENTS_PER_SECOND`` events
per second. Designed to behave well under SIGTERM (Docker stop) by flushing
in-flight messages before exiting.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from typing import NoReturn

import structlog
from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaConnectionError
from config import settings
from dataset import iter_events
from schema import ContentEvent


def _configure_logging() -> structlog.stdlib.BoundLogger:
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=settings.log_level.upper(),
    )
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level.upper(), logging.INFO),
        ),
    )
    return structlog.get_logger("producer")


log = _configure_logging()


def _serialize(event: ContentEvent) -> bytes:
    return event.model_dump_json().encode("utf-8")


async def _build_producer() -> AIOKafkaProducer:
    producer = AIOKafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        client_id=settings.kafka_client_id,
        # Modest acks setting: 1 keeps latency low for a dev environment.
        # Tighten to "all" once we move to a multi-broker production cluster.
        acks=1,
        enable_idempotence=False,
        linger_ms=5,
    )
    # Retry the initial connection - Kafka may still be electing a leader
    # the very first time the stack comes up.
    last_error: Exception | None = None
    for attempt in range(1, 11):
        try:
            await producer.start()
            return producer
        except (
            KafkaConnectionError
        ) as exc:  # pragma: no cover - timing dependent
            last_error = exc
            wait = min(2**attempt, 15)
            log.warning(
                "kafka_connection_retry",
                attempt=attempt,
                wait_seconds=wait,
                error=str(exc),
            )
            await asyncio.sleep(wait)
    raise RuntimeError(
        f"Could not connect to Kafka at {settings.kafka_bootstrap_servers}: {last_error}"
    )


async def run() -> None:
    log.info(
        "producer_starting",
        bootstrap=settings.kafka_bootstrap_servers,
        topic=settings.kafka_topic_text,
        dataset=str(settings.dataset_path),
        rate=settings.events_per_second,
        loop=settings.loop_dataset,
    )

    producer = await _build_producer()
    interval = 1.0 / settings.events_per_second
    stop = asyncio.Event()

    def _request_stop(signum: int) -> None:
        log.info("signal_received", signum=signum)
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _request_stop, sig)

    sent = 0
    try:
        for event in iter_events(
            settings.dataset_path, loop=settings.loop_dataset
        ):
            if stop.is_set():
                break

            payload = _serialize(event)
            key = (event.source_id or str(event.event_id)).encode("utf-8")

            await producer.send_and_wait(
                settings.kafka_topic_text,
                value=payload,
                key=key,
            )
            sent += 1

            if sent % 100 == 0:
                log.info("events_emitted", count=sent)

            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
                # If wait_for did not raise, stop was set: leave the loop.
                break
            except TimeoutError:
                pass  # normal pacing path
    finally:
        log.info("producer_stopping", total_sent=sent)
        await producer.stop()


def main() -> NoReturn:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:  # interactive use
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
