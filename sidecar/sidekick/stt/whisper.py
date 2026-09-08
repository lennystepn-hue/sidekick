"""faster-whisper on CPU (int8). The model is loaded once and kept warm."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from ..config import Settings
from ..state import AppState

log = logging.getLogger(__name__)


class STT(Protocol):
    async def transcribe(self, audio: np.ndarray, hotwords: list[str] | None = None) -> str: ...


class WhisperSTT:
    def __init__(
        self, settings: Callable[[], Settings], models_dir: Path, state: AppState | None = None
    ) -> None:
        self._settings = settings
        self._models_dir = models_dir
        self._state = state
        self._model: Any = None
        self._model_name = ""
        self._lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def describe(self) -> tuple[str, str]:
        cfg = self._settings().stt
        return "faster-whisper", f"{cfg.model} {cfg.compute_type}".strip()

    def _load(self) -> Any:
        cfg = self._settings().stt
        with self._lock:
            if self._model is not None and self._model_name == cfg.model:
                return self._model
            from faster_whisper import WhisperModel

            log.info("loading whisper model %s (%s)", cfg.model, cfg.compute_type)
            self._model = WhisperModel(
                cfg.model,
                device="cpu",
                compute_type=cfg.compute_type,
                download_root=str(self._models_dir),
            )
            self._model_name = cfg.model
            if self._state is not None:
                self._state.set_models(
                    stt_engine="faster-whisper", stt_model=self.describe()[1], stt_loaded=True
                )
            log.info("whisper model %s ready", cfg.model)
            return self._model

    async def preload(self) -> None:
        await asyncio.to_thread(self._load)

    def on_settings_changed(self, old: Settings, new: Settings) -> None:
        if old.stt.model != new.stt.model or old.stt.compute_type != new.stt.compute_type:
            with self._lock:
                self._model = None
            if self._state is not None and new.stt.engine == "faster-whisper":
                self._state.set_models(stt_loaded=False, stt_model=self.describe()[1])

    def _transcribe_sync(self, audio: np.ndarray, hotwords: list[str] | None) -> str:
        model = self._load()
        cfg = self._settings().stt
        language = cfg.languages[0] if len(cfg.languages) == 1 else None
        segments, info = model.transcribe(
            np.asarray(audio, dtype=np.float32),
            beam_size=5,
            language=language,
            vad_filter=False,
            condition_on_previous_text=False,
            hotwords=", ".join(hotwords) if hotwords else None,
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        log.info("whisper: lang=%s p=%.2f text=%r", info.language, info.language_probability, text[:80])
        return text

    async def transcribe(self, audio: np.ndarray, hotwords: list[str] | None = None) -> str:
        return await asyncio.to_thread(self._transcribe_sync, audio, hotwords)


class FakeSTT:
    def __init__(self, text: str = "hallo welt") -> None:
        self.text = text
        self.calls: list[int] = []

    async def transcribe(self, audio: np.ndarray, hotwords: list[str] | None = None) -> str:
        self.calls.append(len(audio))
        return self.text


if __name__ == "__main__":  # manual check: transcribe a WAV file given on the command line
    import sys
    import wave

    from ..config import Settings as _Settings
    from ..paths import models_dir

    path = Path(sys.argv[1])
    with wave.open(str(path), "rb") as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1, "need 16 kHz mono wav"
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    stt = WhisperSTT(lambda: _Settings(), models_dir())
    print(asyncio.run(stt.transcribe(data, ["Claude", "FastAPI"])))
