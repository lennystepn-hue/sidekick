import asyncio

from sidekick.config import GestureSettings, Settings
from sidekick.events import EventBus
from sidekick.gestures.controller import GestureController
from sidekick.gestures.engine import resolve_action, should_swallow
from sidekick.gestures.mediakeys import FakeMediaKeyHook
from sidekick.presence.monitor import (
    FakePresenceBackends,
    PresenceMonitor,
    PresenceSample,
    PresenceState,
    next_presence,
)
from sidekick.state import AppState

# --- presence state machine -----------------------------------------------------


def _feed(state, samples, threshold=300):
    all_transitions = []
    for s in samples:
        state, t = next_presence(state, s, threshold)
        all_transitions.extend(t)
    return state, all_transitions


def test_present_after_two_good_samples():
    good = PresenceSample(unlocked=True, idle_s=10, glasses_connected=True)
    state, t = _feed(PresenceState(), [good])
    assert state.presence == "unknown" and t == []
    state, t = _feed(state, [good])
    assert state.presence == "present" and state.glasses == "connected"
    assert t == ["glasses_connected", "became_present"]


def test_absent_on_lock_debounced_and_glasses_flap_ignored():
    good = PresenceSample(True, 10, True)
    locked = PresenceSample(False, 10, True)
    state, _ = _feed(PresenceState(), [good, good])
    state, t = _feed(state, [locked])
    assert state.presence == "present" and t == []
    state, t = _feed(state, [locked])
    assert state.presence == "absent" and t == ["became_absent"]
    # single flap of the glasses does not change anything
    flap = PresenceSample(False, 10, False)
    state, t = _feed(state, [flap, locked, locked])
    assert state.glasses == "connected" and t == []
    # real disconnect
    state, t = _feed(state, [flap, flap])
    assert state.glasses == "disconnected" and t == ["glasses_disconnected"]


def test_idle_threshold_makes_absent():
    state, _ = _feed(PresenceState(), [PresenceSample(True, 10, True)] * 2)
    state, t = _feed(state, [PresenceSample(True, 400, True)] * 2, threshold=300)
    assert state.presence == "absent" and t == ["became_absent"]


def test_startup_absent_has_no_transition():
    state, t = _feed(PresenceState(), [PresenceSample(True, 0, False)] * 2)
    assert state.presence == "absent" and state.glasses == "disconnected" and t == []


async def test_monitor_updates_state_and_calls_handler():
    bus = EventBus()
    bus.bind(asyncio.get_running_loop())
    state = AppState(bus)
    backends = FakePresenceBackends()
    seen: list[str] = []

    async def handler(name: str) -> None:
        seen.append(name)

    mon = PresenceMonitor(backends, backends, backends, state, lambda: Settings(), handler)
    await mon.tick()
    await mon.tick()
    assert state.data.presence == "present" and state.data.glasses == "connected"
    assert seen == ["glasses_connected", "became_present"]
    backends.connected = False
    await mon.tick()
    await mon.tick()
    assert state.data.presence == "absent" and seen[-2:] == ["glasses_disconnected", "became_absent"]


# --- gestures -------------------------------------------------------------------


def test_resolve_action_defaults_and_custom():
    g = GestureSettings()
    assert resolve_action("play_pause", g) == ("single_tap", "toggle_listen")
    assert resolve_action("next", g) == ("double_tap", "repeat_last")
    assert resolve_action("prev", g) == ("triple_tap", "btw")
    assert resolve_action("stop", g) == ("hold", "btw")
    assert resolve_action("volume_up", g) == ("unknown", "none")
    custom = GestureSettings(hold="stop_speaking", single_tap="none")
    assert resolve_action("stop", custom) == ("hold", "stop_speaking")
    assert resolve_action("play_pause", custom) == ("single_tap", "none")


def test_should_swallow():
    g = GestureSettings()
    assert should_swallow(g, glasses_connected=True) is True
    assert should_swallow(g, glasses_connected=False) is False
    assert should_swallow(GestureSettings(capture_always=True), False) is True
    assert should_swallow(GestureSettings(capture_media_keys=False), True) is False


async def test_controller_dispatches_actions_and_logs():
    bus = EventBus()
    bus.bind(asyncio.get_running_loop())
    state = AppState(bus)
    calls: list[str] = []

    async def toggle() -> None:
        calls.append("toggle")

    async def repeat() -> None:
        calls.append("repeat")

    ctl = GestureController(
        FakeMediaKeyHook, lambda: Settings(), state, bus, {"toggle_listen": toggle, "repeat_last": repeat}
    )
    ctl.start()
    hook: FakeMediaKeyHook = ctl.hook  # type: ignore[assignment]
    assert hook.press("play_pause") is False  # glasses not connected -> not swallowed
    state.update(glasses="connected")
    assert hook.press("next") is True
    await asyncio.sleep(0.05)
    assert calls == ["toggle", "repeat"]
    entries = ctl.entries()
    assert [e["key"] for e in entries] == ["play_pause", "next"]
    assert entries[1]["swallowed"] is True and entries[1]["action"] == "repeat_last"
    assert [ev.type for ev in bus.history if ev.type == "media_key"] == ["media_key", "media_key"]
    ctl.stop()
