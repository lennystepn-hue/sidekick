"""Part B: adopt terminal sessions, defer ("später") permissions, quiet period."""

from __future__ import annotations

import asyncio
import time

import pytest
from claude_agent_sdk import SystemMessage, ToolPermissionContext
from fastapi.testclient import TestClient

from sidekick.app import create_app
from sidekick.claude.answers import parse_decision
from sidekick.claude.sessions import SessionManager
from sidekick.config import Settings
from sidekick.db import Database
from sidekick.events import EventBus
from sidekick.services import build_services
from sidekick.state import AppState
from tests.test_hooks import _handler
from tests.test_sessions import FakeClient, _settle


@pytest.mark.parametrize(
    "text,expected",
    [
        ("später", "defer"),
        ("Später bitte", "defer"),
        ("frag mich nachher", "defer"),
        ("warte", "defer"),
        ("not now", "defer"),
        ("ja", "allow"),
        ("nein", "deny"),
        ("Bitte warte mit dem Deployment bis ich die Konfiguration geprüft habe", None),
    ],
)
def test_parse_decision_defer(text, expected):
    assert parse_decision(text) == expected


async def _manager(tmp_path):
    bus = EventBus()
    bus.bind(asyncio.get_running_loop())
    state = AppState(bus)
    announced: list[str] = []
    events = []
    queue = bus.subscribe()

    async def drain():
        while True:
            events.append(await queue.get())

    task = asyncio.create_task(drain())
    mgr = SessionManager(
        lambda: Settings(),
        state,
        bus,
        Database(tmp_path / "s.db"),
        on_needs_input=lambda pending, s: announced.append(pending.id),
        client_factory=FakeClient,
        scratch_dir=tmp_path / "scratch",
    )
    return mgr, state, announced, events, task


async def test_adopt_forks_terminal_session(tmp_path):
    mgr, state, announced, events, task = await _manager(tmp_path)
    s = await mgr.adopt("sdk-term-1", str(tmp_path))
    client = FakeClient.instances[-1]
    assert client.options.resume == "sdk-term-1" and client.options.fork_session is True
    assert s.kind == "code" and s.title == f"Terminal: {tmp_path.name}" and s.adopted_from == "sdk-term-1"
    assert mgr.active_id == s.session_id and state.data.session.title == s.title
    client.queue.put_nowait(SystemMessage(subtype="init", data={"session_id": "sdk-fork-9"}))
    await _settle(lambda: s.sdk_session_id == "sdk-fork-9")
    assert mgr.summary(s.session_id)["sdk_session_id"] == "sdk-fork-9" and "sdk-fork-9" in mgr.sdk_ids()
    # adopting the same terminal session again returns the running one
    again = await mgr.adopt("sdk-term-1", str(tmp_path))
    assert again is s and len(FakeClient.instances) == len(FakeClient.instances)
    with pytest.raises(ValueError):
        await mgr.adopt("sdk-term-2", str(tmp_path / "missing"))
    # a normal session is never forked
    plain = await mgr.create(str(tmp_path))
    assert FakeClient.instances[-1].options.fork_session is False and plain.adopted_from is None
    await mgr.stop_all()
    task.cancel()


async def test_defer_and_wake_embedded_permission(tmp_path):
    mgr, state, announced, events, task = await _manager(tmp_path)
    s = await mgr.create(str(tmp_path))
    fut = asyncio.create_task(s._can_use_tool("Bash", {"command": "rm -rf build"}, ToolPermissionContext()))
    await _settle(lambda: bool(s.pending))
    pid = next(iter(s.pending))
    assert announced == [pid] and state.data.attention == "waiting_input" and mgr.any_pending()
    assert s.resolve_permission(pid, "defer") is True
    pending = s.pending[pid]
    assert pending.snoozed and 9 * 60 < pending.snoozed_until - time.time() <= 10 * 60
    assert state.data.attention == "none" and not mgr.any_pending() and s.oldest_pending() is None
    await _settle(lambda: any(e.type == "permission_deferred" and e.data["id"] == pid for e in events))
    assert any(e.type == "permission_deferred" and e.data["id"] == pid for e in events)
    assert s.summary()["pending"] == 1 and pending.to_dict()["snoozed_until"] == pending.snoozed_until
    # not yet due: nothing happens
    assert mgr.tick_snoozes() == []
    # presence returns (or the snooze runs out): announced again, attention back
    assert mgr.wake_all_snoozed() == [pid]
    await _settle(lambda: len(announced) == 2)
    assert announced == [pid, pid] and not pending.snoozed and state.data.attention == "waiting_input"
    assert s.oldest_pending() is pending and mgr.any_pending()
    await _settle(lambda: any(e.type == "permission_woken" and e.data["id"] == pid for e in events))
    assert any(e.type == "permission_woken" and e.data["id"] == pid for e in events)
    # explicit "wake" from the UI is silent
    s.resolve_permission(pid, "defer")
    assert s.resolve_permission(pid, "wake") is True and not pending.snoozed
    await asyncio.sleep(0.05)
    assert len(announced) == 2
    with pytest.raises(ValueError):
        s.resolve_permission(pid, "maybe")
    assert s.resolve_permission(pid, "allow") is True
    result = await fut
    assert type(result).__name__ == "PermissionResultAllow"
    await mgr.stop_all()
    task.cancel()


async def test_hooks_defer_adopt_and_quiet(tmp_path):
    h, bus, state, sounds, speaker = _handler(tmp_path)
    perm = {"session_id": "t1", "cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {"command": "ls"}}
    await h.handle("PermissionRequest", perm)
    ext = h.sessions["t1"]
    assert ext.attention and ext.last_prompt and speaker.spoken[-1][1] == "needs_input"
    assert state.data.attention == "waiting_input" and h.waiting() is ext
    spoken_before = len(speaker.spoken)
    # defer: silent, attention off, still listed
    until = h.defer("t1", 10)
    assert until is not None and ext.snoozed and state.data.attention == "none" and h.waiting() is None
    assert h.list_sessions()[0]["snoozed_until"] == until
    assert h.defer("nope", 10) is None
    # the snooze runs out: the stored prompt is read again
    assert h.tick_snoozes(now=until + 1) == ["t1"]
    assert not ext.snoozed and state.data.attention == "waiting_input"
    assert speaker.spoken[-1] == (ext.last_prompt, "needs_input") and len(speaker.spoken) == spoken_before + 1
    # wake without announce
    h.defer("t1", 10)
    assert h.wake("t1") is True and h.wake("t1") is False and len(speaker.spoken) == spoken_before + 1
    # adopted: nothing is spoken any more, attention cleared, latest() ignores it
    h.mark_adopted("t1", "sk-1")
    assert (
        h.list_sessions()[0]["adopted_by"] == "sk-1" and state.data.attention == "none" and h.latest() is None
    )
    await h.handle("Stop", {"session_id": "t1", "last_assistant_message": "Fertig."})
    await h.handle("PermissionRequest", {**perm, "tool_input": {"command": "pwd"}})
    assert len(speaker.spoken) == spoken_before + 1 and ext.last_prompt
    # typing in the terminal again takes the session back
    await h.handle("UserPromptSubmit", {"session_id": "t1"})
    assert ext.adopted_by is None and h.latest() is ext


async def test_hooks_quiet_period_only_plays_tone(tmp_path):
    quiet = {"on": True}
    h, bus, state, sounds, speaker = _handler(tmp_path)
    h._quiet = lambda: quiet["on"]
    await h.handle(
        "Stop", {"session_id": "t2", "cwd": str(tmp_path), "last_assistant_message": "Alles grün."}
    )
    assert sounds.played[-1] == "done" and speaker.spoken == []
    quiet["on"] = False
    await h.handle("Stop", {"session_id": "t2", "last_assistant_message": "Alles grün."})
    assert speaker.spoken and speaker.spoken[-1][1] == "done"
    # questions are always read, quiet or not
    quiet["on"] = True
    await h.handle(
        "Notification", {"session_id": "t2", "notification_type": "idle_prompt", "message": "Weiter?"}
    )
    assert speaker.spoken[-1][1] == "needs_input"


def test_api_adopt_defer_wake_and_quiet_settings(tmp_path):
    services = build_services(tmp_path / "config.toml", tmp_path / "t.db", fake=True, hardware=False)
    services.sessions._client_factory = FakeClient
    spoken: list = []
    services.speaker.speak = lambda text, kind="summary": spoken.append((text, kind))
    with TestClient(create_app(services)) as c:
        assert c.post("/sessions/adopt", json={"session_id": "unknown"}).status_code == 404
        assert (
            c.post("/sessions/adopt", json={"session_id": "x", "cwd": str(tmp_path / "nope")}).status_code
            == 422
        )
        # a terminal session announces itself through hooks, then gets adopted
        assert (
            c.post("/hook/SessionStart", json={"session_id": "term-a", "cwd": str(tmp_path)}).status_code
            == 200
        )
        for _ in range(100):
            if any(e["session_id"] == "term-a" for e in c.get("/sessions/external").json()):
                break
            time.sleep(0.01)
        adopted = c.post("/sessions/adopt", json={"session_id": "term-a"}).json()
        assert adopted["kind"] == "code" and adopted["title"] == f"Terminal: {tmp_path.name}"
        assert (
            adopted["cwd"] == str(tmp_path) and c.get("/state").json()["active_session_id"] == adopted["id"]
        )
        ext = next(e for e in c.get("/sessions/external").json() if e["session_id"] == "term-a")
        assert (
            ext["adopted_by"] == adopted["id"] and ext["snoozed_until"] is None and ext["last_prompt"] == ""
        )
        # defer/wake on a terminal session with an open prompt
        assert c.post("/sessions/external/term-a/defer").status_code == 404
        c.post("/hook/UserPromptSubmit", json={"session_id": "term-a"})  # back in the terminal
        c.post(
            "/hook/PermissionRequest",
            json={"session_id": "term-a", "tool_name": "Bash", "tool_input": {"command": "ls"}},
        )
        for _ in range(100):
            ext = next(e for e in c.get("/sessions/external").json() if e["session_id"] == "term-a")
            if ext["attention"]:
                break
            time.sleep(0.01)
        r = c.post("/sessions/external/term-a/defer")
        assert r.status_code == 200 and r.json()["until"] > time.time()
        assert c.get("/state").json()["attention"] == "none"
        assert c.post("/sessions/external/term-a/wake").json()["ok"] is True
        assert c.post("/sessions/external/term-a/wake").status_code == 404
        # embedded permission: defer + wake through the session route
        live = services.sessions.get(adopted["id"])
        loop = services.bus._loop  # the app's loop (TestClient runs it in a thread)
        fut = asyncio.run_coroutine_threadsafe(
            live._can_use_tool("Bash", {"command": "ls"}, ToolPermissionContext()), loop
        )
        for _ in range(200):
            if live.pending:
                break
            time.sleep(0.01)
        pid = next(iter(live.pending))
        assert c.post(f"/session/permission/{pid}", json={"decision": "defer"}).json()["ok"] is True
        assert c.get("/session").json()["pending"][0]["snoozed_until"] > time.time()
        assert c.post(f"/session/permission/{pid}", json={"decision": "wake"}).json()["ok"] is True
        assert c.get("/session").json()["pending"][0]["snoozed_until"] is None
        assert c.post(f"/session/permission/{pid}", json={"decision": "later"}).status_code == 422
        assert c.post(f"/session/permission/{pid}", json={"decision": "allow"}).json()["ok"] is True
        fut.result(timeout=5)
        # quiet period after own input
        c.put("/settings", json={"tts": {"quiet_after_input_s": 30}, "claude": {"defer_minutes": 3}})
        assert services.settings.claude.defer_minutes == 3
        assert services.quiet_now() is False
        c.post(f"/sessions/{adopted['id']}/send", json={"text": "hallo"})
        assert services.quiet_now() is True
