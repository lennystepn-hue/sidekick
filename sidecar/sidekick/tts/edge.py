"""Microsoft Edge neural voices via edge-tts (free, MP3 stream decoded with miniaudio)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable

import numpy as np

from ..audio.player import PcmChunk
from ..config import Settings
from .base import TtsError

log = logging.getLogger(__name__)

SAMPLE_RATE = 24000
CHUNK = 4800  # 200 ms


def decode_mp3(data: bytes) -> np.ndarray:
    import miniaudio

    decoded = miniaudio.decode(
        data, output_format=miniaudio.SampleFormat.SIGNED16, nchannels=1, sample_rate=SAMPLE_RATE
    )
    return np.frombuffer(decoded.samples, dtype=np.int16).astype(np.float32) / 32768.0


class EdgeEngine:
    name = "edge"

    def __init__(self, settings: Callable[[], Settings]) -> None:
        self._settings = settings

    def available(self) -> bool:
        return True

    async def synthesize(self, text: str) -> AsyncIterator[PcmChunk]:
        import edge_tts

        voice = self._settings().tts.edge_voice or "de-DE-ConradNeural"
        communicate = edge_tts.Communicate(text, voice)
        buf = bytearray()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buf.extend(chunk["data"])
        if not buf:
            raise TtsError("edge-tts returned no audio")
        import asyncio

        samples = await asyncio.to_thread(decode_mp3, bytes(buf))
        for start in range(0, len(samples), CHUNK):
            yield samples[start : start + CHUNK].reshape(-1, 1), SAMPLE_RATE, 1


if __name__ == "__main__":
    import asyncio
    import sys

    from ..audio.player import Player, SounddeviceOutput
    from ..config import Settings as _Settings

    async def main() -> None:
        player = Player(SounddeviceOutput())
        engine = EdgeEngine(lambda: _Settings())
        handle, done = player.play_stream()
        async for chunk in engine.synthesize(" ".join(sys.argv[1:]) or "Hallo, ich bin Sidekick."):
            handle.write(chunk)
        handle.end()
        done.wait()

    asyncio.run(main())
