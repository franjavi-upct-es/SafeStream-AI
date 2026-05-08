# services/inference/src/api/routes_stream.py
"""WebSocket endpoint that pushes live prediction events to the dashboard.

The handler does almost no work itself - it registers the socket with the
``ConnectionManager`` and waits. The actual data flow is driven by the
broadcaster task running in the background, which reads from Kafka and
calls ``manager.broadcast`` for every prediction.

Auth is opt-in: when ``API_KEYS`` is non-empty, the client must pass
``?api_key=...`` in the URL (browsers cannot set custom headers on the
WebSocket handshake without proxies, hence the query string).
"""

# NOTE: see routes_classify - keep `from __future__ import annotations` OFF.

import secrets

from config import settings
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

router = APIRouter(tags=["stream"])


def _api_key_ok(key: str | None) -> bool:
    if not settings.api_keys:
        return True  # auth disabled
    if key is None:
        return False
    return any(secrets.compare_digest(key, k) for k in settings.api_keys)


@router.websocket("/v1/stream")
async def stream(
    websocket: WebSocket,
    api_key: str | None = Query(default=None),
) -> None:
    if not _api_key_ok(api_key):
        # Reject before accepting so the browser sees a 4401-style close.
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    manager = websocket.app.state.ws_manager
    await websocket.accept()
    await manager.add(websocket)

    try:
        # The protocol is server-push only. We loop on receive_text purely so
        # this coroutine stays alive until the client disconnects (and so we
        # honour any pings the client decides to send).
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await manager.remove(websocket)
