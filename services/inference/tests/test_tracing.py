# services/inference/tests/test_tracing.py
"""``setup_tracing`` behaviour: opt-in flag, idempotency, instrumentation."""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def fresh_tracing_module():
    """Reload tracing so the module-level ``_initialised`` flag resets."""
    import tracing

    importlib.reload(tracing)
    yield tracing
    # Best-effort teardown: leave tracing off for subsequent tests.
    import tracing

    importlib.reload(tracing)


def test_setup_tracing_noop_when_disabled(fresh_tracing_module) -> None:  # type: ignore[no-untyped-def]
    """With ``otel_enabled=False`` the call must short-circuit cleanly."""
    from config import settings

    settings.otel_enabled = False
    fresh_tracing_module.setup_tracing()  # must not raise
    assert fresh_tracing_module._initialised is True  # noqa: SLF001


def test_setup_tracing_is_idempotent(fresh_tracing_module) -> None:  # type: ignore[no-untyped-def]
    from config import settings

    settings.otel_enabled = False
    fresh_tracing_module.setup_tracing()
    # Second call must not raise even if the providers were already wired.
    fresh_tracing_module.setup_tracing()


def test_instrument_app_noop_when_disabled() -> None:
    """``instrument_app`` is a safe no-op when tracing is off."""
    from config import settings
    from fastapi import FastAPI
    from tracing import instrument_app

    settings.otel_enabled = False
    app = FastAPI()
    instrument_app(app)  # must not raise
