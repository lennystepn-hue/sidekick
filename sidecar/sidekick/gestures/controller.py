"""Bridges the hook thread to asyncio actions and keeps a log for the gesture test view."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

from ..config import Settings
from ..events import EventBus
from ..state import AppState
from .engine import resolve_action, should_swallow
from .mediakeys import KeyHandler, MediaKeyHook

log = logging.getLogger(__name__)

Action = Callable[[], Awaitable[None] | None]
HookFactory = Callable[[KeyHandler, Callable[[], bool]], MediaKeyHook]


class GestureController:
    def __init__(
        self,
        hook_factory: HookFactory,
        settings: Callable[[], Settings],
        state: AppState,
        bus: EventBus,
        actions: dict[str, Action],
    ) -> None:
        self._settings = settings
        self._state = state
        self._bus = bus
        self._actions = actions
        self._loop: asyncio.AbstractEventLoop | None = None
        self.hook = hook_factory(self._on_key, self._should_swallow)
        self.log: deque[dict[str, Any]] = deque(maxlen=100)
        self._log_lock = threading.Lock()

    def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self.hook.start()

    def stop(self) -> None:
        self.hook.stop()

    def _should_swallow(self) -> bool:
        return should_swallow(self._settings().gestures, self._state.glasses_connected)

    def _on_key(self, key: str, swallowed: bool, injected: bool) -> None:
        gesture, action = resolve_action(key, self._settings().gestures)
        entry = {
            "ts": time.time(),
            "key": key,
            "gesture": gesture,
            "action": action,
            "swallowed": swallowed,
            "injected": injected,
        }
        with self._log_lock:
            self.log.append(entry)
        self._bus.publish("media_key", entry)
        if action == "none":
            return
        if self._loop is None:
            self._dispatch(action)
        else:
            self._loop.call_soon_threadsafe(self._dispatch, action)

    def _dispatch(self, action: str) -> None:
        fn = self._actions.get(action)
        if fn is None:
            log.warning("no handler for gesture action %s", action)
            return
        try:
            result = fn()
            if asyncio.iscoroutine(result):
                task = asyncio.ensure_future(result)
                task.add_done_callback(_log_task_error)
        except Exception:  # noqa: BLE001
            log.exception("gesture action %s failed", action)

    def entries(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._log_lock:
            return list(self.log)[-limit:]


def _log_task_error(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        log.error("gesture action failed: %r", exc)
