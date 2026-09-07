"""Named UI sounds (see tools/gen_sounds.py)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal, get_args

from ..paths import sounds_dir
from .player import Player

log = logging.getLogger(__name__)

SoundName = Literal[
    "done", "needs_input", "error", "listening_start", "listening_stop", "connected", "ready_to_paste"
]
SOUND_NAMES: tuple[str, ...] = get_args(SoundName)


class Sounds:
    def __init__(self, player: Player, directory: Path | None = None) -> None:
        self._player = player
        self._dir = directory or sounds_dir()
        self.played: list[str] = []

    def path(self, name: str) -> Path:
        if name not in SOUND_NAMES:
            raise KeyError(name)
        return self._dir / f"{name}.wav"

    def play(self, name: str, block: bool = False) -> None:
        path = self.path(name)
        self.played.append(name)
        if not path.exists():
            log.warning("sound file missing: %s", path)
            return
        self._player.play_wav(path, block=block)
