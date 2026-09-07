import asyncio
import json

from sidekick.claude.hooks import HookHandler
from sidekick.claude.summarize import Summarizer
from sidekick.claude.transcript import last_assistant_text, recent_messages
from sidekick.claude.utility import FakeLLM
from sidekick.config import Settings
from sidekick.db import Database
from sidekick.events import EventBus
from sidekick.state import AppState


class FakeSounds:
    def __init__(self):
        self.played = []

    def play(self, name, block=False):
        self.played.append(name)


class FakeSpeaker:
    def __init__(self):
        self.spoken = []

    def speak(self, text, kind="summary"):
        self.spoken.append((text, kind))


def _handler(tmp_path, llm=None, embedded_waiting=lambda: False):
    bus = EventBus()
    bus.bind(asyncio.get_running_loop())
    state = AppState(bus)
    sounds, speaker = FakeSounds(), FakeSpeaker()
    summarizer = Summarizer(llm or FakeLLM(["Kurzfassung."]), lambda: Settings())
    h = HookHandler(
        state,
        bus,
        Database(tmp_path / "t.db"),
        sounds,
        speaker,
        summarizer,
        lambda: Settings(),
        embedded_waiting,
    )
    return h, bus, state, sounds, speaker


def _write_transcript(path, entries):
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")


def test_transcript_parsing(tmp_path):
    p = tmp_path / "t.jsonl"
    _write_transcript(
        p,
        [
            {"type": "user", "message": {"role": "user", "content": "Mach X"}},
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Ich mache X."},
                        {"type": "tool_use", "id": "1", "name": "Bash", "input": {}},
                    ],
                },
            },
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": "1", "content": "ok"}],
                },
            },
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "tool_use", "id": "2", "name": "Read", "input": {}}],
                },
            },
            {
                "type": "assistant",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "Fertig mit X."}]},
            },
            {"type": "summary", "summary": "irrelevant"},
            "not json",
        ],
    )
    assert last_assistant_text(p) == "Fertig mit X."
    assert recent_messages(p, 10) == [
        {"role": "user", "text": "Mach X"},
        {"role": "assistant", "text": "Ich mache X."},
        {"role": "assistant", "text": "Fertig mit X."},
    ]
    assert recent_messages(p, 1) == [{"role": "assistant", "text": "Fertig mit X."}]
    assert last_assistant_text(tmp_path / "missing.jsonl") is None
    assert last_assistant_text(None) is None


async def test_stop_hook_plays_done_and_speaks_summary(tmp_path):
    llm = FakeLLM(["Alles erledigt, Tests grün."])
    h, bus, state, sounds, speaker = _handler(tmp_path, llm)
    long_text = "Ich habe " + "sehr viel gemacht. " * 30
    await h.handle(
        "Stop",
        {"session_id": "s1", "cwd": "C:/p", "hook_event_name": "Stop", "last_assistant_message": long_text},
    )
    assert sounds.played == ["done"]
    assert speaker.spoken == [("Alles erledigt, Tests grün.", "done")]
    assert "<<<" in llm.calls[0]["prompt"] and long_text[:40] in llm.calls[0]["prompt"]
    assert state.data.external_sessions == 1 and state.data.attention == "none"
    assert h.list_sessions()[0]["cwd"] == "C:/p"
    assert any(e.type == "hook_event" and e.data["event"] == "Stop" for e in bus.history)
    assert h._db.count_hook_events() == 1


async def test_stop_hook_falls_back_to_transcript(tmp_path):
    p = tmp_path / "t.jsonl"
    _write_transcript(p, [{"type": "assistant", "message": {"content": [{"type": "text", "text": "Kurz."}]}}])
    h, bus, state, sounds, speaker = _handler(tmp_path)
    await h.handle("Stop", {"session_id": "s1", "transcript_path": str(p)})
    assert speaker.spoken == [("Kurz.", "done")]


async def test_notification_permission_and_dedupe_with_permission_request(tmp_path):
    h, bus, state, sounds, speaker = _handler(tmp_path)
    perm = {
        "session_id": "s1",
        "tool_name": "Bash",
        "tool_input": {"command": "npm test"},
        "tool_use_id": "tu1",
    }
    await h.handle("PermissionRequest", perm)
    await h.handle(
        "Notification",
        {
            "session_id": "s1",
            "notification_type": "permission_prompt",
            "notification_data": {
                "tool_name": "Bash",
                "tool_input": {"command": "npm test"},
                "tool_use_id": "tu1",
            },
        },
    )
    assert sounds.played == ["needs_input"]
    assert (
        len(speaker.spoken) == 1
        and "npm test" in speaker.spoken[0][0]
        and speaker.spoken[0][1] == "needs_input"
    )
    assert state.data.attention == "waiting_input"
    await h.handle("UserPromptSubmit", {"session_id": "s1"})
    assert state.data.attention == "none"


async def test_idle_notification_and_ignored_types(tmp_path):
    h, bus, state, sounds, speaker = _handler(tmp_path)
    await h.handle(
        "Notification", {"session_id": "s1", "notification_type": "auth_success", "message": "Logged in"}
    )
    assert speaker.spoken == []
    await h.handle(
        "Notification",
        {
            "session_id": "s1",
            "notification_type": "idle_prompt",
            "message": "Claude is waiting for your input",
        },
    )
    assert sounds.played == ["needs_input"] and speaker.spoken[0][0].startswith("Claude fragt:")
    await h.handle(
        "Notification",
        {
            "session_id": "s1",
            "notification_type": "idle_prompt",
            "message": "Claude is waiting for your input",
        },
    )
    assert len(speaker.spoken) == 1  # duplicate within 5 s


async def test_session_lifecycle_and_embedded_attention(tmp_path):
    waiting = {"v": False}
    h, bus, state, sounds, speaker = _handler(tmp_path, embedded_waiting=lambda: waiting["v"])
    await h.handle("SessionStart", {"session_id": "a", "cwd": "C:/a"})
    await h.handle("SessionStart", {"session_id": "b", "cwd": "C:/b"})
    assert state.data.external_sessions == 2 and h.latest().session_id == "b"
    await h.handle("SessionEnd", {"session_id": "b"})
    assert state.data.external_sessions == 1 and h.latest().session_id == "a"
    waiting["v"] = True
    await h.handle("UserPromptSubmit", {"session_id": "a"})
    assert state.data.attention == "waiting_input"


async def test_unknown_event_is_logged_not_fatal(tmp_path):
    h, bus, state, sounds, speaker = _handler(tmp_path)
    await h.handle("SubagentStop", {"session_id": "s1"})
    await h.handle(None, {"hook_event_name": "PreCompact", "session_id": "s1"})
    assert speaker.spoken == [] and h._db.count_hook_events() == 2
