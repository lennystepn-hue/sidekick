"""Regression tests for the findings of the first code review."""

import asyncio

import numpy as np
from claude_agent_sdk import ResultMessage, ToolPermissionContext

from sidekick.audio.capture import FakeCapture
from sidekick.audio.devices import AudioDevice
from sidekick.audio.player import Player
from sidekick.audio.router import AudioRouter
from sidekick.audio.sounds import Sounds
from sidekick.audio.vad import FRAME, FakeVad, Segmenter, SegmenterConfig
from sidekick.claude.embedded import EmbeddedSession
from sidekick.claude.hooks import HookHandler
from sidekick.claude.installer import is_sidekick_hook
from sidekick.claude.summarize import Summarizer
from sidekick.claude.utility import FakeLLM, client_key
from sidekick.config import Settings
from sidekick.db import Database
from sidekick.events import EventBus
from sidekick.fakes import FakeAudioBackend, FakeOutput
from sidekick.listen import ListenController
from sidekick.state import AppState
from sidekick.stt.cleanup import Cleaner
from sidekick.stt.whisper import FakeSTT
from sidekick.tts.speaker import FakeEngine, Speaker


def test_client_key_separates_prompts_on_same_model():
    assert client_key("claude-haiku-4-5", "cleanup") != client_key("claude-haiku-4-5", "summary")
    assert client_key("claude-haiku-4-5", "cleanup") == client_key("claude-haiku-4-5", "cleanup")


def test_router_does_not_remember_glasses_hfp_as_previous():
    backend = FakeAudioBackend()
    backend.set_default("rb-hfp")  # Windows made the headset's hands-free endpoint the default
    bus = EventBus()
    state = AppState(bus)
    router = AudioRouter(backend, state, lambda: Settings())
    router.route_to_glasses()
    assert state.data.audio.previous_output_device is None
    assert router.restore() is None and backend.get_default("render").id == "rb-a2dp"


def test_router_restore_failure_clears_state():
    backend = FakeAudioBackend()
    bus = EventBus()
    state = AppState(bus)
    router = AudioRouter(backend, state, lambda: Settings())
    router.route_to_glasses()
    backend.devices = [d for d in backend.devices if d.id != "spk"]  # speakers vanished
    try:
        router.restore()
    except KeyError:
        pass
    assert state.data.audio.routed_to_glasses is False and state.data.audio.previous_output_device is None


class BrokenOutput(FakeOutput):
    def open(self, samplerate, channels, device):
        raise RuntimeError("device gone")


def test_player_reports_playback_error_on_stream_handle():
    player = Player(BrokenOutput())
    handle, finished = player.play_stream()
    handle.write((np.zeros((100, 1), dtype=np.float32), 24000, 1))
    handle.end()
    assert finished.wait(2)
    assert isinstance(handle.error, RuntimeError) and handle.wrote_samples == 0


async def test_speaker_falls_back_when_playback_fails():
    bus = EventBus()
    bus.bind(asyncio.get_running_loop())
    state = AppState(bus)
    speaker = Speaker({"e": FakeEngine("e")}, lambda: ["e"], Player(BrokenOutput()), state, bus)
    speaker.speak("x")
    for _ in range(100):
        await asyncio.sleep(0.02)
        if any(ev.type == "error" for ev in bus.history):
            break
    assert any(ev.type == "error" and "Wiedergabe" in ev.data["message"] for ev in bus.history)
    await speaker.stop()


class DeadClient:
    instances = []

    def __init__(self, options):
        self.options = options
        self.disconnected = False
        self.interrupted = False
        self.queue: asyncio.Queue = asyncio.Queue()
        DeadClient.instances.append(self)

    async def connect(self):
        pass

    async def disconnect(self):
        self.disconnected = True

    async def query(self, text):
        pass

    async def interrupt(self):
        self.interrupted = True

    async def receive_messages(self):
        while True:
            msg = await self.queue.get()
            if msg is None:
                return
            yield msg


async def test_embedded_restart_disconnects_dead_client_and_marks_stopped(tmp_path):
    bus = EventBus()
    bus.bind(asyncio.get_running_loop())
    state = AppState(bus)
    session = EmbeddedSession(lambda: Settings(), state, bus, Database(tmp_path / "t.db"), client_factory=DeadClient)
    await session.start(str(tmp_path))
    first = DeadClient.instances[-1]
    assert session.running and first.options.setting_sources == ["user", "project", "local"]
    await first.queue.put(None)  # CLI exits
    for _ in range(50):
        await asyncio.sleep(0.01)
        if not session.running:
            break
    assert not session.running and session.client_active
    assert state.session.status == "stopped"
    await session.start(str(tmp_path))
    assert first.disconnected is True and DeadClient.instances[-1] is not first
    await session.stop()


async def test_embedded_interrupt_suppresses_done(tmp_path):
    bus = EventBus()
    bus.bind(asyncio.get_running_loop())
    state = AppState(bus)
    done = []

    async def on_done(text):
        done.append(text)

    session = EmbeddedSession(lambda: Settings(), state, bus, Database(tmp_path / "t.db"), on_done, client_factory=DeadClient)
    await session.start(str(tmp_path))
    client = DeadClient.instances[-1]
    await session.send("mach")
    await session.interrupt()
    await client.queue.put(ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1, session_id="s", result="halb"))
    await asyncio.sleep(0.1)
    assert done == [] and state.session.status == "idle"
    await session.send("weiter")
    await client.queue.put(ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1, session_id="s", result="fertig"))
    await asyncio.sleep(0.1)
    assert done == ["fertig"]
    await session.stop()


async def test_embedded_attention_routes_through_refresh(tmp_path):
    bus = EventBus()
    bus.bind(asyncio.get_running_loop())
    state = AppState(bus)
    calls = []
    session = EmbeddedSession(
        lambda: Settings(), state, bus, Database(tmp_path / "t.db"), client_factory=DeadClient, attention_refresh=lambda: calls.append(1)
    )
    await session.start(str(tmp_path))
    task = asyncio.create_task(session._can_use_tool("Bash", {"command": "ls"}, ToolPermissionContext()))
    for _ in range(50):
        await asyncio.sleep(0.01)
        if session.pending:
            break
    session.resolve_permission(next(iter(session.pending)), "allow")
    await task
    assert calls  # attention was recomputed by the hook handler, not blindly cleared
    await session.stop()


class FakeDeliverer:
    def __init__(self):
        self.delivered = []

    async def deliver(self, text, mode):
        self.delivered.append((text, mode))
        return "clipboard"


def _listen(tmp_path, probs, delay=0.3, cleaner_delay=0.0):
    bus = EventBus()
    bus.bind(asyncio.get_running_loop())
    state = AppState(bus)
    settings = Settings()
    settings.stt.review_delay_s = delay
    frames = [np.zeros(FRAME, dtype=np.float32) for _ in range(len(probs))]
    deliverer = FakeDeliverer()

    class SlowLLM(FakeLLM):
        async def complete(self, model, system, prompt):
            await asyncio.sleep(cleaner_delay)
            return await super().complete(model, system, prompt)

    ctl = ListenController(
        capture_factory=lambda: FakeCapture(frames),
        segmenter_factory=lambda: Segmenter(FakeVad(probs), SegmenterConfig(silence_timeout_s=0.2, min_speech_s=0.1, no_speech_timeout_s=0.5)),
        stt=FakeSTT("text"),
        cleaner=Cleaner(SlowLLM(["Text."]), lambda: settings),
        sounds=Sounds(Player(FakeOutput())),
        router=None,
        state=state,
        bus=bus,
        db=Database(tmp_path / "t.db"),
        settings=lambda: settings,
        deliverer=deliverer,
    )
    return ctl, bus, state, deliverer


async def _settle(ctl, state):
    for _ in range(300):
        await asyncio.sleep(0.02)
        if not ctl.busy and state.mode == "idle":
            return
    raise AssertionError(f"pipeline stuck in {state.mode}")


async def test_listen_cancel_during_cleanup_is_honoured(tmp_path):
    ctl, bus, state, deliverer = _listen(tmp_path, [0.9] * 20 + [0.0] * 30, cleaner_delay=0.3)
    await ctl.toggle()
    for _ in range(100):
        await asyncio.sleep(0.01)
        if state.mode == "transcribing":
            break
    await asyncio.sleep(0.05)
    await ctl.cancel()
    await _settle(ctl, state)
    assert deliverer.delivered == []
    statuses = [e.data["status"] for e in bus.history if e.type == "transcript"]
    assert statuses in ([], ["cancelled"])


async def test_tap_during_review_sends_immediately(tmp_path):
    ctl, bus, state, deliverer = _listen(tmp_path, [0.9] * 20 + [0.0] * 30, delay=5.0)
    await ctl.toggle()
    for _ in range(200):
        await asyncio.sleep(0.01)
        if state.mode == "reviewing":
            break
    assert await ctl.toggle() is False
    await _settle(ctl, state)
    assert deliverer.delivered == [("Text.", "main")]


async def test_deepgram_engine_reports_not_configured(tmp_path):
    ctl, bus, state, deliverer = _listen(tmp_path, [0.9] * 5)
    ctl._settings().stt.engine = "deepgram"
    await ctl.toggle()
    await _settle(ctl, state)
    assert any(e.type == "error" and "nicht konfiguriert" in e.data["message"] for e in bus.history)


class RecSounds:
    def __init__(self):
        self.played = []

    def play(self, name, block=False):
        self.played.append(name)


class RecSpeaker:
    def __init__(self):
        self.spoken = []

    def speak(self, text, kind="summary"):
        self.spoken.append((text, kind))


async def test_hooks_ignore_embedded_session_and_dedupe_without_ids(tmp_path):
    bus = EventBus()
    bus.bind(asyncio.get_running_loop())
    state = AppState(bus)
    sounds, speaker = RecSounds(), RecSpeaker()
    h = HookHandler(
        state, bus, Database(tmp_path / "t.db"), sounds, speaker, Summarizer(FakeLLM(["s"]), lambda: Settings()),
        lambda: Settings(), ignore_session_ids=lambda: {"embedded-1"},
    )
    await h.handle("Stop", {"session_id": "embedded-1", "last_assistant_message": "x"})
    assert sounds.played == [] and h.sessions == {}
    perm = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
    await h.handle("PermissionRequest", {"session_id": "ext", **perm, "tool_use_id": "tu9"})
    await h.handle("Notification", {"session_id": "ext", "notification_type": "permission_prompt", "notification_data": perm})
    assert len(speaker.spoken) == 1


def test_is_sidekick_hook_regex():
    assert is_sidekick_hook({"type": "http", "url": "http://127.0.0.1:47821/hook/Stop"})
    assert is_sidekick_hook({"type": "http", "url": "http://localhost:47821/hook"})
    assert not is_sidekick_hook({"type": "http", "url": "http://127.0.0.1:9999/hooks/webhook"})
    assert not is_sidekick_hook({"type": "command", "command": "curl http://127.0.0.1:47821/hook"})


def test_fake_audio_devices_have_hfp_capture():
    devs = FakeAudioBackend().list_devices()
    assert any(isinstance(d, AudioDevice) and d.flow == "capture" and "Hands-Free" in d.name for d in devs)
