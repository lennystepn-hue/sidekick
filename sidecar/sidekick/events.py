"""Tiny asyncio event bus.

Producers may live on hardware threads (audio callbacks, keyboard hook, COM threads), so
`publish` is thread-safe: when called off-loop it marshals onto the loop with
`call_soon_threadsafe`. Consumers subscribe and receive `Event` objects through queues.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass(slots=True)
class Event:
    type: str
    data: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "ts": self.ts, "data": self.data}


class EventBus:
    def __init__(self, max_queue: int = 500) -> None:
        self._subscribers: set[asyncio.Queue[Event]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._max_queue = max_queue
        self._lock = threading.Lock()
        self.history: list[Event] = []

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue[Event]:
        q: asyncio.Queue[Event] = asyncio.Queue(maxsize=self._max_queue)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[Event]) -> None:
        with self._lock:
            self._subscribers.discard(q)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def publish(self, type: str, data: dict[str, Any] | None = None) -> Event:
        ev = Event(type=type, data=data or {})
        loop = self._loop
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
        if loop is None:
            self._deliver(ev)
            return ev
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            self._deliver(ev)
        else:
            loop.call_soon_threadsafe(self._deliver, ev)
        return ev

    def _deliver(self, ev: Event) -> None:
        self.history.append(ev)
        if len(self.history) > 200:
            del self.history[: len(self.history) - 200]
        with self._lock:
            subs = list(self._subscribers)
        for q in subs:
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:
                log.warning("event queue full, dropping %s for a slow subscriber", ev.type)
