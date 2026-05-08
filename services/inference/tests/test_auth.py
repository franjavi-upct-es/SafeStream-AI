# services/inference/tests/test_auth.py
"""API-key dependency behaviour."""

from __future__ import annotations

import pytest
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_auth_disabled_when_keys_empty() -> None:
    from api.deps import require_api_key
    from config import settings

    settings.api_keys = []
    # Must not raise.
    await require_api_key(api_key=None)
    await require_api_key(api_key="anything")


@pytest.mark.asyncio
async def test_auth_rejects_missing_key() -> None:
    from api.deps import require_api_key
    from config import settings

    settings.api_keys = ["secret"]
    with pytest.raises(HTTPException) as info:
        await require_api_key(api_key=None)
    assert info.value.status_code == 401


@pytest.mark.asyncio
async def test_auth_rejects_wrong_key() -> None:
    from api.deps import require_api_key
    from config import settings

    settings.api_keys = ["secret"]
    with pytest.raises(HTTPException) as info:
        await require_api_key(api_key="wrong")
    assert info.value.status_code == 401


@pytest.mark.asyncio
async def test_auth_accepts_valid_key() -> None:
    from api.deps import require_api_key
    from config import settings

    settings.api_keys = ["a", "b", "secret"]
    # Any key in the allow-list works.
    await require_api_key(api_key="secret")
    await require_api_key(api_key="a")
