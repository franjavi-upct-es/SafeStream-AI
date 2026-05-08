# services/inference/tests/test_connection_manager.py
"""Behaviour of the WebSocket fan-out helper."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest


class FakeWebSocket:
    """Minimal WebSocket stand-in.

    The manager only calls ``send_text`` and ``close`` on us, so that's
    the entire surface we need to mock.
    """

    def __init__(
        self,
        name: str,
        *,
        fail: bool = False,
        slow: bool = False,
    ) -> None:
        self.name = name
        self.fail = fail
        self.slow = slow
        self.received: list[str] = []
        self.closed = False

    async def send_text(self, msg: str) -> None:
        if self.fail:
            raise RuntimeError(f"{self.name} dead")
        if self.slow:
            await asyncio.sleep(5.0)  # exceeds the manager's send timeout
        self.received.append(msg)

    async def close(self, *args: Any, **kwargs: Any) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_broadcast_delivers_to_all_clients() -> None:
    from workers.connection_manager import ConnectionManager

    mgr = ConnectionManager(send_timeout=0.5)
    a, b = FakeWebSocket("a"), FakeWebSocket("b")
    await mgr.add(a)  # type: ignore[arg-type]
    await mgr.add(b)  # type: ignore[arg-type]

    await mgr.broadcast("hello")

    assert a.received == ["hello"]
    assert b.received == ["hello"]


@pytest.mark.asyncio
async def test_broadcast_prunes_failed_clients() -> None:
    from workers.connection_manager import ConnectionManager

    mgr = ConnectionManager(send_timeout=0.1)
    healthy = FakeWebSocket("alive")
    dead = FakeWebSocket("dead", fail=True)
    slow = FakeWebSocket("slow", slow=True)

    for ws in (healthy, dead, slow):
        await mgr.add(ws)  # type: ignore[arg-type]

    await mgr.broadcast("first")

    assert healthy.received == ["first"]
    assert dead.received == []  # raised
    assert slow.received == []  # timed out
    # Two pruned, one remains.
    assert mgr.size == 1


@pytest.mark.asyncio
async def test_concurrent_broadcasts_do_not_deadlock() -> None:
    from workers.connection_manager import ConnectionManager

    mgr = ConnectionManager(send_timeout=0.5)
    client = FakeWebSocket("c")
    await mgr.add(client)  # type: ignore[arg-type]

    await asyncio.gather(*[mgr.broadcast(f"msg-{i}") for i in range(20)])

    assert len(client.received) == 20


@pytest.mark.asyncio
async def test_close_all_clears_registry() -> None:
    from workers.connection_manager import ConnectionManager

    mgr = ConnectionManager()
    a, b = FakeWebSocket("a"), FakeWebSocket("b")
    await mgr.add(a)  # type: ignore[arg-type]
    await mgr.add(b)  # type: ignore[arg-type]

    await mgr.close_all()

    assert mgr.size == 0
    assert a.closed
    assert b.closed


@pytest.mark.asyncio
async def test_broadcast_with_no_clients_is_noop() -> None:
    from workers.connection_manager import ConnectionManager

    mgr = ConnectionManager()
    # Must not raise.
    await mgr.broadcast("ignored")
