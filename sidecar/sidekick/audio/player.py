"""Playback of WAV files and streamed PCM on a chosen output device.

One worker thread plays jobs sequentially. A job is an iterator of `PcmChunk`s; the first
chunk decides sample rate and channel count. `stop()` aborts the current job and clears the
queue. Output goes through an `OutputBackend` so tests can run without a sound card.
"""

from __future__ import annotations

import logging
import queue
import threading
import wave
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Protocol

import numpy as np

log = logging.getLogger(__name__)

# (samples as float32 in [-1, 1] shaped (n, channels), samplerate, channels)
PcmChunk = tuple[np.ndarray, int, int]
END = object()


class OutputSink(Protocol):
    def write(self, samples: np.ndarray) -> None: ...
    def close(self) -> None: ...


class OutputBackend(Protocol):
    def open(self, samplerate: int, channels: int, device: int | None) -> OutputSink: ...


class SounddeviceOutput:
    """PortAudio/WASAPI output. Falls back to the device's native rate with resampling."""

    def open(self, samplerate: int, channels: int, device: int | None) -> OutputSink:
        import sounddevice as sd

        try:
            stream = sd.OutputStream(samplerate=samplerate, channels=channels, dtype="float32", device=device)
            stream.start()
            return _SdSink(stream, samplerate, samplerate)
        except sd.PortAudioError as exc:
            info = sd.query_devices(device if device is not None else sd.default.device[1])
            native = int(info["default_samplerate"])
            log.warning("output at %s Hz failed (%s); resampling to %s Hz", samplerate, exc, native)
            stream = sd.OutputStream(samplerate=native, channels=channels, dtype="float32", device=device)
            stream.start()
            return _SdSink(stream, samplerate, native)


class _SdSink:
    def __init__(self, stream, src_rate: int, dst_rate: int) -> None:
        self._stream = stream
        self._src = src_rate
        self._dst = dst_rate

    def write(self, samples: np.ndarray) -> None:
        if self._src != self._dst:
            samples = resample(samples, self._src, self._dst)
        self._stream.write(np.ascontiguousarray(samples, dtype=np.float32))

    def close(self) -> None:
        try:
            self._stream.stop()
        finally:
            self._stream.close()


def resample(samples: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst or len(samples) == 0:
        return samples
    n_out = int(round(len(samples) * dst / src))
    x_old = np.linspace(0, 1, len(samples), endpoint=False)
    x_new = np.linspace(0, 1, n_out, endpoint=False)
    if samples.ndim == 1:
        return np.interp(x_new, x_old, samples).astype(np.float32)
    return np.stack([np.interp(x_new, x_old, samples[:, c]) for c in range(samples.shape[1])], axis=1).astype(
        np.float32
    )


def load_wav(path: Path) -> PcmChunk:
    with wave.open(str(path), "rb") as w:
        sr, ch, width, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
        raw = w.readframes(n)
    if width == 2:
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif width == 4:
        data = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128) / 128.0
    return data.reshape(-1, ch), sr, ch


def pcm16_to_float(data: bytes, channels: int) -> np.ndarray:
    arr = (
        np.frombuffer(data[: len(data) - len(data) % (2 * channels)], dtype=np.int16).astype(np.float32)
        / 32768.0
    )
    return arr.reshape(-1, channels)


def find_output_device(name_substring: str | None) -> int | None:
    """Index of the first WASAPI output device whose name contains the substring."""
    if not name_substring:
        return None
    import sounddevice as sd

    needle = name_substring.lower()
    hostapis = sd.query_hostapis()
    candidates: list[tuple[int, int]] = []
    for idx, dev in enumerate(sd.query_devices()):
        if dev["max_output_channels"] <= 0 or needle not in dev["name"].lower():
            continue
        api_name = hostapis[dev["hostapi"]]["name"].lower()
        prio = 0 if "wasapi" in api_name else 1
        candidates.append((prio, idx))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][1]


class StreamHandle:
    """Feed PCM into a running playback job from another thread."""

    def __init__(self) -> None:
        self._q: queue.Queue[PcmChunk | object] = queue.Queue()
        self.done = threading.Event()

    def write(self, chunk: PcmChunk) -> None:
        self._q.put(chunk)

    def end(self) -> None:
        self._q.put(END)

    def __iter__(self) -> Iterator[PcmChunk]:
        while True:
            item = self._q.get()
            if item is END:
                return
            yield item  # type: ignore[misc]


class Player:
    def __init__(
        self,
        output: OutputBackend,
        device_resolver: Callable[[], int | None] | None = None,
        volume_resolver: Callable[[], float] | None = None,
    ) -> None:
        self._output = output
        self._device_resolver = device_resolver or (lambda: None)
        self._volume_resolver = volume_resolver or (lambda: 1.0)
        self._jobs: queue.Queue[tuple[Iterable[PcmChunk], threading.Event, float | None]] = queue.Queue()
        self._stop_current = threading.Event()
        self._playing = threading.Event()
        self._idle = threading.Event()
        self._idle.set()
        self._thread = threading.Thread(target=self._run, name="player", daemon=True)
        self._thread.start()

    @property
    def is_playing(self) -> bool:
        return self._playing.is_set()

    def play_wav(self, path: Path, block: bool = False, volume: float | None = None) -> threading.Event:
        return self.play_chunks([load_wav(path)], block=block, volume=volume)

    def play_chunks(
        self, chunks: Iterable[PcmChunk], block: bool = False, volume: float | None = None
    ) -> threading.Event:
        finished = threading.Event()
        self._idle.clear()
        self._jobs.put((chunks, finished, volume))
        if block:
            finished.wait()
        return finished

    def play_stream(self, volume: float | None = None) -> tuple[StreamHandle, threading.Event]:
        handle = StreamHandle()
        finished = self.play_chunks(handle, volume=volume)
        return handle, finished

    def stop(self) -> None:
        while True:
            try:
                _chunks, finished, _v = self._jobs.get_nowait()
                finished.set()
            except queue.Empty:
                break
        self._stop_current.set()

    def wait_idle(self, timeout: float | None = None) -> bool:
        return self._idle.wait(timeout)

    def _run(self) -> None:
        while True:
            chunks, finished, volume = self._jobs.get()
            self._stop_current.clear()
            self._playing.set()
            try:
                self._play(chunks, volume)
            except Exception:  # noqa: BLE001
                log.exception("playback failed")
            finally:
                self._playing.clear()
                finished.set()
                if self._jobs.empty():
                    self._idle.set()

    def _play(self, chunks: Iterable[PcmChunk], volume: float | None) -> None:
        sink: OutputSink | None = None
        gain = self._volume_resolver() if volume is None else volume
        try:
            for samples, sr, ch in chunks:
                if self._stop_current.is_set():
                    break
                if sink is None:
                    sink = self._output.open(sr, ch, self._device_resolver())
                if samples.ndim == 1:
                    samples = samples.reshape(-1, ch)
                sink.write(samples * gain)
        finally:
            if sink is not None:
                sink.close()
