"""Playback of WAV files and streamed PCM on a chosen output device.

One worker thread plays jobs sequentially. A job is an iterator of `PcmChunk`s; the first
chunk decides sample rate and channel count. `stop()` aborts the current job and clears the
queue. Output goes through an `OutputBackend` so tests can run without a sound card.
Playback errors are recorded on the job (`StreamHandle.error` / the returned `Job`) so the
caller can fall back instead of believing the audio was heard.

Sample rates: the WASAPI stream is opened in shared mode with automatic conversion, so
Windows resamples 44.1 kHz tones and 24 kHz speech to the endpoint's mix format. Only when
that is impossible (non-WASAPI device) the stream runs at the device's native rate and a
seam-free `Resampler` converts each chunk.
"""

from __future__ import annotations

import logging
import queue
import threading
import wave
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import numpy as np

from . import portaudio

log = logging.getLogger(__name__)

# (samples as float32 in [-1, 1] shaped (n, channels), samplerate, channels)
PcmChunk = tuple[np.ndarray, int, int]
END = object()


class OutputSink(Protocol):
    def write(self, samples: np.ndarray) -> None: ...
    def close(self) -> None: ...


class OutputBackend(Protocol):
    def open(self, samplerate: int, channels: int, device: int | None) -> OutputSink: ...


class Resampler:
    """Linear-interpolation resampler that keeps its phase across chunks (no seams)."""

    def __init__(self, src: int, dst: int) -> None:
        self.src = src
        self.dst = dst
        self._ratio = src / dst
        self._pos = 0.0
        self._prev: np.ndarray | None = None

    def process(self, samples: np.ndarray) -> np.ndarray:
        if self.src == self.dst or len(samples) == 0:
            return samples
        if samples.ndim == 1:
            samples = samples.reshape(-1, 1)
        data = samples if self._prev is None else np.vstack([self._prev, samples])
        n = len(data)
        if n < 2:
            self._prev = data[-1:]
            return np.zeros((0, data.shape[1]), dtype=np.float32)
        positions = np.arange(self._pos, n - 1, self._ratio)
        if len(positions) == 0:
            self._pos -= n - 1
            self._prev = data[-1:]
            return np.zeros((0, data.shape[1]), dtype=np.float32)
        idx = positions.astype(np.int64)
        frac = (positions - idx)[:, None]
        out = data[idx] * (1.0 - frac) + data[idx + 1] * frac
        self._pos = positions[-1] + self._ratio - (n - 1)
        self._prev = data[-1:]
        return out.astype(np.float32)


class SounddeviceOutput:
    """PortAudio/WASAPI output (shared mode, automatic sample-rate conversion)."""

    def open(self, samplerate: int, channels: int, device: int | None) -> OutputSink:
        import sounddevice as sd

        if device is None:
            device = portaudio.wasapi_default_device("output")
        extra = portaudio.wasapi_settings(device)
        try:
            stream = sd.OutputStream(
                samplerate=samplerate, channels=channels, dtype="float32", device=device,
                extra_settings=extra, latency="high",
            )
            stream.start()
            return _SdSink(stream, samplerate, samplerate)
        except sd.PortAudioError as exc:
            info = sd.query_devices(device if device is not None else sd.default.device[1])
            native = int(info["default_samplerate"])
            log.warning(
                "output at %s Hz failed on %r (%s); using %s Hz with seamless resampling",
                samplerate, info["name"], exc, native,
            )
            stream = sd.OutputStream(
                samplerate=native, channels=channels, dtype="float32", device=device,
                extra_settings=extra, latency="high",
            )
            stream.start()
            return _SdSink(stream, samplerate, native)


class _SdSink:
    def __init__(self, stream, src_rate: int, dst_rate: int) -> None:
        self._stream = stream
        self._resampler = Resampler(src_rate, dst_rate) if src_rate != dst_rate else None
        portaudio.stream_opened()

    def write(self, samples: np.ndarray) -> None:
        if self._resampler is not None:
            samples = self._resampler.process(samples)
            if len(samples) == 0:
                return
        self._stream.write(np.ascontiguousarray(samples, dtype=np.float32))

    def close(self) -> None:
        try:
            self._stream.stop()
        finally:
            try:
                self._stream.close()
            finally:
                portaudio.stream_closed()


def resample(samples: np.ndarray, src: int, dst: int) -> np.ndarray:
    """One-shot resampling of a complete signal (use `Resampler` for streams)."""
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
    return portaudio.find_device(name_substring, "output")


@dataclass
class Job:
    chunks: Iterable[PcmChunk]
    finished: threading.Event = field(default_factory=threading.Event)
    volume: float | None = None
    error: BaseException | None = None
    wrote_samples: int = 0


class StreamHandle:
    """Feed PCM into a running playback job from another thread."""

    def __init__(self) -> None:
        self._q: queue.Queue[PcmChunk | object] = queue.Queue()
        self.job: Job | None = None

    @property
    def error(self) -> BaseException | None:
        return self.job.error if self.job else None

    @property
    def wrote_samples(self) -> int:
        return self.job.wrote_samples if self.job else 0

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
        self._jobs: queue.Queue[Job] = queue.Queue()
        self._stop_current = threading.Event()
        self._playing = threading.Event()
        self._idle = threading.Event()
        self._idle.set()
        self.last_error: BaseException | None = None
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
        return self.submit(chunks, block=block, volume=volume).finished

    def submit(self, chunks: Iterable[PcmChunk], block: bool = False, volume: float | None = None) -> Job:
        job = Job(chunks=chunks, volume=volume)
        if isinstance(chunks, StreamHandle):
            chunks.job = job
        self._idle.clear()
        self._jobs.put(job)
        if block:
            job.finished.wait()
        return job

    def play_stream(self, volume: float | None = None) -> tuple[StreamHandle, threading.Event]:
        handle = StreamHandle()
        job = self.submit(handle, volume=volume)
        return handle, job.finished

    def stop(self) -> None:
        while True:
            try:
                job = self._jobs.get_nowait()
                job.finished.set()
            except queue.Empty:
                break
        self._stop_current.set()

    def wait_idle(self, timeout: float | None = None) -> bool:
        return self._idle.wait(timeout)

    def _run(self) -> None:
        while True:
            job = self._jobs.get()
            self._stop_current.clear()
            self._playing.set()
            try:
                self._play(job)
            except Exception as exc:  # noqa: BLE001
                log.exception("playback failed")
                job.error = exc
                self.last_error = exc
                # drain a stream so its producer does not block forever
                if isinstance(job.chunks, StreamHandle):
                    for _ in job.chunks:
                        if self._stop_current.is_set():
                            break
            finally:
                self._playing.clear()
                job.finished.set()
                if self._jobs.empty():
                    self._idle.set()

    def _play(self, job: Job) -> None:
        sink: OutputSink | None = None
        gain = self._volume_resolver() if job.volume is None else job.volume
        try:
            for samples, sr, ch in job.chunks:
                if self._stop_current.is_set():
                    break
                if sink is None:
                    sink = self._output.open(sr, ch, self._device_resolver())
                if samples.ndim == 1:
                    samples = samples.reshape(-1, ch)
                sink.write(samples * gain)
                job.wrote_samples += len(samples)
        finally:
            if sink is not None:
                sink.close()
