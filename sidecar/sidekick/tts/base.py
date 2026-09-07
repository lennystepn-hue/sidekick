from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from ..audio.player import PcmChunk


class TtsEngine(Protocol):
    name: str

    def available(self) -> bool: ...

    def synthesize(self, text: str) -> AsyncIterator[PcmChunk]: ...


class TtsError(RuntimeError):
    pass
