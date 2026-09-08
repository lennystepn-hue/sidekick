"""Multiple concurrent sessions, persistence and resume."""

import asyncio

import pytest
from claude_agent_sdk import ResultMessage, SystemMessage, ToolPermissionContext

from sidekick.claude.sessions import SessionManager
from sidekick.config import Settings
from sidekick.db import Database
from sidekick.events import EventBus
from sidekick.state import AppState


class FakeClient:
    instances: list["FakeClient"] = []

    def __init__(self, options):
        self.options = options
        self.queue: asyncio.Queue = asyncio.Queue()
        self.queries: list[str] = []
        self.disconnected = False
        FakeClient.instances.append(self)

    async def connect(self):
        pass

    async def disconnect(self):
        self.disconnected = True

    async def query(self, text):
        self.queries.append(text)

    async def interrupt(self):
        pass

    async def receive_messages(self):
        while True:
            msg = await self.queue.get()
            if msg is None:
                return
            yield msg


def _result(sdk_id):
    return ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=1,
        session_id=sdk_id,
        result="ok",
    )


async def _manager(tmp_path, db=None):
    bus = EventBus()
    bus.bind(asyncio.get_running_loop())
    state = AppState(bus)
    done = []
    mgr = SessionManager(
        lambda: Settings(),
        state,
        bus,
        db or Database(tmp_path / "s.db"),
        on_done=lambda text, s: done.append((s.title, text)),
        client_factory=FakeClient,
    )
    return mgr, state, done


async def _settle(until=None):
    for _ in range(100):
        await asyncio.sleep(0.01)
        if until is None or until():
            break


async def test_two_sessions_run_concurrently_and_switch(tmp_path):
    mgr, state, done = await _manager(tmp_path)
    a = await mgr.create(str(tmp_path))
    b = await mgr.create(str(tmp_path), title="B")
    assert mgr.active_id == b.session_id and state.data.active_session_id == b.session_id
    assert [s["title"] for s in state.data.sessions] == ["B", tmp_path.name]
    await a.send("Baue Feature X mit sehr langem Titel " + "x" * 80)
    assert a.title.startswith("Baue Feature X") and a.title.endswith("…") and len(a.title) <= 60
    assert b.title == "B"  # explicit titles are never overwritten
    await mgr.activate(a.session_id)
    assert state.data.session.id == a.session_id and state.data.session.status == "running"
    # finish A's turn while B is idle: on_done knows which session
    FakeClient.instances[-2].queue.put_nowait(SystemMessage(subtype="init", data={"session_id": "sdk-a"}))
    FakeClient.instances[-2].queue.put_nowait(_result("sdk-a"))
    await _settle(lambda: bool(done))
    assert done == [(a.title, "ok")]
    assert a.sdk_session_id == "sdk-a" and mgr.sdk_ids() == {"sdk-a"}
    summary_a = mgr.summary(a.session_id)
    assert (
        summary_a["status"] == "idle" and summary_a["message_count"] == 1 and summary_a["resumable"] is False
    )
    await mgr.stop_all()
    assert all(s["status"] == "stopped" for s in mgr.summaries())


async def test_resume_after_restart_uses_sdk_session_id(tmp_path):
    db = Database(tmp_path / "p.db")
    mgr, state, _ = await _manager(tmp_path, db)
    s = await mgr.create(str(tmp_path))
    await s.send("hallo")
    FakeClient.instances[-1].queue.put_nowait(_result("sdk-1"))
    await _settle(lambda: s.sdk_session_id == "sdk-1")
    await mgr.stop(s.session_id)
    sid = s.session_id
    assert mgr.summary(sid)["resumable"] is True and mgr.summary(sid)["status"] == "stopped"

    # "restart": a fresh manager on the same database
    mgr2, state2, _ = await _manager(tmp_path, db)
    mgr2.load()
    assert state2.data.active_session_id == sid and state2.data.sessions[0]["resumable"] is True
    resumed = await mgr2.activate(sid)
    assert resumed["status"] == "idle" and resumed["message_count"] == 1
    client = FakeClient.instances[-1]
    assert client.options.resume == "sdk-1" and client.options.cwd == str(tmp_path)
    live = mgr2.get(sid)
    assert live is not None and live.running and live.title == "hallo"
    await live.send("weiter")
    assert db.count_messages(sid) == 2
    await mgr2.stop_all()


async def test_rename_delete_and_pending_lookup(tmp_path):
    mgr, state, _ = await _manager(tmp_path)
    s = await mgr.create(str(tmp_path))
    mgr.rename(s.session_id, "  Mein   Projekt  ")
    assert s.title == "Mein Projekt" and mgr.summary(s.session_id)["title"] == "Mein Projekt"
    await s.send("x")  # auto title must not overwrite a manual one
    assert s.title == "Mein Projekt"
    task = asyncio.create_task(s._can_use_tool("Bash", {"command": "ls"}, ToolPermissionContext()))
    await _settle(lambda: bool(s.pending))
    pid = next(iter(s.pending))
    assert mgr.any_pending() and mgr.summary(s.session_id)["pending"] == 1
    found = mgr.find_pending(pid)
    assert found is not None and found[0] is s
    s.resolve_permission(pid, "allow")
    await task
    assert not mgr.any_pending()
    await mgr.delete(s.session_id)
    assert mgr.summaries() == [] and state.data.active_session_id is None
    with pytest.raises(KeyError):
        await mgr.activate("nope")


async def test_activate_stopped_session_without_sdk_id_only_selects(tmp_path):
    mgr, state, _ = await _manager(tmp_path)
    s = await mgr.create(str(tmp_path))
    await mgr.stop(s.session_id)
    summary = await mgr.activate(s.session_id)
    assert summary["status"] == "stopped" and summary["resumable"] is False
    assert state.data.active_session_id == s.session_id
