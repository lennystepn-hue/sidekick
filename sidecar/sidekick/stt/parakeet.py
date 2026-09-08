"""NVIDIA Parakeet TDT 0.6B v3 through onnx-asr: local, CPU, 25 European languages.

About ten times faster than Whisper `small` on the same CPU (RTF ≈ 0.08 measured), no
hotword support (the Haiku cleanup knows the terms instead). The int8 model (~670 MB) is
downloaded once into the app-data models folder. Segments longer than `MAX_SEGMENT_S` are
split at their quietest moments because the transducer is trained on short utterances.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from ..config import Settings
from ..state import AppState

log = logging.getLogger(__name__)

ENGINE = "parakeet"
REPO_ID = "istupakov/parakeet-tdt-0.6b-v3-onnx"
MODEL_FILES = ["config.json", "vocab.txt", "*.int8.onnx"]
SAMPLE_RATE = 16000
MAX_SEGMENT_S = 25.0
MIN_SEGMENT_S = 12.0
FRAME_S = 0.02


def split_points(audio: np.ndarray, sr: int = SAMPLE_RATE) -> list[int]:
    """Sample indices where a long recording is cut: the quietest 20 ms frame between
    MIN_SEGMENT_S and MAX_SEGMENT_S after the previous cut, repeated until the rest fits."""
    n = len(audio)
    max_len, min_len = int(MAX_SEGMENT_S * sr), int(MIN_SEGMENT_S * sr)
    frame = max(1, int(FRAME_S * sr))
    cuts: list[int] = []
    start = 0
    while n - start > max_len:
        lo, hi = start + min_len, start + max_len
        window = audio[lo:hi]
        frames = len(window) // frame
        if frames < 1:
            cut = hi
        else:
            energy = np.square(window[: frames * frame].reshape(frames, frame)).mean(axis=1)
            cut = lo + int(np.argmin(energy)) * frame + frame // 2
        cuts.append(cut)
        start = cut
    return cuts


def split_audio(audio: np.ndarray, sr: int = SAMPLE_RATE) -> list[np.ndarray]:
    cuts = split_points(audio, sr)
    if not cuts:
        return [audio]
    bounds = [0, *cuts, len(audio)]
    return [audio[a:b] for a, b in zip(bounds[:-1], bounds[1:], strict=True) if b > a]


def _to_mono_float32(audio: np.ndarray) -> np.ndarray:
    arr = np.asarray(audio)
    if arr.ndim == 2:
        arr = arr.mean(axis=1)
    if arr.dtype == np.int16:
        arr = arr.astype(np.float32) / 32768.0
    return np.ascontiguousarray(arr, dtype=np.float32)


class ParakeetSTT:
    def __init__(
        self,
        settings: Callable[[], Settings],
        models_dir: Path,
        state: AppState | None = None,
        loader: Callable[..., Any] | None = None,
        downloader: Callable[..., Path] | None = None,
    ) -> None:
        self._settings = settings
        self._models_dir = Path(models_dir)
        self._state = state
        self._loader = loader
        self._downloader = downloader
        self._model: Any = None
        self._model_key = ""
        self._lock = threading.Lock()

    # --- info ----------------------------------------------------------
    @property
    def loaded(self) -> bool:
        return self._model is not None

    def describe(self) -> tuple[str, str]:
        cfg = self._settings().stt
        return ENGINE, f"{cfg.parakeet_model} {cfg.parakeet_quantization}".strip()

    def model_dir(self) -> Path:
        cfg = self._settings().stt
        return self._models_dir / cfg.parakeet_model.replace("/", "_")

    def _set_state(self, **fields: Any) -> None:
        if self._state is not None:
            self._state.set_models(**fields)

    # --- download + load ------------------------------------------------
    def _download(self, target: Path) -> Path:
        if self._downloader is not None:
            return Path(self._downloader(target))
        from huggingface_hub import snapshot_download

        state = self._state

        class _Progress:
            """tqdm stand-in: turns huggingface's per-file progress into state.models."""

            def __init__(self, *a: Any, total: float | None = None, **k: Any) -> None:
                self.total = total or 0
                self.n = 0.0

            def update(self, n: float = 1) -> None:
                self.n += n
                if state is not None and self.total:
                    state.set_models(stt_downloading=True, stt_progress=min(1.0, self.n / self.total))

            def close(self) -> None:
                pass

            def __enter__(self) -> _Progress:
                return self

            def __exit__(self, *a: Any) -> None:
                pass

            def set_description(self, *a: Any, **k: Any) -> None:
                pass

            def refresh(self) -> None:
                pass

        log.info("downloading %s into %s", REPO_ID, target)
        path = snapshot_download(
            repo_id=REPO_ID,
            local_dir=str(target),
            allow_patterns=MODEL_FILES,
            tqdm_class=_Progress,  # type: ignore[arg-type]
        )
        return Path(path)

    def _have_files(self, target: Path) -> bool:
        return (target / "config.json").exists() and any(target.glob("*.int8.onnx"))

    def _load(self) -> Any:
        cfg = self._settings().stt
        key = f"{cfg.parakeet_model}|{cfg.parakeet_quantization}"
        with self._lock:
            if self._model is not None and self._model_key == key:
                return self._model
            target = self.model_dir()
            self._set_state(stt_engine=ENGINE, stt_model=self.describe()[1], stt_loaded=False)
            if not self._have_files(target):
                self._set_state(stt_downloading=True, stt_progress=0.0)
                try:
                    self._download(target)
                finally:
                    self._set_state(stt_downloading=False, stt_progress=0.0)
            if self._loader is not None:
                model = self._loader(cfg.parakeet_model, path=target, quantization=cfg.parakeet_quantization)
            else:
                import onnx_asr

                log.info(
                    "loading parakeet %s (%s) from %s", cfg.parakeet_model, cfg.parakeet_quantization, target
                )
                model = onnx_asr.load_model(
                    cfg.parakeet_model,
                    path=str(target),
                    quantization=cfg.parakeet_quantization or None,
                    providers=["CPUExecutionProvider"],
                )
            self._model = model
            self._model_key = key
            self._set_state(stt_loaded=True)
            log.info("parakeet ready")
            return model

    async def preload(self) -> None:
        await asyncio.to_thread(self._load)

    def on_settings_changed(self, old: Settings, new: Settings) -> None:
        if (
            old.stt.parakeet_model != new.stt.parakeet_model
            or old.stt.parakeet_quantization != new.stt.parakeet_quantization
        ):
            with self._lock:
                self._model = None
                self._model_key = ""
            if new.stt.engine == ENGINE:
                self._set_state(stt_loaded=False, stt_model=self.describe()[1])

    # --- transcription --------------------------------------------------
    def _transcribe_sync(self, audio: np.ndarray, hotwords: list[str] | None) -> str:
        model = self._load()
        wav = _to_mono_float32(audio)
        if len(wav) == 0:
            return ""
        parts: list[str] = []
        for piece in split_audio(wav):
            if len(piece) < int(0.1 * SAMPLE_RATE):
                continue
            out = model.recognize(piece, sample_rate=SAMPLE_RATE)
            text = out if isinstance(out, str) else str(getattr(out, "text", out) or "")
            if text.strip():
                parts.append(text.strip())
        text = " ".join(parts).strip()
        log.info(
            "parakeet: %.1fs audio, %d segment(s), text=%r",
            len(wav) / SAMPLE_RATE,
            len(parts) or 1,
            text[:80],
        )
        return text

    async def transcribe(self, audio: np.ndarray, hotwords: list[str] | None = None) -> str:
        return await asyncio.to_thread(self._transcribe_sync, audio, hotwords)
