"""Listen pipeline: gesture -> capture -> VAD -> STT -> cleanup -> review -> deliver."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

from .audio.capture import Capture
from .audio.router import AudioRouter
from .audio.sounds import Sounds
from .audio.vad import Segmenter, SegmentEvent
from .config import Settings
from .db import Database, new_id, now_iso
from .events import EventBus
from .state import AppState
from .stt.cleanup import Cleaner
from .stt.whisper import STT

log = logging.getLogger(__name__)


class Deliverer(Protocol):
    async def deliver(self, text: str, mode: str) -> str:
        """Deliver text; returns the target label (embedded|clipboard|answer|btw)."""
        ...


@dataclass
class ReviewEntry:
    future: asyncio.Future
    raw: str
    cleaned: str
    mode: str


class ListenController:
    def __init__(
        self,
        capture_factory: Callable[[], Capture],
        segmenter_factory: Callable[[], Segmenter],
        stt: STT,
        cleaner: Cleaner,
        sounds: Sounds,
        router: AudioRouter | None,
        state: AppState,
        bus: EventBus,
        db: Database,
        settings: Callable[[], Settings],
        deliverer: Deliverer,
    ) -> None:
        self._capture_factory = capture_factory
        self._segmenter_factory = segmenter_factory
        self._stt = stt
        self._cleaner = cleaner
        self._sounds = sounds
        self._router = router
        self._state = state
        self._bus = bus
        self._db = db
        self._settings = settings
        self._deliverer = deliverer
        self._task: asyncio.Task | None = None
        self._manual_stop = threading.Event()
        self._cancel = threading.Event()
        self._reviews: dict[str, ReviewEntry] = {}
        self._capture: Capture | None = None
        self.recent: list[dict[str, Any]] = []

    # --- public API ----------------------------------------------------
    @property
    def recording(self) -> bool:
        return (
            self._task is not None
            and not self._task.done()
            and self._state.mode in ("listening", "btw_listening")
        )

    @property
    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    async def toggle(self, mode: str = "main") -> bool:
        """Tap: start recording, or stop the running recording and transcribe. Returns True if now recording."""
        if self.recording:
            self._manual_stop.set()
            return False
        if self.busy:
            log.info("listen pipeline busy (%s), ignoring toggle", self._state.mode)
            return False
        self._manual_stop.clear()
        self._cancel.clear()
        self._task = asyncio.create_task(self._run(mode), name="listen")
        return True

    async def stop(self) -> None:
        if self.recording:
            self._manual_stop.set()

    async def cancel(self) -> None:
        self._cancel.set()
        self._manual_stop.set()
        for entry in list(self._reviews.values()):
            if not entry.future.done():
                entry.future.set_result(("cancel", None))

    def send_now(self, transcript_id: str, text: str | None = None) -> bool:
        entry = self._reviews.get(transcript_id)
        if entry is None or entry.future.done():
            return False
        entry.future.set_result(("send", text))
        return True

    def cancel_review(self, transcript_id: str) -> bool:
        entry = self._reviews.get(transcript_id)
        if entry is None or entry.future.done():
            return False
        entry.future.set_result(("cancel", None))
        return True

    # --- pipeline -------------------------------------------------------
    def _publish(self, transcript: dict[str, Any]) -> None:
        self.recent = [t for t in self.recent if t["id"] != transcript["id"]]
        self.recent.insert(0, transcript)
        del self.recent[50:]
        self._bus.publish("transcript", transcript)

    async def _run(self, mode: str) -> None:
        listen_mode = "btw_listening" if mode == "btw" else "listening"
        self._state.update(mode=listen_mode)
        self._sounds.play("listening_start")
        audio: np.ndarray | None = None
        try:
            audio = await asyncio.to_thread(self._record)
        except Exception as exc:  # noqa: BLE001
            log.exception("recording failed")
            self._bus.publish("error", {"module": "listen", "message": f"Aufnahme fehlgeschlagen: {exc}"})
        self._sounds.play("listening_stop")
        if self._router is not None:
            try:
                await asyncio.to_thread(self._router.ensure_a2dp)
            except Exception as exc:  # noqa: BLE001
                log.warning("ensure_a2dp failed: %s", exc)
        if self._cancel.is_set() or audio is None or len(audio) == 0:
            self._state.update(mode="idle")
            if not self._cancel.is_set():
                self._sounds.play("error")
                self._bus.publish("error", {"module": "listen", "message": "Keine Sprache erkannt"})
            return

        self._state.update(mode="transcribing")
        cfg = self._settings()
        try:
            raw = await self._stt.transcribe(audio, cfg.stt.hotwords)
        except Exception as exc:  # noqa: BLE001
            log.exception("transcription failed")
            self._state.update(mode="idle")
            self._sounds.play("error")
            self._bus.publish("error", {"module": "stt", "message": f"Transkription fehlgeschlagen: {exc}"})
            return
        raw = (raw or "").strip()
        if not raw:
            self._state.update(mode="idle")
            self._sounds.play("error")
            self._bus.publish("error", {"module": "stt", "message": "Leeres Transkript"})
            return

        cleaned, cleaned_ok = await self._cleaner.clean(raw)
        tid = new_id()
        delay = max(0.0, float(cfg.stt.review_delay_s))
        deadline = time.time() + delay
        transcript = {
            "id": tid,
            "raw": raw,
            "cleaned": cleaned,
            "cleaned_ok": cleaned_ok,
            "sent": False,
            "status": "reviewing",
            "target": "",
            "mode": mode,
            "review_deadline_ts": deadline,
            "ts": now_iso(),
        }
        self._db.add_transcript(tid, raw, cleaned, status="reviewing", target="")
        self._state.update(mode="reviewing")
        self._publish(transcript)

        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._reviews[tid] = ReviewEntry(future=future, raw=raw, cleaned=cleaned, mode=mode)
        decision: tuple[str, str | None]
        try:
            if delay > 0:
                decision = await asyncio.wait_for(future, delay)
            else:
                decision = ("send", None)
        except TimeoutError:
            decision = ("send", None)
        finally:
            self._reviews.pop(tid, None)
        self._state.update(mode="idle")

        if decision[0] == "cancel":
            self._db.mark_transcript(tid, "cancelled", False)
            self._publish({**transcript, "status": "cancelled"})
            return
        text = (decision[1] or "").strip() or cleaned
        try:
            target = await self._deliverer.deliver(text, mode)
        except Exception as exc:  # noqa: BLE001
            log.exception("delivery failed")
            self._db.mark_transcript(tid, "failed", False, cleaned=text)
            self._sounds.play("error")
            self._bus.publish("error", {"module": "delivery", "message": f"Zustellung fehlgeschlagen: {exc}"})
            self._publish({**transcript, "cleaned": text, "status": "failed"})
            return
        self._db.mark_transcript(tid, "sent", True, target=target, cleaned=text)
        self._publish({**transcript, "cleaned": text, "sent": True, "status": "sent", "target": target})

    def _record(self) -> np.ndarray | None:
        """Blocking capture loop (runs in a worker thread)."""
        capture = self._capture_factory()
        self._capture = capture
        segmenter = self._segmenter_factory()
        try:
            for frame in capture.frames():
                if self._cancel.is_set():
                    return None
                if self._manual_stop.is_set():
                    return segmenter.audio if segmenter.end_now() else None
                event = segmenter.feed(frame)
                if event in (SegmentEvent.SPEECH_END, SegmentEvent.MAX_DURATION):
                    return segmenter.audio
                if event == SegmentEvent.TIMEOUT_NO_SPEECH:
                    return None
            return segmenter.audio if segmenter.has_speech else None
        finally:
            capture.close()
            self._capture = None
