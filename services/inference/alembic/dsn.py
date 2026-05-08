# services/inference/alembic/dsn.py
"""DSN normalisation used by both env.py and the test suite."""

from __future__ import annotations


def normalise_to_psycopg2(dsn: str) -> str:
    """Translate a runtime DSN into the synchronous psycopg2 URL Alembic uses.

    Accepts the three variants we encounter in practice:

      * ``postgresql+asyncpg://...`` - what the service uses at runtime.
      * ``postgres://...`` - emitted by some env tooling.
      * ``postgresql://...`` - the compose default.

    Anything already on ``postgresql+psycopg2://`` is returned unchanged.
    """
    for prefix in ("postgresql+asyncpg://", "postgres://", "postgresql://"):
        if dsn.startswith(prefix):
            return "postgresql+psycopg2://" + dsn.removeprefix(prefix)
    return dsn
