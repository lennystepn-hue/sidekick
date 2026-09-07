"""Generate Sidekick's UI sounds as 44.1 kHz 16-bit mono WAV files.

Run: `uv run python tools/gen_sounds.py` (from sidecar/). Deterministic, no external deps.
"""

from __future__ import annotations

import sys
import wave
from pathlib import Path

import numpy as np

SR = 44100
OUT = Path(__file__).resolve().parents[1] / "sidekick" / "sounds"


def env(n: int, attack: float, release: float, sustain_level: float = 1.0) -> np.ndarray:
    a = max(1, int(attack * SR))
    r = max(1, int(release * SR))
    e = np.ones(n, dtype=np.float32) * sustain_level
    e[:a] = np.linspace(0, sustain_level, a, dtype=np.float32)
    tail = np.linspace(sustain_level, 0, r, dtype=np.float32)
    if r <= n:
        e[n - r :] = np.minimum(e[n - r :], tail)
    return e


def note(freq: float, dur: float, partials=((1, 1.0), (2, 0.25), (3, 0.08)), attack=0.006, release=None) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n, dtype=np.float32) / SR
    y = np.zeros(n, dtype=np.float32)
    for mult, amp in partials:
        y += amp * np.sin(2 * np.pi * freq * mult * t)
    decay = np.exp(-t * 6.0)
    return y * decay * env(n, attack, release if release is not None else min(0.05, dur / 3))


def sweep(f0: float, f1: float, dur: float) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n, dtype=np.float32) / SR
    freqs = np.linspace(f0, f1, n, dtype=np.float32)
    phase = 2 * np.pi * np.cumsum(freqs) / SR
    y = np.sin(phase) + 0.2 * np.sin(2 * phase)
    return y * env(n, 0.005, 0.04)


def silence(dur: float) -> np.ndarray:
    return np.zeros(int(dur * SR), dtype=np.float32)


def normalize(y: np.ndarray, peak: float = 0.6) -> np.ndarray:
    m = float(np.max(np.abs(y))) or 1.0
    return (y / m * peak).astype(np.float32)


def write(name: str, y: np.ndarray) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    data = (normalize(y) * 32767).astype(np.int16)
    with wave.open(str(OUT / f"{name}.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())


def build_all() -> dict[str, np.ndarray]:
    E5, A5, A4, CS5, C5 = 659.25, 880.0, 440.0, 554.37, 523.25
    return {
        "done": np.concatenate([note(E5, 0.16), note(A5, 0.34)]),
        "needs_input": np.concatenate([note(A4, 0.14), note(CS5, 0.14), note(E5, 0.32)]),
        "error": np.concatenate(
            [note(220.0, 0.16, partials=((1, 1.0), (3, 0.35), (5, 0.15))), silence(0.03),
             note(196.0, 0.18, partials=((1, 1.0), (3, 0.35), (5, 0.15)))]
        ),
        "listening_start": sweep(660, 990, 0.15),
        "listening_stop": sweep(990, 660, 0.15),
        "connected": note(C5, 0.5, partials=((1, 1.0), (2, 0.4), (4, 0.1)), release=0.25),
        "ready_to_paste": note(1320.0, 0.08, partials=((1, 1.0),), attack=0.002, release=0.03),
    }


def main() -> int:
    sounds = build_all()
    for name, y in sounds.items():
        write(name, y)
        print(f"wrote {name}.wav ({len(y) / SR:.2f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
