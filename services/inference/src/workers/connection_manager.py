# services/inference/src/workers/connection_manager.py
"""Tracks active WebSocket clients and fans out broadcasts.

Designed to be small and obvious. Concurrent ``broadcast`` calls are safe;
a slow / dead client never blocks the others - we time out and prune it.
"""

import asyncio
from app_logging import get_logger

from fastapi import WebSocket

log = get_logger(__name__)


class ConnectionManager:
    """In-memory registry of open WebSocket connections."""

    def __init__(self, *, send_timeout: float = 2.0) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self._send_timeout = send_timeout

    async def add(self, ws: WebSocket) -> None:
        async with self._lock:
            self._connections.add(ws)
        log.info("ws_client_connected", total=len(self._connections))

    async def remove(self, ws: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(ws)
        log.info("ws_client_disconnected", total=len(self._connections))

    @property
    def size(self) -> int:
        return len(self._connections)

    async def broadcast(self, message: str) -> None:
        """Send ``message`` to every connected client.

        We snapshot the set under the lock, then send outside it so a slow
        client cannot stall connections / disconnections happening in
        parallel.
        """
        async with self._lock:
            targets = list(self._connections)
        if not targets:
            return

        dead: list[WebSocket] = []

        # Concurrent fan-out with per-client timeout.
        async def _send(ws: WebSocket) -> None:
            try:
                await asyncio.wait_for(
                    ws.send_text(message),
                    timeout=self._send_timeout,
                )
            except Exception:  # noqa: BLE001 - network failures are normal here
                dead.append(ws)

        await asyncio.gather(*(_send(ws) for ws in targets))

        if dead:
            async with self._lock:
                for ws in dead:
                    self._connections.discard(ws)
            log.info(
                "ws_clients_pruned",
                pruned=len(dead),
                total=len(self._connections),
            )

    async def close_all(self) -> None:
        async with self._lock:
            targets = list(self._connections)
            self._connections.clear()
        for ws in targets:
            try:
                await ws.close()
            except Exception:  # noqa: BLE001 - best-effort close
                pass
