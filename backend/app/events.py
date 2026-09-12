from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator


class EventBus:
    """In-process pub/sub used to fan events out to SSE subscribers."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()

    async def publish(self, event: dict) -> None:
        payload = json.dumps(event, default=str).encode()
        dead: list[asyncio.Queue] = []
        for q in self._subscribers:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._subscribers.discard(q)

    async def iterator(self) -> AsyncIterator[bytes]:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.add(q)
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=20)
                except asyncio.TimeoutError:
                    yield b": keepalive\n\n"
                    continue
                yield b"data: " + payload + b"\n\n"
        finally:
            self._subscribers.discard(q)


bus = EventBus()