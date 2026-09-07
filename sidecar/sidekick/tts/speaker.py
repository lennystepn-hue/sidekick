"""Speaker: queue of things to say, engine fallback chain, interruptible playback."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass

from ..audio.player import Player
from ..events import EventBus
from ..state import AppState
from .base import TtsEngine

log = logging.getLogger(__name__)

BUSY_MODES = ("listening", "btw_listening", "transcribing")


@dataclass(slots=True)
class Utterance:
    text: str
    kind: str = "summary"


class Speaker:
    def __init__(
        self,
        engines: dict[str, TtsEngine],
        order: Callable[[], list[str]],
        player: Player,
        state: AppState,
        bus: EventBus,
    ) -> None:
        self._engines = engines
        self._order = order
        self._player = player
        self._state = state
        self._bus = bus
        self._queue: asyncio.Queue[Utterance] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._current: asyncio.Task | None = None
        self.last_text: str | None = None
        self.spoken: list[Utterance] = []

    # --- lifecycle -----------------------------------------------------
    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._worker(), name="speaker")

    async def stop(self) -> None:
        self.stop_speaking()
        if self._task:
            self._task.cancel()
            self._task = None

    # --- public API ----------------------------------------------------
    def speak(self, text: str, kind: str = "summary") -> None:
        text = (text or "").strip()
        if not text:
            return
        self.start()
        self._queue.put_nowait(Utterance(text=text, kind=kind))

    def stop_speaking(self) -> None:
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        if self._current and not self._current.done():
            self._current.cancel()
        self._player.stop()

    def repeat_last(self) -> None:
        if self.is_speaking:
            self.stop_speaking()
            return
        if self.last_text:
            self.speak(self.last_text, kind="repeat")

    @property
    def is_speaking(self) -> bool:
        return self._current is not None and not self._current.done()

    # --- internals -----------------------------------------------------
    async def _worker(self) -> None:
        while True:
            utt = await self._queue.get()
            await self._wait_until_free()
            self._current = asyncio.create_task(self._say(utt))
            try:
                await self._current
            except asyncio.CancelledError:
                if self._task is None or self._task.cancelled():
                    raise
            except Exception:  # noqa: BLE001
                log.exception("speaker failed")
            finally:
                self._current = None
                if self._state.mode == "speaking":
                    self._state.update(mode="idle")

    async def _wait_until_free(self) -> None:
        for _ in range(120):  # up to 60 s
            if self._state.mode not in BUSY_MODES:
                return
            await asyncio.sleep(0.5)

    async def _say(self, utt: Utterance) -> None:
        self.last_text = utt.text
        self.spoken.append(utt)
        log.info("speaking [%s]: %s", utt.kind, utt.text[:200])
        self._bus.publish("spoken", {"text": utt.text, "kind": utt.kind})
        errors: list[str] = []
        for name in self._order():
            engine = self._engines.get(name)
            if engine is None or not engine.available():
                continue
            if self._state.mode == "idle":
                self._state.update(mode="speaking")
            handle, finished = self._player.play_stream()
            wrote = False
            try:
                async for chunk in engine.synthesize(utt.text):
                    handle.write(chunk)
                    wrote = True
                handle.end()
                await asyncio.to_thread(finished.wait)
                if wrote:
                    return
                errors.append(f"{name}: leer")
            except asyncio.CancelledError:
                handle.end()
                self._player.stop()
                raise
            except Exception as exc:  # noqa: BLE001
                handle.end()
                self._player.stop()
                errors.append(f"{name}: {exc}")
                log.warning("tts engine %s failed: %s", name, exc)
        self._bus.publish(
            "error", {"module": "tts", "message": "Sprachausgabe fehlgeschlagen: " + "; ".join(errors)}
        )


class FakeEngine:
    def __init__(self, name: str, fail: bool = False, samples: int = 2400) -> None:
        self.name = name
        self.fail = fail
        self.samples = samples
        self.texts: list[str] = []

    def available(self) -> bool:
        return True

    async def synthesize(self, text: str):
        import numpy as np

        self.texts.append(text)
        if self.fail:
            raise RuntimeError("boom")
        for _ in range(2):
            yield np.zeros((self.samples, 1), dtype=np.float32), 24000, 1
            await asyncio.sleep(0)
