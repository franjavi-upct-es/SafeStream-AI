# services/inference/tests/test_alembic_env.py
"""Test the DSN normalisation used by alembic/env.py.

We don't actually invoke alembic from here (that would need a live DB);
we only verify the URL transformation is correct so the migration uses
the synchronous psycopg2 driver no matter what runtime DSN we feed it.

Loading the helper through ``importlib.util`` because the local
``alembic/`` directory shadows the installed alembic package on the
import path - we want the local one without messing with sys.path.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_HELPER_PATH = Path(__file__).resolve().parent.parent / "alembic" / "dsn.py"


def _load_helper():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(
        "_safestream_alembic_dsn",
        _HELPER_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "input_dsn,expected",
    [
        # asyncpg variant (what the runtime service uses).
        (
            "postgresql+asyncpg://user:pw@host:5432/db",
            "postgresql+psycopg2://user:pw@host:5432/db",
        ),
        # Bare postgres:// scheme (some env tooling normalises to this).
        (
            "postgres://user:pw@host/db",
            "postgresql+psycopg2://user:pw@host/db",
        ),
        # Plain postgresql:// (default in our compose file).
        (
            "postgresql://user:pw@host/db",
            "postgresql+psycopg2://user:pw@host/db",
        ),
        # Already psycopg2 - passthrough.
        (
            "postgresql+psycopg2://user:pw@host/db",
            "postgresql+psycopg2://user:pw@host/db",
        ),
    ],
)
def test_normalise_to_psycopg2(input_dsn: str, expected: str) -> None:
    helper = _load_helper()
    assert helper.normalise_to_psycopg2(input_dsn) == expected


def test_normalise_unknown_scheme_passthrough() -> None:
    helper = _load_helper()
    # Anything we don't recognise is returned verbatim - alembic itself
    # will surface a clearer error than us trying to be clever here.
    assert (
        helper.normalise_to_psycopg2("sqlite:///:memory:")
        == "sqlite:///:memory:"
    )
