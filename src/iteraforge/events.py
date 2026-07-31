from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._revision = 0
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    @property
    def revision(self) -> int:
        return self._revision

    async def publish(self, event: dict[str, Any]) -> None:
        self._revision += 1
        event = {"revision": self._revision, **event}
        for queue in list(self._subscribers):
            await queue.put(event)

    async def stream(self) -> AsyncGenerator[str, None]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers.add(queue)
        try:
            yield "event: hello\ndata: {\"type\":\"hello\"}\n\n"
            while True:
                event = await queue.get()
                yield f"event: message\ndata: {json.dumps(event)}\n\n"
        finally:
            self._subscribers.discard(queue)
