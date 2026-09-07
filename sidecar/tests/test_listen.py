import asyncio

import numpy as np

from sidekick.audio.capture import FakeCapture
from sidekick.audio.player import Player
from sidekick.audio.sounds import Sounds
from sidekick.audio.vad import FRAME, FakeVad, Segmenter, SegmenterConfig
from sidekick.claude.utility import FakeLLM
from sidekick.config import Settings
from sidekick.db import Database
from sidekick.events import EventBus
from sidekick.fakes import FakeOutput
from sidekick.listen import ListenController
from sidekick.state import AppState
from sidekick.stt.cleanup import Cleaner
from sidekick.stt.whisper import FakeSTT


class FakeDeliverer:
    def __init__(self, fail=False):
        self.delivered: list[tuple[str, str]] = []
        self.fail = fail

    async def deliver(self, text: str, mode: str) -> str:
        if self.fail:
            raise RuntimeError("no target")
        self.delivered.append((text, mode))
        return "clipboard"


def _controller(tmp_path, probs, settings=None, deliverer=None, stt_text="fast api ist gut", max_duration_s=60.0):
    bus = EventBus()
    bus.bind(asyncio.get_running_loop())
    state = AppState(bus)
    settings = settings or Settings()
    settings.stt.review_delay_s = 0.3
    frames = [np.zeros(FRAME, dtype=np.float32) for _ in range(len(probs))]
    deliverer = deliverer or FakeDeliverer()
    ctl = ListenController(
        capture_factory=lambda: FakeCapture(frames),
        segmenter_factory=lambda: Segmenter(
            FakeVad(probs),
            SegmenterConfig(
                silence_timeout_s=0.2, min_speech_s=0.1, no_speech_timeout_s=0.5, max_duration_s=max_duration_s
            ),
        ),
        stt=FakeSTT(stt_text),
        cleaner=Cleaner(FakeLLM(["FastAPI ist gut."]), lambda: settings),
        sounds=Sounds(Player(FakeOutput())),
        router=None,
        state=state,
        bus=bus,
        db=Database(tmp_path / "t.db"),
        settings=lambda: settings,
        deliverer=deliverer,
    )
    return ctl, bus, state, deliverer


def _events(bus, type_):
    return [e.data for e in bus.history if e.type == type_]


async def _wait_idle(ctl, state, timeout=5.0):
    for _ in range(int(timeout / 0.02)):
        await asyncio.sleep(0.02)
        if not ctl.busy and state.mode == "idle":
            return
    raise AssertionError(f"pipeline did not finish, mode={state.mode}")


async def test_full_pipeline_sends_after_review(tmp_path):
    probs = [0.0] * 5 + [0.9] * 20 + [0.0] * 30
    ctl, bus, state, deliverer = _controller(tmp_path, probs)
    assert await ctl.toggle("main") is True
    await _wait_idle(ctl, state)
    ts = _events(bus, "transcript")
    assert [t["status"] for t in ts] == ["reviewing", "sent"]
    assert ts[-1]["cleaned"] == "FastAPI ist gut." and ts[-1]["raw"] == "fast api ist gut"
    assert ts[-1]["target"] == "clipboard" and ts[-1]["sent"] is True
    assert deliverer.delivered == [("FastAPI ist gut.", "main")]
    modes = [e.data["mode"] for e in bus.history if e.type == "state"]
    assert modes[:2] == ["listening", "transcribing"] and "reviewing" in modes
    assert ctl._sounds.played[:2] == ["listening_start", "listening_stop"]


async def test_cancel_during_review(tmp_path):
    probs = [0.9] * 20 + [0.0] * 30
    ctl, bus, state, deliverer = _controller(tmp_path, probs)
    await ctl.toggle()
    for _ in range(200):
        await asyncio.sleep(0.01)
        if _events(bus, "transcript"):
            break
    tid = _events(bus, "transcript")[0]["id"]
    assert ctl.cancel_review(tid) is True
    await _wait_idle(ctl, state)
    assert [t["status"] for t in _events(bus, "transcript")] == ["reviewing", "cancelled"]
    assert deliverer.delivered == []


async def test_send_now_with_edited_text(tmp_path):
    probs = [0.9] * 20 + [0.0] * 30
    ctl, bus, state, deliverer = _controller(tmp_path, probs)
    await ctl.toggle("btw")
    for _ in range(200):
        await asyncio.sleep(0.01)
        if _events(bus, "transcript"):
            break
    tid = _events(bus, "transcript")[0]["id"]
    assert ctl.send_now(tid, "Edited text") is True
    await _wait_idle(ctl, state)
    assert deliverer.delivered == [("Edited text", "btw")]
    assert _events(bus, "transcript")[-1]["cleaned"] == "Edited text"
    modes = [e.data["mode"] for e in bus.history if e.type == "state"]
    assert modes[0] == "btw_listening"


async def test_no_speech_plays_error(tmp_path):
    ctl, bus, state, deliverer = _controller(tmp_path, [0.0] * 40)
    await ctl.toggle()
    await _wait_idle(ctl, state)
    assert _events(bus, "transcript") == []
    assert "error" in ctl._sounds.played
    assert any(e.type == "error" for e in bus.history)


async def test_manual_stop_by_second_toggle(tmp_path):
    # speech never ends by itself (always 0.9); the second tap must stop and transcribe.
    # FakeCapture produces frames without real-time pacing, so max_duration must be huge here.
    ctl, bus, state, deliverer = _controller(tmp_path, [0.9] * 5, max_duration_s=1e9)
    await ctl.toggle()
    await asyncio.sleep(0.15)
    assert ctl.recording is True
    assert await ctl.toggle() is False
    await _wait_idle(ctl, state)
    assert deliverer.delivered and _events(bus, "transcript")[-1]["status"] == "sent"


async def test_delivery_failure_marks_failed(tmp_path):
    probs = [0.9] * 20 + [0.0] * 30
    ctl, bus, state, _ = _controller(tmp_path, probs, deliverer=FakeDeliverer(fail=True))
    await ctl.toggle()
    await _wait_idle(ctl, state)
    assert _events(bus, "transcript")[-1]["status"] == "failed"
    assert any(e.type == "error" and e.data["module"] == "delivery" for e in bus.history)
