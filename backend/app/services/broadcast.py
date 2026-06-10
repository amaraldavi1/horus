"""In-process async pub/sub hub used to fan out MQTT messages to websockets."""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

MAX_QUEUE_SIZE = 256


class BroadcastHub:
    """Topic-based fanout; each subscriber gets its own bounded queue."""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[dict]]] = defaultdict(set)

    def subscribe(self, topic: str) -> asyncio.Queue[dict]:
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)
        self._subscribers[topic].add(queue)
        return queue

    def unsubscribe(self, topic: str, queue: asyncio.Queue[dict]) -> None:
        self._subscribers[topic].discard(queue)

    def publish(self, topic: str, message: dict) -> None:
        for queue in list(self._subscribers[topic]):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                logger.warning("Dropping %s broadcast for a slow websocket subscriber", topic)


hub = BroadcastHub()
