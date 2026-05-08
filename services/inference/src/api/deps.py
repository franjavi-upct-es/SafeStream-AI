# services/inference/src/api/deps.py
"""Cross-cutting FastAPI dependencies: API-key auth and rate limiting.

Auth is opt-in: an empty ``API_KEYS`` settings disables it (handy for focal
development). The rate limiter is always on; the budget is the ``RATE_LIMIT``
setting, e.g. ``100/minute``.
"""

from __future__ import annotations

import secrets
from typing import Annotated

from config import settings
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader
from slowapi import Limiter
from slowapi.util import get_remote_address

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def _peer_or_key(request: Request) -> str:
    """Rate-limit by API key when present, fall back to peer IP."""
    key = request.headers.get("X-API-Key")
    if key:
        return f"key:{key}"
    return f"ip:{get_remote_address(request)}"


limiter = Limiter(key_func=_peer_or_key, default_limits=[settings.rate_limit])


async def require_api_key(
    api_key: Annotated[str | None, Depends(_API_KEY_HEADER)],
) -> None:
    """Validate ``X-API-Key`` against the configured allow-list."""

    if not settings.api_keys:
        # Auth disabled; let everyone through.
        return

    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    # Constant-time compare against every allowed key.
    if not any(secrets.compare_digest(api_key, k) for k in settings.api_keys):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
        )
