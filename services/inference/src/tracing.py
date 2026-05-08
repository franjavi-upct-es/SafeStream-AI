# services/inference/src/tracing.py
"""OpenTelemetry bootstrap.

All instrumentation lives behind ``settings.otel_enabled`` so the
project boots fine with the OTel libs installed but no collector
running. ``setup_tracing()`` is idempotent: calling it twice does not
register the same instrumentation twice.

The instrumentations we wire up cover the three integration points the
service has with the outside world:

  * **FastAPI** - automatic span per HTTP request, with route template
    used as the span name so dashboards stay aggregable.
  * **aiokafka** - producer / consumer spans with W3C ``traceparent``
    headers attached to each Kafka record. This stitches an inbound
    request to its asynchronous follow-up across the broker.
  * **asyncpg** - a span per query, surfacing slow SQL inside whatever
    parent span the request created.

The actual export is OTLP/gRPC. The optional console exporter is handy
when iterating locally without a collector.
"""

from __future__ import annotations

from app_logging import get_logger
from config import settings
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
    OTLPSpanExporter,
)
from opentelemetry.instrumentation.aiokafka import AIOKafkaInstrumentor
from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
)

log = get_logger(__name__)

_initialised = False


def setup_tracing() -> None:
    """Wire up the OTel SDK and library instrumentations.

    Safe to call multiple times - subsequent calls are no-ops.
    """
    global _initialised
    if _initialised:
        return
    if not settings.otel_enabled:
        log.info("otel_disabled")
        _initialised = True
        return

    resource = Resource.create({SERVICE_NAME: settings.otel_service_name})
    provider = TracerProvider(resource=resource)

    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint=settings.otel_exporter_endpoint,
                insecure=True,
            ),
        )
    )
    if settings.otel_console_export:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)

    # Library instrumentations are global - calling them once is enough
    AIOKafkaInstrumentor().instrument()
    AsyncPGInstrumentor().instrument()

    log.info(
        "otel_initialised",
        endpoint=settings.otel_exporter_endpoint,
        service=settings.otel_service_name,
    )
    _initialised = True


def instrument_app(app) -> None:  # type: ignore[no-untyped-def]
    """Wrap a FastAPI app with tracing middleware."""
    if not settings.otel_enabled:
        return
    FastAPIInstrumentor.instrument_app(
        app, excluded_urls="healthz,readyz,metrics"
    )
