"""Microphone capture (16 kHz mono float32, 512-sample frames)."""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Iterator
from typing import Protocol

import numpy as np

from .vad import FRAME, SAMPLE_RATE

log = logging.getLogger(__name__)


class Capture(Protocol):
    def frames(self) -> Iterator[np.ndarray]: ...
    def close(self) -> None: ...


def find_input_device(name_substring: str | None) -> int | None:
    if not name_substring:
        return None
    import sounddevice as sd

    needle = name_substring.lower()
    hostapis = sd.query_hostapis()
    candidates: list[tuple[int, int]] = []
    for idx, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] <= 0 or needle not in dev["name"].lower():
            continue
        api_name = hostapis[dev["hostapi"]]["name"].lower()
        candidates.append((0 if "wasapi" in api_name else 1, idx))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][1]


class SounddeviceCapture:
    def __init__(self, device: int | None) -> None:
        import sounddevice as sd

        self._q: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=400)
        self._closed = threading.Event()
        self.device = device

        def callback(indata, frames, time_info, status) -> None:  # noqa: ARG001
            if status:
                log.debug("capture status: %s", status)
            try:
                self._q.put_nowait(indata[:, 0].copy())
            except queue.Full:
                pass

        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=FRAME,
            device=device,
            callback=callback,
        )
        self._stream.start()
        log.info("capture opened on device %s", device if device is not None else "default")

    def frames(self) -> Iterator[np.ndarray]:
        while not self._closed.is_set():
            try:
                frame = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            if frame is None:
                return
            yield frame

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        try:
            self._stream.stop()
            self._stream.close()
        finally:
            try:
                self._q.put_nowait(None)
            except queue.Full:
                pass
        log.info("capture closed")


class FakeCapture:
    def __init__(self, frames: list[np.ndarray]) -> None:
        self._frames = list(frames)
        self.closed = False

    def frames(self) -> Iterator[np.ndarray]:
        for f in self._frames:
            if self.closed:
                return
            yield f
        # keep yielding silence so segmenter timeouts can fire
        while not self.closed:
            yield np.zeros(FRAME, dtype=np.float32)

    def close(self) -> None:
        self.closed = True
