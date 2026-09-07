"""Presence state machine (pure) and the monitor task that feeds it."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Literal, Protocol

from ..config import Settings
from ..state import AppState

log = logging.getLogger(__name__)

PresenceValue = Literal["unknown", "present", "absent"]
GlassesValue = Literal["unknown", "connected", "disconnected"]


@dataclass(slots=True)
class PresenceSample:
    unlocked: bool
    idle_s: float
    glasses_connected: bool


@dataclass(slots=True)
class PresenceState:
    presence: PresenceValue = "unknown"
    glasses: GlassesValue = "unknown"
    pending: tuple[str, str] | None = None
    pending_count: int = 0


def _candidate(sample: PresenceSample, idle_threshold_s: float) -> tuple[str, str]:
    glasses = "connected" if sample.glasses_connected else "disconnected"
    present = sample.unlocked and sample.idle_s < idle_threshold_s and sample.glasses_connected
    return ("present" if present else "absent", glasses)


def next_presence(
    prev: PresenceState, sample: PresenceSample, idle_threshold_s: float, debounce: int = 2
) -> tuple[PresenceState, list[str]]:
    """Feed one sample; return the new state and the transitions it confirmed."""
    cand = _candidate(sample, idle_threshold_s)
    if cand == (prev.presence, prev.glasses):
        return replace(prev, pending=None, pending_count=0), []
    if prev.pending == cand:
        count = prev.pending_count + 1
    else:
        count = 1
    if count < debounce:
        return replace(prev, pending=cand, pending_count=count), []
    transitions: list[str] = []
    new_presence, new_glasses = cand
    if new_glasses != prev.glasses:
        if new_glasses == "connected":
            transitions.append("glasses_connected")
        elif prev.glasses != "unknown":
            transitions.append("glasses_disconnected")
    if new_presence != prev.presence:
        if new_presence == "present":
            transitions.append("became_present")
        elif prev.presence != "unknown":
            transitions.append("became_absent")
    return PresenceState(presence=new_presence, glasses=new_glasses), transitions  # type: ignore[arg-type]


class SessionLockBackend(Protocol):
    def is_unlocked(self) -> bool: ...


class IdleBackend(Protocol):
    def idle_seconds(self) -> float: ...


class BluetoothBackend(Protocol):
    def is_connected(self, name_substring: str) -> bool | None: ...


@dataclass
class FakePresenceBackends:
    unlocked: bool = True
    idle_s: float = 0.0
    connected: bool | None = True

    def is_unlocked(self) -> bool:
        return self.unlocked

    def idle_seconds(self) -> float:
        return self.idle_s

    def is_connected(self, name_substring: str) -> bool | None:
        return self.connected


TransitionHandler = Callable[[str], Awaitable[None] | None]


class PresenceMonitor:
    def __init__(
        self,
        lock: SessionLockBackend,
        idle: IdleBackend,
        bluetooth: BluetoothBackend,
        state: AppState,
        settings: Callable[[], Settings],
        on_transition: TransitionHandler,
    ) -> None:
        self._lock = lock
        self._idle = idle
        self._bt = bluetooth
        self._state = state
        self._settings = settings
        self._on_transition = on_transition
        self._task: asyncio.Task | None = None
        self._tick_lock = asyncio.Lock()
        self.machine = PresenceState()
        self.last_sample: PresenceSample | None = None
        self.last_tick = 0.0

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="presence")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    def sample(self) -> PresenceSample:
        name = self._settings().audio.glasses_device_name
        connected = self._bt.is_connected(name)
        return PresenceSample(
            unlocked=self._lock.is_unlocked(),
            idle_s=self._idle.idle_seconds(),
            glasses_connected=bool(connected),
        )

    async def tick(self) -> list[str]:
        async with self._tick_lock:  # manual ticks (UI) must not race the poll loop
            return await self._tick()

    async def _tick(self) -> list[str]:
        try:
            sample = await asyncio.to_thread(self.sample)
        except Exception as exc:  # noqa: BLE001
            log.warning("presence sample failed: %s", exc)
            return []
        self.last_sample = sample
        self.last_tick = time.time()
        threshold = self._settings().presence.idle_threshold_min * 60
        self.machine, transitions = next_presence(self.machine, sample, threshold)
        self._state.update(
            presence=self.machine.presence,
            glasses=self.machine.glasses,
            glasses_name=self._settings().audio.glasses_device_name,
        )
        for name in transitions:
            log.info("presence transition: %s", name)
            try:
                result = self._on_transition(name)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:  # noqa: BLE001
                log.exception("transition handler failed for %s", name)
        return transitions

    async def _run(self) -> None:
        while True:
            await self.tick()
            await asyncio.sleep(max(0.5, self._settings().presence.poll_interval_s))
