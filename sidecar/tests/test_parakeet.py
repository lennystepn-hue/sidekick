"""Parakeet engine, engine router, cleanup terms."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import numpy as np
import pytest

from sidekick.claude.utility import FakeLLM
from sidekick.config import Settings, merge_settings
from sidekick.events import EventBus
from sidekick.state import AppState
from sidekick.stt.cleanup import Cleaner
from sidekick.stt.parakeet import MAX_SEGMENT_S, ParakeetSTT, split_audio, split_points
from sidekick.stt.router import SttRouter
from sidekick.stt.whisper import FakeSTT

SR = 16000


def _state() -> AppState:
    return AppState(EventBus())


def _fake_dl(target: Path) -> Path:
    target.mkdir(parents=True, exist_ok=True)
    (target / "config.json").write_text(json.dumps({"model_type": "nemo-conformer-tdt"}), encoding="utf-8")
    (target / "vocab.txt").write_text("a\nb\n", encoding="utf-8")
    (target / "encoder-model.int8.onnx").write_bytes(b"x")
    (target / "decoder_joint-model.int8.onnx").write_bytes(b"x")
    return target


class _Model:
    def __init__(self, calls: list) -> None:
        self.calls = calls

    def recognize(self, wav, sample_rate=16000):
        self.calls.append((len(wav), sample_rate))
        return f"seg{len(self.calls)}"


def _settings(engine: str = "parakeet") -> Settings:
    return merge_settings(Settings(), {"stt": {"engine": engine}})


def test_config_accepts_parakeet():
    s = _settings("parakeet")
    assert s.stt.engine == "parakeet"
    assert s.stt.parakeet_model == "nemo-parakeet-tdt-0.6b-v3" and s.stt.parakeet_quantization == "int8"
    assert Settings().stt.engine == "parakeet"  # new installs; saved configs keep their choice


def test_split_points_prefers_silence():
    audio = np.random.default_rng(0).normal(0, 0.3, int(60 * SR)).astype(np.float32)
    for sec in (22.0, 47.0):  # two clearly quiet moments
        audio[int((sec - 0.1) * SR) : int((sec + 0.1) * SR)] = 0.0
    cuts = split_points(audio)
    assert len(cuts) == 2
    assert abs(cuts[0] / SR - 22.0) < 0.15 and abs(cuts[1] / SR - 47.0) < 0.15
    pieces = split_audio(audio)
    assert len(pieces) == 3 and sum(len(p) for p in pieces) == len(audio)
    assert all(len(p) <= MAX_SEGMENT_S * SR for p in pieces)
    assert split_audio(np.zeros(SR, np.float32))[0].shape == (SR,)


async def test_parakeet_downloads_loads_once_and_transcribes(tmp_path):
    state = _state()
    calls: list = []
    loads: list = []
    dl: list = []

    def loader(name, path=None, quantization=None):
        loads.append((name, Path(path).name, quantization))
        return _Model(calls)

    def downloader(target):
        dl.append(target)
        return _fake_dl(target)

    stt = ParakeetSTT(lambda: _settings(), tmp_path, state, loader=loader, downloader=downloader)
    assert not stt.loaded and stt.describe() == ("parakeet", "nemo-parakeet-tdt-0.6b-v3 int8")
    out = await stt.transcribe(np.zeros(SR, np.float32))
    assert out == "seg1" and stt.loaded
    assert calls == [(SR, SR)] and loads == [
        ("nemo-parakeet-tdt-0.6b-v3", "nemo-parakeet-tdt-0.6b-v3", "int8")
    ]
    assert dl == [tmp_path / "nemo-parakeet-tdt-0.6b-v3"]
    models = state.data.models
    assert models.stt_engine == "parakeet" and models.stt_loaded and not models.stt_downloading
    assert models.stt_model == "nemo-parakeet-tdt-0.6b-v3 int8"
    # second call: no new download, no new load; int16 stereo input is normalised
    stereo = np.zeros((SR, 2), np.int16)
    assert await stt.transcribe(stereo) == "seg2" and len(loads) == 1 and len(dl) == 1
    assert calls[-1] == (SR, SR)
    # a 60 s recording is transcribed in pieces and joined
    long = np.random.default_rng(1).normal(0, 0.3, 60 * SR).astype(np.float32)
    long[int(22 * SR) : int(22.2 * SR)] = 0
    long[int(47 * SR) : int(47.2 * SR)] = 0
    out = await stt.transcribe(long)
    assert out == "seg3 seg4 seg5"


async def test_parakeet_settings_change_reloads(tmp_path):
    state = _state()
    cfg = {"s": _settings()}
    loads: list = []
    stt = ParakeetSTT(
        lambda: cfg["s"],
        tmp_path,
        state,
        loader=lambda *a, **k: loads.append(k) or _Model([]),
        downloader=_fake_dl,
    )
    await stt.preload()
    assert stt.loaded and len(loads) == 1
    new = merge_settings(cfg["s"], {"stt": {"parakeet_quantization": ""}})
    stt.on_settings_changed(cfg["s"], new)
    cfg["s"] = new
    assert not stt.loaded and state.data.models.stt_loaded is False
    await stt.preload()
    assert len(loads) == 2 and loads[-1]["quantization"] == ""


async def test_router_selects_engine_and_reports_state():
    state = _state()
    cfg = {"s": _settings("faster-whisper")}
    whisper, parakeet = FakeSTT("whisper sagt"), FakeSTT("parakeet sagt")
    router = SttRouter({"faster-whisper": whisper, "parakeet": parakeet}, lambda: cfg["s"], state)
    assert state.data.models.stt_engine == "faster-whisper" and state.data.models.stt_model == "small"
    assert await router.transcribe(np.zeros(10, np.float32), ["x"]) == "whisper sagt"
    preloaded: list[str] = []

    async def preload() -> None:
        preloaded.append("parakeet")

    parakeet.preload = preload  # type: ignore[attr-defined]
    new = _settings("parakeet")
    router.on_settings_changed(cfg["s"], new)
    cfg["s"] = new
    await asyncio.sleep(0.01)
    assert preloaded == ["parakeet"]  # switching warms the new engine right away
    assert await router.transcribe(np.zeros(10, np.float32)) == "parakeet sagt"
    assert state.data.models.stt_engine == "parakeet" and whisper.calls == [10] and parakeet.calls == [10]
    cfg["s"] = _settings("deepgram")
    with pytest.raises(RuntimeError, match="Deepgram"):
        router.current()
    with pytest.raises(RuntimeError):
        await router.transcribe(np.zeros(10, np.float32))


async def test_cleanup_prompt_lists_known_terms():
    llm = FakeLLM(["FastAPI und pytest"])
    cleaner = Cleaner(llm, lambda: Settings())
    out, ok = await cleaner.clean("fast api und pei test", ["FastAPI", "pytest", " "])
    assert ok and out == "FastAPI und pytest"
    assert llm.calls[-1]["prompt"].startswith("Bekannte Begriffe: FastAPI, pytest\n\nTranskript:")
    await cleaner.clean("ohne begriffe")
    assert llm.calls[-1]["prompt"].startswith("Transkript:")
