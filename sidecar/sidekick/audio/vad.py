"""Streaming voice activity detection with Silero (ONNX) and an utterance segmenter."""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

import numpy as np

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
FRAME = 512  # samples per VAD frame at 16 kHz (32 ms)


class VadModel(Protocol):
    def __call__(self, frame: np.ndarray) -> float: ...
    def reset(self) -> None: ...


class SileroVad:
    """Silero VAD v4/v5 ONNX model wrapper for 16 kHz, 512-sample frames."""

    def __init__(self, model_path: Path) -> None:
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.log_severity_level = 3
        self._session = ort.InferenceSession(str(model_path), sess_options=opts, providers=["CPUExecutionProvider"])
        names = {i.name for i in self._session.get_inputs()}
        self._v5 = "state" in names
        self._context = np.zeros((1, 64), dtype=np.float32)
        self.reset()

    def reset(self) -> None:
        if self._v5:
            self._state = np.zeros((2, 1, 128), dtype=np.float32)
        else:
            self._h = np.zeros((2, 1, 64), dtype=np.float32)
            self._c = np.zeros((2, 1, 64), dtype=np.float32)
        self._context = np.zeros((1, 64), dtype=np.float32)

    def __call__(self, frame: np.ndarray) -> float:
        x = np.asarray(frame, dtype=np.float32).reshape(1, -1)
        if x.shape[1] != FRAME:
            raise ValueError(f"expected {FRAME} samples, got {x.shape[1]}")
        if self._v5:
            inp = np.concatenate([self._context, x], axis=1)
            out, self._state = self._session.run(
                None, {"input": inp, "state": self._state, "sr": np.array(SAMPLE_RATE, dtype=np.int64)}
            )
            self._context = x[:, -64:]
        else:
            out, self._h, self._c = self._session.run(
                None, {"input": x, "h": self._h, "c": self._c, "sr": np.array(SAMPLE_RATE, dtype=np.int64)}
            )
        return float(out[0][0])


class FakeVad:
    """Scripted probabilities for tests."""

    def __init__(self, probs: list[float]) -> None:
        self._probs = list(probs)
        self.i = 0

    def __call__(self, frame: np.ndarray) -> float:
        p = self._probs[self.i] if self.i < len(self._probs) else self._probs[-1]
        self.i += 1
        return p

    def reset(self) -> None:
        self.i = 0


class SegmentEvent(Enum):
    SPEECH_START = "speech_start"
    SPEECH_END = "speech_end"
    TIMEOUT_NO_SPEECH = "timeout_no_speech"
    MAX_DURATION = "max_duration"


@dataclass(slots=True)
class SegmenterConfig:
    threshold: float = 0.5
    silence_timeout_s: float = 1.5
    min_speech_s: float = 0.25
    no_speech_timeout_s: float = 8.0
    max_duration_s: float = 60.0
    pre_roll_s: float = 0.3


class Segmenter:
    """Turns a stream of 512-sample frames into one utterance."""

    def __init__(self, vad: VadModel, config: SegmenterConfig) -> None:
        self._vad = vad
        self.cfg = config
        self._frame_s = FRAME / SAMPLE_RATE
        self._pre = deque(maxlen=max(1, int(config.pre_roll_s / self._frame_s)))
        self._buffer: list[np.ndarray] = []
        self.speaking = False
        self.finished = False
        self._speech_frames = 0
        self._silence_frames = 0
        self._elapsed_frames = 0
        self._speaking_frames = 0
        self.last_prob = 0.0

    @property
    def audio(self) -> np.ndarray:
        if not self._buffer:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(self._buffer).astype(np.float32)

    @property
    def has_speech(self) -> bool:
        return bool(self._buffer)

    def feed(self, frame: np.ndarray) -> SegmentEvent | None:
        if self.finished:
            return None
        frame = np.asarray(frame, dtype=np.float32).reshape(-1)
        prob = self._vad(frame)
        self.last_prob = prob
        self._elapsed_frames += 1
        is_speech = prob >= self.cfg.threshold

        if not self.speaking:
            self._pre.append(frame)
            if is_speech:
                self._speech_frames += 1
                if self._speech_frames * self._frame_s >= self.cfg.min_speech_s:
                    self.speaking = True
                    self._buffer = list(self._pre)
                    self._silence_frames = 0
                    self._speaking_frames = len(self._buffer)
                    return SegmentEvent.SPEECH_START
            else:
                self._speech_frames = 0
            if self._elapsed_frames * self._frame_s >= self.cfg.no_speech_timeout_s:
                self.finished = True
                return SegmentEvent.TIMEOUT_NO_SPEECH
            return None

        self._buffer.append(frame)
        self._speaking_frames += 1
        if is_speech:
            self._silence_frames = 0
        else:
            self._silence_frames += 1
            if self._silence_frames * self._frame_s >= self.cfg.silence_timeout_s:
                self.finished = True
                return SegmentEvent.SPEECH_END
        if self._speaking_frames * self._frame_s >= self.cfg.max_duration_s:
            self.finished = True
            return SegmentEvent.MAX_DURATION
        return None

    def end_now(self) -> bool:
        """Manual stop (second tap). Returns True if there is speech to transcribe."""
        self.finished = True
        return self.has_speech
