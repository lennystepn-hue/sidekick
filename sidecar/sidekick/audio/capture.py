"""Microphone capture (16 kHz mono float32, 512-sample frames).

WASAPI shared mode with automatic conversion delivers 16 kHz straight from Windows. If
the endpoint still refuses (non-WASAPI device), the stream is opened at the device's
native rate and resampled seam-free into 512-sample frames.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Iterator
from typing import Protocol

import numpy as np

from . import portaudio
from .player import Resampler
from .vad import FRAME, SAMPLE_RATE

log = logging.getLogger(__name__)


class Capture(Protocol):
    def frames(self) -> Iterator[np.ndarray]: ...
    def close(self) -> None: ...


def find_input_device(name_substring: str | None) -> int | None:
    return portaudio.find_device(name_substring, "input")


class SounddeviceCapture:
    def __init__(self, device: int | None) -> None:
        import sounddevice as sd

        self._q: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=400)
        self._closed = threading.Event()
        if device is None:
            device = portaudio.wasapi_default_device("input")
        self.device = device
        self.native_rate = SAMPLE_RATE
        self._pending = np.zeros(0, dtype=np.float32)
        self._resampler: Resampler | None = None
        extra = portaudio.wasapi_settings(device)

        def push(frame: np.ndarray) -> None:
            try:
                self._q.put_nowait(frame)
            except queue.Full:
                pass

        def callback_native(indata, frames, time_info, status) -> None:  # noqa: ARG001
            if status:
                log.debug("capture status: %s", status)
            push(indata[:, 0].copy())

        def callback_resampled(indata, frames, time_info, status) -> None:  # noqa: ARG001
            if status:
                log.debug("capture status: %s", status)
            assert self._resampler is not None
            converted = self._resampler.process(indata[:, 0].astype(np.float32)).reshape(-1)
            buf = np.concatenate([self._pending, converted])
            while len(buf) >= FRAME:
                push(buf[:FRAME].copy())
                buf = buf[FRAME:]
            self._pending = buf

        try:
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=FRAME,
                device=device,
                extra_settings=extra,
                callback=callback_native,
            )
            self._stream.start()
        except sd.PortAudioError as exc:
            info = sd.query_devices(device if device is not None else sd.default.device[0])
            self.native_rate = int(info["default_samplerate"])
            block = int(round(FRAME * self.native_rate / SAMPLE_RATE))
            self._resampler = Resampler(self.native_rate, SAMPLE_RATE)
            log.warning(
                "capture at 16 kHz failed on %r (%s); using %s Hz with resampling",
                info["name"],
                exc,
                self.native_rate,
            )
            self._stream = sd.InputStream(
                samplerate=self.native_rate,
                channels=1,
                dtype="float32",
                blocksize=block,
                device=device,
                extra_settings=extra,
                callback=callback_resampled,
            )
            self._stream.start()
        portaudio.stream_opened()
        log.info("capture opened on %r (index %s)", portaudio.device_name(device), device)

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
            portaudio.stream_closed()
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
