# services/inference/tests/test_routes_prometheus.py
"""Verify the Prometheus instrumentation is wired and exposing samples."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_metrics_endpoint_exposed_and_returns_text(client) -> None:  # type: ignore[no-untyped-def]
    """The Instrumentator default mounts /metrics with text/plain output.

    We hit a known endpoint first so the histogram has at least one
    sample, then scrape /metrics and assert the HTTP metrics and our
    custom in-flight gauge are present.
    """
    # Generate one request worth of samples.
    pre = await client.get("/healthz")
    assert pre.status_code == 200

    response = await client.get("/metrics")

    assert response.status_code == 200
    # Content-Type follows the OpenMetrics convention.
    assert response.headers["content-type"].startswith("text/plain")

    body = response.text
    # The in-flight gauge is registered but only EMITS samples while a
    # request is in flight. Asserting on its HELP line is enough to
    # prove the instrumentator wired our custom name through.
    assert "# HELP safestream_inflight_requests" in body
    # Request totals counter, populated by our healthz hit above.
    assert "http_requests_total" in body
    # Request duration histogram registered by the instrumentator.
    assert "http_request_duration_seconds" in body


@pytest.mark.asyncio
async def test_metrics_endpoint_excludes_itself(client) -> None:  # type: ignore[no-untyped-def]
    """``excluded_handlers`` should keep /metrics from measuring itself."""
    # Scrape twice to seed any potential samples.
    await client.get("/metrics")
    response = await client.get("/metrics")
    body = response.text
    # The handler label for our excluded paths must not appear.
    assert 'handler="/metrics"' not in body
    assert 'handler="/healthz"' not in body
