import asyncio

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    StreamEvent,
    TextBlock,
    ToolPermissionContext,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from sidekick.claude.answers import build_question_answers, match_option, parse_decision
from sidekick.claude.embedded import EmbeddedSession
from sidekick.config import Settings
from sidekick.db import Database
from sidekick.events import EventBus
from sidekick.state import AppState

# --- answers ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("ja", "allow"),
        ("Ja, mach das.", "allow"),
        ("okay", "allow"),
        ("nein", "deny"),
        ("Nein, nicht ausführen", "deny"),
        ("bitte nicht", "deny"),
        ("immer erlauben", "allow_always"),
        ("ja, und nicht mehr fragen", "allow_always"),
        ("always allow", "allow_always"),
        ("Nimm bitte Postgres statt SQLite", None),
        ("Ich möchte, dass du zuerst die Tests schreibst und dann erst den Code änderst", None),
    ],
)
def test_parse_decision(text, expected):
    assert parse_decision(text) == expected


def test_match_option():
    opts = ["Summary", "Detailed", "Skip for now"]
    assert match_option("summary", opts) == "Summary"
    assert match_option("die zweite", opts) == "Detailed"
    assert match_option("skip", opts) == "Skip for now"
    assert match_option("detailed please", opts) == "Detailed"
    assert match_option("something else entirely", opts) is None


def test_build_question_answers():
    questions = [
        {
            "question": "Welches Format?",
            "header": "Format",
            "options": [{"label": "Kurz"}, {"label": "Ausführlich"}],
            "multiSelect": False,
        },
    ]
    assert build_question_answers(questions, "ausführlich bitte") == {"Welches Format?": "Ausführlich"}
    assert build_question_answers(questions, "mach was du willst") == {
        "Welches Format?": "mach was du willst"
    }
    multi = [
        {
            "question": "Welche Teile?",
            "options": [{"label": "Tests"}, {"label": "Docs"}, {"label": "CI"}],
            "multiSelect": True,
        }
    ]
    assert build_question_answers(multi, "tests und docs") == {"Welche Teile?": "Tests, Docs"}


# --- embedded session with a fake SDK client ----------------------------------------


class FakeClient:
    instances: list["FakeClient"] = []

    def __init__(self, options):
        self.options = options
        self.queue: asyncio.Queue = asyncio.Queue()
        self.queries: list[str] = []
        self.connected = False
        self.interrupted = False
        FakeClient.instances.append(self)

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.connected = False

    async def query(self, text):
        self.queries.append(text)

    async def interrupt(self):
        self.interrupted = True

    async def receive_messages(self):
        while True:
            msg = await self.queue.get()
            if msg is None:
                return
            yield msg


async def _session(tmp_path):
    bus = EventBus()
    bus.bind(asyncio.get_running_loop())
    state = AppState(bus)
    done: list[str] = []
    needs: list[str] = []

    async def on_done(text):
        done.append(text)

    async def on_needs_input(p):
        needs.append(p.kind)

    session = EmbeddedSession(
        lambda: Settings(),
        state,
        bus,
        Database(tmp_path / "t.db"),
        on_done,
        on_needs_input,
        client_factory=FakeClient,
    )
    return session, bus, state, done, needs


async def _drain(bus, type_, count, timeout=2.0):
    for _ in range(int(timeout / 0.01)):
        found = [e for e in bus.history if e.type == type_]
        if len(found) >= count:
            return found
        await asyncio.sleep(0.01)
    raise AssertionError(f"expected {count} {type_} events, got {[e.type for e in bus.history]}")


async def test_session_streams_messages_and_calls_on_done(tmp_path):
    session, bus, state, done, _ = await _session(tmp_path)
    info = await session.start(str(tmp_path), None)
    assert info.mode == "embedded" and state.session.status == "idle"
    client = FakeClient.instances[-1]
    assert client.options.cwd == str(tmp_path) and client.options.permission_mode == "default"
    await session.send("Sag OK")
    assert client.queries == ["Sag OK"] and state.session.status == "running"
    await client.queue.put(
        StreamEvent(uuid="u", session_id="s", event={"type": "message_start", "message": {"id": "m1"}})
    )
    await client.queue.put(
        StreamEvent(
            uuid="u",
            session_id="s",
            event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hal"}},
        )
    )
    await client.queue.put(
        AssistantMessage(
            content=[TextBlock(text="Hallo"), ToolUseBlock(id="t1", name="Bash", input={"command": "ls"})],
            model="m",
        )
    )
    await client.queue.put(
        UserMessage(content=[ToolResultBlock(tool_use_id="t1", content="file.txt", is_error=False)])
    )
    await client.queue.put(AssistantMessage(content=[TextBlock(text="Fertig, eine Datei.")], model="m"))
    await client.queue.put(
        ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id="sdk-1",
            result="Fertig, eine Datei.",
        )
    )
    msgs = await _drain(bus, "message", 4)
    roles = [m.data["role"] for m in msgs]
    assert roles == ["user", "assistant", "tool", "assistant"]
    assert msgs[1].data["blocks"][1]["type"] == "tool_use" and msgs[1].data["stream_id"] == "m1"
    deltas = [e for e in bus.history if e.type == "assistant_delta"]
    assert deltas and deltas[0].data["text"] == "Hal" and deltas[0].data["message_id"] == "m1"
    for _ in range(100):
        await asyncio.sleep(0.01)
        if done:
            break
    assert done == ["Fertig, eine Datei."] and state.session.status == "idle"
    assert session.sdk_session_id == "sdk-1"
    assert len(session._db.list_messages(session.session_id)) == 4
    await session.stop()
    assert state.session.status == "stopped"


async def test_permission_flow_allow_always_and_deny(tmp_path):
    session, bus, state, _, needs = await _session(tmp_path)
    await session.start(str(tmp_path))
    ctx = ToolPermissionContext(suggestions=[{"type": "addRules"}], tool_use_id="tu1", title="Run ls")
    task = asyncio.create_task(session._can_use_tool("Bash", {"command": "ls"}, ctx))
    reqs = await _drain(bus, "permission_request", 1)
    req = reqs[0].data
    assert req["kind"] == "permission" and req["tool_name"] == "Bash" and req["title"] == "Run ls"
    assert (
        state.data.attention == "waiting_input"
        and state.session.status == "waiting"
        and needs == ["permission"]
    )
    assert session.oldest_pending().id == req["id"]
    assert session.resolve_permission(req["id"], "allow_always") is True
    result = await task
    assert isinstance(result, PermissionResultAllow)
    assert result.updated_permissions == [{"type": "addRules"}] and result.updated_input == {"command": "ls"}
    assert state.data.attention == "none" and not session.pending
    assert session.resolve_permission(req["id"], "allow") is False  # already resolved

    task = asyncio.create_task(session._can_use_tool("Write", {"file_path": "x"}, ToolPermissionContext()))
    reqs = await _drain(bus, "permission_request", 2)
    session.resolve_permission(reqs[-1].data["id"], "deny", message="Nope")
    result = await task
    assert isinstance(result, PermissionResultDeny) and result.message == "Nope"
    with pytest.raises(ValueError):
        session.resolve_permission("zzz", "maybe")
    await session.stop()


async def test_ask_user_question_flow(tmp_path):
    session, bus, state, _, needs = await _session(tmp_path)
    await session.start(str(tmp_path))
    q = {
        "questions": [
            {
                "question": "Format?",
                "header": "F",
                "options": [{"label": "Kurz"}, {"label": "Lang"}],
                "multiSelect": False,
            }
        ]
    }
    task = asyncio.create_task(session._can_use_tool("AskUserQuestion", q, ToolPermissionContext()))
    reqs = await _drain(bus, "permission_request", 1)
    assert reqs[0].data["kind"] == "question" and reqs[0].data["questions"][0]["question"] == "Format?"
    session.resolve_permission(reqs[0].data["id"], "allow", answers={"Format?": "Kurz"})
    result = await task
    assert isinstance(result, PermissionResultAllow) and result.updated_input["answers"] == {
        "Format?": "Kurz"
    }
    assert needs == ["question"]
    # stopping the session denies whatever is still pending
    task = asyncio.create_task(session._can_use_tool("Bash", {"command": "rm"}, ToolPermissionContext()))
    await _drain(bus, "permission_request", 2)
    await session.stop()
    assert isinstance(await task, PermissionResultDeny)
