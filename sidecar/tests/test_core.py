import asyncio
import threading

from sidekick.db import Database
from sidekick.events import EventBus
from sidekick.state import AppState, SessionInfo


async def test_bus_delivers_to_subscribers():
    bus = EventBus()
    bus.bind(asyncio.get_running_loop())
    q = bus.subscribe()
    bus.publish("x", {"a": 1})
    ev = await asyncio.wait_for(q.get(), 1)
    assert ev.type == "x" and ev.data == {"a": 1}
    bus.unsubscribe(q)
    bus.publish("y")
    assert q.empty()


async def test_bus_publish_from_thread():
    bus = EventBus()
    bus.bind(asyncio.get_running_loop())
    q = bus.subscribe()
    t = threading.Thread(target=lambda: bus.publish("from_thread", {"ok": True}))
    t.start()
    t.join()
    ev = await asyncio.wait_for(q.get(), 1)
    assert ev.type == "from_thread"


async def test_state_update_publishes_and_reports_changes():
    bus = EventBus()
    bus.bind(asyncio.get_running_loop())
    q = bus.subscribe()
    state = AppState(bus)
    assert state.update(mode="listening") == ["mode"]
    assert state.update(mode="listening") == []
    ev = await asyncio.wait_for(q.get(), 1)
    assert ev.type == "state" and ev.data["mode"] == "listening"
    assert q.empty()
    state.update(session=SessionInfo(id="s1", cwd="C:/x", mode="embedded"))
    state.update_session(status="running")
    assert state.to_dict()["session"]["status"] == "running"


def test_db_roundtrip(tmp_path):
    db = Database(tmp_path / "t.db")
    db.add_session("s1", "C:/proj", "embedded")
    m = db.add_message("s1", "user", [{"type": "text", "text": "hi"}])
    assert m["id"] == 1
    db.add_message("s1", "assistant", [{"type": "text", "text": "hello"}])
    msgs = db.list_messages("s1")
    assert [x["role"] for x in msgs] == ["user", "assistant"]
    db.add_transcript("t1", "raw text", "clean text")
    db.mark_transcript("t1", "sent", True, target="clipboard")
    t = db.list_transcripts()[0]
    assert t["sent"] is True and t["status"] == "sent" and t["target"] == "clipboard"
    b = db.add_btw("b1", "s1", "q?", "a.")
    assert db.list_btw()[0]["id"] == b["id"]
    db.close()


def test_hook_events_ring_buffer(tmp_path):
    db = Database(tmp_path / "t.db")
    for i in range(520):
        db.add_hook_event("Stop", "s", {"i": i})
    assert db.count_hook_events() == 500
    assert db.list_hook_events(1)[0]["payload"]["i"] == 519
    db.close()
