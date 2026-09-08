"""Service container and wiring.

`build_services()` assembles real Windows backends (or fakes) into one object that the API
routes and background tasks use. Components with `start()`/`stop()` are registered in
`components` and driven by the FastAPI lifespan.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Settings, load_settings
from .db import Database
from .events import EventBus
from .secrets import FakeSecretStore, KeyringSecretStore, SecretStore
from .state import AppState

log = logging.getLogger(__name__)

BATTERY_REFRESH_S = 300


@dataclass
class Services:
    settings_path: Path
    settings: Settings
    bus: EventBus
    state: AppState
    db: Database
    secrets: SecretStore
    fake: bool = False
    hardware: bool = True
    components: list[Any] = field(default_factory=list)
    # wired in build_services(); typed loosely so partial builds (tests) stay cheap
    router: Any = None
    player: Any = None
    sounds: Any = None
    llm: Any = None
    cleaner: Any = None
    summarizer: Any = None
    stt: Any = None
    speaker: Any = None
    presence: Any = None
    bluetooth: Any = None
    bluetooth_doctor: Any = None
    sessions: Any = None
    materializer: Any = None
    hooks: Any = None
    btw: Any = None
    listen: Any = None
    gestures: Any = None
    clipboard: Callable[[str], None] | None = None
    clipboard_get: Callable[[], str | None] | None = None
    _started: bool = False

    @property
    def session(self) -> Any:
        """The active embedded session (or None)."""
        return self.sessions.active if self.sessions is not None else None

    # --- lifecycle -----------------------------------------------------
    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        self.bus.bind(asyncio.get_running_loop())
        for component in self.components:
            starter = getattr(component, "start", None)
            if starter is None:
                continue
            try:
                result = starter()
                if asyncio.iscoroutine(result):
                    await result
            except Exception:  # noqa: BLE001
                log.exception("failed to start %s", type(component).__name__)
                self.bus.publish(
                    "error", {"module": type(component).__name__, "message": "Start fehlgeschlagen"}
                )

    async def stop(self) -> None:
        if not self._started:
            return
        self._started = False
        for component in reversed(self.components):
            stopper = getattr(component, "stop", None)
            if stopper is None:
                continue
            try:
                result = stopper()
                if asyncio.iscoroutine(result):
                    await asyncio.wait_for(result, timeout=5)
            except Exception:  # noqa: BLE001
                log.exception("failed to stop %s", type(component).__name__)
        self.db.close()

    def restore_audio_sync(self) -> None:
        """Best-effort audio restore for hard exits (parent watchdog)."""
        try:
            if (
                self.router is not None
                and self.state.data.audio.routed_to_glasses
                and self.settings.audio.restore_previous_device
            ):
                self.router.restore()
        except Exception:  # noqa: BLE001
            log.exception("audio restore failed")

    # --- settings ------------------------------------------------------
    def apply_settings(self, new: Settings) -> None:
        old = self.settings
        self.settings = new
        for component in self.components:
            hook = getattr(component, "on_settings_changed", None)
            if hook is not None:
                try:
                    hook(old, new)
                except Exception:  # noqa: BLE001
                    log.exception("settings hook failed in %s", type(component).__name__)

    def on_secret_changed(self, name: str) -> None:
        for component in self.components:
            hook = getattr(component, "on_secret_changed", None)
            if hook is not None:
                try:
                    hook(name)
                except Exception:  # noqa: BLE001
                    log.exception("secret hook failed in %s", type(component).__name__)


def build_core(settings_path: Path, db_path: Path | str, fake: bool) -> Services:
    settings = load_settings(settings_path)
    bus = EventBus()
    state = AppState(bus)
    db = Database(db_path)
    secrets: SecretStore = FakeSecretStore() if fake else KeyringSecretStore()
    return Services(
        settings_path=settings_path,
        settings=settings,
        bus=bus,
        state=state,
        db=db,
        secrets=secrets,
        fake=fake,
    )


def _log_task_errors(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        log.error("background task %s failed: %r", task.get_name(), exc)


def spawn(coro: Any, name: str) -> asyncio.Task:
    """create_task with error logging (exceptions in fire-and-forget tasks are otherwise silent)."""
    task = asyncio.create_task(coro, name=name)
    task.add_done_callback(_log_task_errors)
    return task


class _Background:
    """Warm-ups and periodic chores that must not delay startup."""

    def __init__(self, services: Services) -> None:
        self._s = services
        self._tasks: list[asyncio.Task] = []

    def start(self) -> None:
        self._tasks.append(spawn(self._warm_whisper(), "warm-whisper"))
        self._tasks.append(spawn(self._warm_llm(), "warm-llm"))
        self._tasks.append(spawn(self._battery_loop(), "battery"))

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        self._tasks.clear()
        if self._s.llm is not None and hasattr(self._s.llm, "close"):
            await self._s.llm.close()

    async def _warm_whisper(self) -> None:
        stt = self._s.stt
        if stt is None or not hasattr(stt, "preload"):
            return
        try:
            await stt.preload()
        except Exception as exc:  # noqa: BLE001
            log.warning("whisper preload failed: %s", exc)
            self._s.bus.publish(
                "error", {"module": "stt", "message": f"Whisper-Modell konnte nicht geladen werden: {exc}"}
            )

    async def _warm_llm(self) -> None:
        llm = self._s.llm
        if llm is None or not hasattr(llm, "warm_up"):
            return
        cfg = self._s.settings.claude
        targets = [
            (cfg.cleanup_model, self._s.cleaner.system_prompt),
            (cfg.summary_model, self._s.summarizer.system_prompt),
        ]
        await llm.warm_up(targets)

    async def _battery_loop(self) -> None:
        bt = self._s.bluetooth
        if bt is None or not hasattr(bt, "battery"):
            return
        while True:
            await asyncio.sleep(BATTERY_REFRESH_S)
            if not self._s.state.glasses_connected:
                continue
            try:
                level = await asyncio.to_thread(bt.battery, self._s.settings.audio.glasses_device_name, 1)
                self._s.state.update(battery=level)
            except Exception:  # noqa: BLE001
                log.debug("battery refresh failed", exc_info=True)


class RoutedDeliverer:
    """Decide where a finished transcript goes."""

    def __init__(self, services: Services) -> None:
        self._s = services

    async def deliver(self, text: str, mode: str) -> str:
        from .claude.answers import build_question_answers, parse_decision

        s = self._s
        if mode == "btw":
            record = await s.btw.ask(text)
            s.speaker.speak(record["answer"], kind="btw")
            return "btw"
        pending = s.session.oldest_pending() if s.session is not None else None
        if pending is not None:
            if pending.kind == "question":
                answers = build_question_answers(pending.questions, text)
                s.session.resolve_permission(pending.id, "allow", answers=answers)
            else:
                decision = parse_decision(text) or "deny"
                s.session.resolve_permission(
                    pending.id, decision, message=None if decision != "deny" else text
                )
            s.sounds.play("ready_to_paste")
            return "answer"
        if s.session is not None and s.session.running:
            await s.session.send(text)
            return "embedded"
        cfg = s.settings.delivery
        if not cfg.clipboard and not cfg.send_input:
            raise RuntimeError("Kein Zustellziel: Zwischenablage und SendInput sind beide deaktiviert")
        if s.clipboard is None:
            raise RuntimeError("Keine Zwischenablage verfügbar")
        previous = None
        if not cfg.clipboard and s.clipboard_get is not None:
            try:
                previous = await asyncio.to_thread(s.clipboard_get)
            except Exception:  # noqa: BLE001
                previous = None
        await asyncio.to_thread(s.clipboard, text)
        s.sounds.play("ready_to_paste")
        if cfg.send_input and s.hardware:
            from .delivery.sendinput import paste_and_enter

            await asyncio.sleep(0.2)
            await asyncio.to_thread(paste_and_enter)
            if not cfg.clipboard and previous is not None:
                await asyncio.sleep(0.5)
                await asyncio.to_thread(s.clipboard, previous)
            return "sendinput"
        return "clipboard"


def build_services(
    settings_path: Path, db_path: Path | str, fake: bool = False, hardware: bool | None = None
) -> Services:
    """Build the full container.

    fake=True simulates the glasses (Bluetooth always connected, microphone = default
    device). hardware=False (tests) replaces every Windows backend with a fake.
    """
    from .audio import portaudio
    from .audio.capture import FakeCapture, SounddeviceCapture, find_input_device
    from .audio.player import Player, SounddeviceOutput, find_output_device
    from .audio.router import AudioRouter
    from .audio.sounds import Sounds
    from .audio.vad import Segmenter, SegmenterConfig, SileroVad
    from .bluetooth_doctor import BluetoothDoctor
    from .claude.btw import BtwAssistant
    from .claude.embedded import EmbeddedSession, PendingPermission
    from .claude.hooks import HookHandler
    from .claude.materialize import Materializer
    from .claude.sessions import SessionManager
    from .claude.summarize import Summarizer, spoken_reply
    from .claude.transcript import recent_messages
    from .claude.utility import UtilityLLM
    from .gestures.controller import GestureController
    from .gestures.mediakeys import FakeMediaKeyHook
    from .listen import ListenController
    from .paths import bundled_models_dir, models_dir
    from .presence.monitor import FakePresenceBackends, PresenceMonitor
    from .stt.cleanup import Cleaner
    from .stt.whisper import WhisperSTT
    from .tts.edge import EdgeEngine
    from .tts.elevenlabs import ElevenLabsEngine
    from .tts.speaker import Speaker

    services = build_core(settings_path, db_path, fake)
    if hardware is None:
        hardware = sys.platform == "win32"
    services.hardware = hardware
    state, bus, db = services.state, services.bus, services.db

    def settings() -> Settings:
        return services.settings

    # --- audio -------------------------------------------------------------
    if hardware:
        from .audio.devices import PycawBackend

        audio_backend: Any = PycawBackend()
        output_backend: Any = SounddeviceOutput()
    else:
        from .fakes import FakeAudioBackend, FakeOutput

        audio_backend = FakeAudioBackend()
        output_backend = FakeOutput()
    router = AudioRouter(audio_backend, state, settings)

    def output_device() -> int | None:
        """WASAPI index of the endpoint to play on: the glasses while routed, otherwise
        whatever Windows currently uses as default (looked up by name, so device changes
        after start are honoured), else PortAudio's WASAPI default."""
        if not hardware:
            return None
        try:
            name = router.output_device_name() or router.current_default_name()
            idx = find_output_device(name)
            if idx is not None:
                return idx
            return portaudio.wasapi_default_device("output")
        except Exception:  # noqa: BLE001
            return None

    player = Player(
        output_backend, device_resolver=output_device, volume_resolver=lambda: settings().audio.tone_volume
    )
    sounds = Sounds(player)
    services.router, services.player, services.sounds = router, player, sounds

    # --- claude utilities ------------------------------------------------------
    if hardware:
        llm: Any = UtilityLLM(cli_path=settings().claude.cli_path or None)
    else:
        from .claude.utility import FakeLLM

        llm = FakeLLM(["(fake)"])
    cleaner = Cleaner(llm, settings)
    summarizer = Summarizer(llm, settings)
    services.llm, services.cleaner, services.summarizer = llm, cleaner, summarizer

    # --- stt / tts ---------------------------------------------------------------
    if hardware:
        stt: Any = WhisperSTT(settings, models_dir(), state)
    else:
        from .stt.whisper import FakeSTT

        stt = FakeSTT()
    engines = {
        "elevenlabs": ElevenLabsEngine(lambda: services.secrets.get("elevenlabs"), settings),
        "edge": EdgeEngine(settings),
    }

    def engine_order() -> list[str]:
        primary = settings().tts.engine
        return [primary] + [name for name in ("elevenlabs", "edge") if name != primary]

    speaker = Speaker(engines, engine_order, player, state, bus)
    services.stt, services.speaker = stt, speaker

    # --- presence ------------------------------------------------------------------
    if hardware and not fake:
        from .presence.bluetooth import WinBluetoothBackend
        from .presence.idle import WinIdleBackend
        from .presence.session_lock import WinSessionLockBackend

        lock: Any = WinSessionLockBackend()
        idle: Any = WinIdleBackend()
        bluetooth: Any = WinBluetoothBackend()
        services.components.append(lock)
    else:
        fake_backends = FakePresenceBackends(connected=True)
        lock = idle = bluetooth = fake_backends
    services.bluetooth = bluetooth

    async def read_battery() -> None:
        if not hasattr(bluetooth, "battery"):
            return
        try:
            level = await asyncio.to_thread(bluetooth.battery, settings().audio.glasses_device_name, 0)
            state.update(battery=level)
        except Exception:  # noqa: BLE001
            log.debug("battery read failed", exc_info=True)

    async def on_transition(name: str) -> None:
        cfg = settings()
        if name == "glasses_connected" and hardware:
            # PortAudio only enumerates devices once; the glasses' endpoints appeared just now.
            if not player.is_playing and not services.listen.busy and portaudio.open_stream_count() == 0:
                await asyncio.to_thread(portaudio.refresh_devices)
            spawn(read_battery(), "battery-read")
        if name == "became_present" and cfg.presence.auto_connect:
            try:
                await asyncio.to_thread(router.route_to_glasses)
                sounds.play("connected")
            except Exception as exc:  # noqa: BLE001
                log.warning("auto route failed: %s", exc)
                bus.publish("error", {"module": "audio", "message": str(exc)})
        elif name == "became_absent":
            try:
                await asyncio.to_thread(router.restore)
            except Exception as exc:  # noqa: BLE001
                bus.publish(
                    "error", {"module": "audio", "message": f"Audio zurücksetzen fehlgeschlagen: {exc}"}
                )
        if name in ("became_present", "became_absent", "glasses_connected", "glasses_disconnected"):
            state.update(presence_manual=False)
        if name == "glasses_disconnected":
            state.update(battery=None)

    presence = PresenceMonitor(lock, idle, bluetooth, state, settings, on_transition)
    services.presence = presence

    # --- bluetooth doctor -----------------------------------------------------
    doctor = BluetoothDoctor(state)
    services.bluetooth_doctor = doctor

    # --- hooks (created first so the embedded session can route attention through it) ----
    hooks = HookHandler(
        state,
        bus,
        db,
        sounds,
        speaker,
        summarizer,
        settings,
        embedded_waiting=lambda: services.sessions.any_pending() if services.sessions else False,
        ignore_session_ids=lambda: services.sessions.sdk_ids() if services.sessions else set(),
    )
    services.hooks = hooks

    # --- embedded sessions ---------------------------------------------------------
    def _prefix(session: EmbeddedSession) -> str:
        # With several sessions running, say which one is talking.
        return f"{session.title}: " if len(sessions.running()) > 1 and session.title else ""

    async def on_done(text: str, session: EmbeddedSession) -> None:
        if session.is_brainstorm:
            # The partner speaks for itself: short replies, read verbatim, no tone in between.
            if settings().brainstorm.speak_replies and text.strip():
                speaker.speak(_prefix(session) + spoken_reply(text), kind="done")
                if settings().brainstorm.auto_listen:
                    spawn(auto_listen(), "auto-listen")
            return
        sounds.play("done")
        summary = await summarizer.summarize(text)
        speaker.speak(_prefix(session) + summary, kind="done")

    async def auto_listen() -> None:
        """Open the microphone again once the spoken reply has finished (round trip without a tap)."""
        await asyncio.sleep(0.5)
        for _ in range(240):  # up to two minutes of speech
            if not speaker.is_speaking and speaker.queue_empty:
                break
            await asyncio.sleep(0.5)
        if state.glasses_connected and state.mode == "idle" and not services.listen.busy:
            await services.listen.toggle("main")

    async def on_needs_input(pending: PendingPermission, session: EmbeddedSession) -> None:
        sounds.play("needs_input")
        if pending.kind == "question" and pending.questions:
            q = pending.questions[0]
            options = [str(o.get("label", "")) for o in q.get("options", []) if isinstance(o, dict)]
            spoken = summarizer.format_needs_input(str(q.get("question", "")), options)
        else:
            spoken = summarizer.format_permission(
                pending.tool_name, pending.input, pending.description or None
            )
        speaker.speak(_prefix(session) + spoken, kind="needs_input")

    sessions = SessionManager(
        settings,
        state,
        bus,
        db,
        on_done,
        on_needs_input,
        attention_refresh=hooks.refresh_state,
        # tests keep brainstorm scratch folders next to their temporary database
        scratch_dir=None if hardware else Path(str(db_path)).parent / "brainstorms",
    )
    services.sessions = sessions
    sessions.load()
    services.materializer = Materializer(settings, bus, db, sessions, llm)

    # --- btw -----------------------------------------------------------------------------
    def btw_context() -> tuple[str | None, list[dict[str, str]], str | None]:
        n = settings().btw.context_messages
        session = sessions.active
        if session is not None and session.session_id:
            msgs = []
            for m in db.list_messages(session.session_id, n * 2):
                text = "\n".join(b.get("text", "") for b in m["blocks"] if b.get("type") == "text").strip()
                if text and m["role"] in ("user", "assistant"):
                    msgs.append({"role": m["role"], "text": text})
            return session.session_id, msgs[-n:], session.cwd
        latest = hooks.latest()
        if latest is not None:
            return latest.session_id, recent_messages(latest.transcript_path, n), latest.cwd or None
        return None, [], settings().claude.last_cwd or None

    btw = BtwAssistant(llm, db, settings, state, bus, btw_context)
    services.btw = btw

    # --- listen ------------------------------------------------------------------
    vad_model: dict[str, Any] = {}

    def segmenter() -> Segmenter:
        if "vad" not in vad_model:
            vad_model["vad"] = SileroVad(bundled_models_dir() / "silero_vad.onnx")
        vad_model["vad"].reset()
        cfg = settings().stt
        return Segmenter(
            vad_model["vad"],
            SegmenterConfig(
                silence_timeout_s=cfg.silence_timeout_s,
                no_speech_timeout_s=cfg.no_speech_timeout_s,
                max_duration_s=cfg.max_duration_s,
            ),
        )

    def capture() -> Any:
        if not hardware:
            return FakeCapture([])
        eps = router.endpoints()
        device = None
        if eps.capture_hfp is not None:
            device = find_input_device(eps.capture_hfp.name)
        if device is None:
            bus.publish(
                "error",
                {
                    "module": "audio",
                    "message": "Mikrofon der Brille (Hands-Free) nicht gefunden, nutze das Standardmikrofon",
                },
            )
        return SounddeviceCapture(device)

    if hardware:
        from .delivery.clipboard import get_clipboard_text, set_clipboard_text

        services.clipboard = set_clipboard_text
        services.clipboard_get = get_clipboard_text
    else:
        from .delivery.clipboard import FakeClipboard

        fake_clip = FakeClipboard()
        services.clipboard = fake_clip.set
        services.clipboard_get = lambda: fake_clip.text

    listen = ListenController(
        capture, segmenter, stt, cleaner, sounds, router, state, bus, db, settings, RoutedDeliverer(services)
    )
    services.listen = listen

    # --- gestures ----------------------------------------------------------------
    async def act_toggle_listen() -> None:
        if speaker.is_speaking:
            speaker.stop_speaking()
        await listen.toggle("main")

    async def act_btw() -> None:
        if speaker.is_speaking:
            speaker.stop_speaking()
        await listen.toggle("btw")

    def act_repeat() -> None:
        speaker.repeat_last()

    def act_stop() -> None:
        speaker.stop_speaking()

    if hardware:
        from .gestures.mediakeys import WinMediaKeyHook

        hook_factory: Any = WinMediaKeyHook
    else:
        hook_factory = FakeMediaKeyHook
    gestures = GestureController(
        hook_factory,
        settings,
        state,
        bus,
        {
            "toggle_listen": act_toggle_listen,
            "repeat_last": act_repeat,
            "btw": act_btw,
            "stop_speaking": act_stop,
        },
    )
    services.gestures = gestures

    services.components.extend(
        [speaker, presence, gestures, stt, _SettingsRelay(sessions), _Background(services)]
    )
    if hardware:
        services.components.append(doctor)
    services.components.append(_Shutdown(services))
    return services


class _SettingsRelay:
    """Forwards settings changes to the embedded session without exposing its start/stop."""

    def __init__(self, sessions: Any) -> None:
        self._sessions = sessions

    def on_settings_changed(self, old: Settings, new: Settings) -> None:
        self._sessions.on_settings_changed(old, new)


class _Shutdown:
    """Runs last on stop: end the session and restore audio."""

    def __init__(self, services: Services) -> None:
        self._s = services

    async def stop(self) -> None:
        s = self._s
        try:
            if s.sessions is not None:
                await s.sessions.stop_all()
        except Exception:  # noqa: BLE001
            log.exception("session stop failed")
        try:
            if (
                s.router is not None
                and s.state.data.audio.routed_to_glasses
                and s.settings.audio.restore_previous_device
            ):
                await asyncio.to_thread(s.router.restore)
        except Exception:  # noqa: BLE001
            log.exception("audio restore failed")
