"""ElevenLabs streaming TTS as raw 24 kHz PCM (no decoder needed)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable

from ..audio.player import PcmChunk, pcm16_to_float
from ..config import Settings
from .base import TtsError

log = logging.getLogger(__name__)

DEFAULT_VOICE = "21m00Tcm4TlvDq8ikWAM"  # "Rachel", multilingual premade voice
SAMPLE_RATE = 24000


class ElevenLabsEngine:
    name = "elevenlabs"

    def __init__(self, api_key: Callable[[], str | None], settings: Callable[[], Settings]) -> None:
        self._api_key = api_key
        self._settings = settings

    def available(self) -> bool:
        return bool(self._api_key())

    async def synthesize(self, text: str) -> AsyncIterator[PcmChunk]:
        key = self._api_key()
        if not key:
            raise TtsError("ElevenLabs API key not set")
        from elevenlabs.client import AsyncElevenLabs

        cfg = self._settings().tts
        client = AsyncElevenLabs(api_key=key)
        stream = client.text_to_speech.stream(
            voice_id=cfg.voice_id or DEFAULT_VOICE,
            text=text,
            model_id=cfg.elevenlabs_model,
            output_format="pcm_24000",
        )
        leftover = b""
        async for data in stream:
            if not data:
                continue
            buf = leftover + data
            usable = len(buf) - (len(buf) % 2)
            leftover = buf[usable:]
            if usable:
                yield pcm16_to_float(buf[:usable], 1), SAMPLE_RATE, 1
