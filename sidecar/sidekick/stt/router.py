"""Picks the speech engine from settings and keeps the others cold."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

import numpy as np

from ..config import Settings
from ..state import AppState

log = logging.getLogger(__name__)

ENGINE_LABELS = {"parakeet": "Parakeet", "faster-whisper": "Whisper", "deepgram": "Deepgram"}


class SttRouter:
    def __init__(
        self,
        engines: dict[str, Any],
        settings: Callable[[], Settings],
        state: AppState | None = None,
    ) -> None:
        self._engines = engines
        self._settings = settings
        self._state = state
        self._publish()

    # --- selection -----------------------------------------------------
    @property
    def engine_name(self) -> str:
        return self._settings().stt.engine

    def current(self) -> Any:
        name = self.engine_name
        engine = self._engines.get(name)
        if engine is None:
            label = ENGINE_LABELS.get(name, name)
            raise RuntimeError(
                f"STT-Engine '{label}' ist nicht konfiguriert; bitte Parakeet oder Whisper wählen"
            )
        return engine

    @property
    def loaded(self) -> bool:
        engine = self._engines.get(self.engine_name)
        return bool(getattr(engine, "loaded", False)) if engine is not None else False

    def describe(self) -> tuple[str, str]:
        engine = self._engines.get(self.engine_name)
        if engine is not None and hasattr(engine, "describe"):
            return engine.describe()
        cfg = self._settings().stt
        return self.engine_name, cfg.model if self.engine_name == "faster-whisper" else ""

    def _publish(self) -> None:
        if self._state is None:
            return
        name, model = self.describe()
        self._state.set_models(stt_engine=name, stt_model=model, stt_loaded=self.loaded)

    # --- lifecycle -----------------------------------------------------
    async def preload(self) -> None:
        engine = self.current()
        if hasattr(engine, "preload"):
            await engine.preload()
        self._publish()

    def on_settings_changed(self, old: Settings, new: Settings) -> None:
        for engine in self._engines.values():
            hook = getattr(engine, "on_settings_changed", None)
            if hook is not None:
                hook(old, new)
        if old.stt.engine != new.stt.engine:
            log.info("stt engine switched %s -> %s", old.stt.engine, new.stt.engine)
            self._schedule_preload()
        self._publish()

    def _schedule_preload(self) -> None:
        """Warm the newly selected engine right away instead of on the first tap."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._preload_quietly(), name="stt-preload")

    async def _preload_quietly(self) -> None:
        try:
            await self.preload()
        except Exception as exc:  # noqa: BLE001
            log.warning("stt preload after engine switch failed: %s", exc)
            self._publish()

    async def transcribe(self, audio: np.ndarray, hotwords: list[str] | None = None) -> str:
        engine = self.current()
        text = await engine.transcribe(audio, hotwords)
        self._publish()
        return text
