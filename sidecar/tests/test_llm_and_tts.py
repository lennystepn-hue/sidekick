import asyncio

import pytest

from sidekick.audio.player import Player
from sidekick.claude.summarize import Summarizer, first_sentences, strip_markdown
from sidekick.claude.utility import FakeLLM, build_options, load_prompt
from sidekick.config import Settings
from sidekick.events import EventBus
from sidekick.fakes import FakeOutput
from sidekick.state import AppState
from sidekick.stt.cleanup import Cleaner, strip_wrapping
from sidekick.tts.speaker import FakeEngine, Speaker

# --- prompts & options ----------------------------------------------------------


def test_prompts_load():
    for name in ("cleanup", "summarize", "btw"):
        assert len(load_prompt(name)) > 100


def test_build_options_disables_tools_and_thinking():
    opts = build_options("claude-haiku-4-5", "sys", None)
    assert opts.model == "claude-haiku-4-5" and opts.tools == [] and opts.max_turns == 1
    assert opts.thinking == {"type": "disabled"} and opts.permission_mode == "dontAsk"
    assert opts.setting_sources == [] and opts.strict_mcp_config is True


# --- cleanup --------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("```\nFastAPI ist gut.\n```", "FastAPI ist gut."),
        ('"FastAPI ist gut."', "FastAPI ist gut."),
        ("Bereinigt: FastAPI ist gut.", "FastAPI ist gut."),
        ("„FastAPI ist gut.“", "FastAPI ist gut."),
    ],
)
def test_strip_wrapping(raw, expected):
    assert strip_wrapping(raw) == expected


async def test_cleaner_uses_llm_and_falls_back():
    llm = FakeLLM(["FastAPI ist gut."])
    cleaner = Cleaner(llm, lambda: Settings())
    text, ok = await cleaner.clean("fast api ist ähm gut")
    assert (text, ok) == ("FastAPI ist gut.", True)
    assert llm.calls[0]["model"] == "claude-haiku-4-5" and "Füllwörter" in llm.calls[0]["system"]
    failing = Cleaner(FakeLLM(error=RuntimeError("down")), lambda: Settings())
    assert await failing.clean("roh text") == ("roh text", False)
    empty = Cleaner(FakeLLM([""]), lambda: Settings())
    assert await empty.clean("roh text") == ("roh text", False)
    s = Settings()
    s.stt.cleanup_enabled = False
    off = Cleaner(FakeLLM(["x"]), lambda: s)
    assert await off.clean("roh") == ("roh", False)


# --- summarizer -----------------------------------------------------------------


def test_strip_markdown_and_first_sentences():
    md = "## Done\n\nI changed `config.py` and **saved** it.\n\n```py\nprint(1)\n```\n- one\n- two"
    plain = strip_markdown(md)
    assert "`" not in plain and "**" not in plain and "##" not in plain and "Codeblock" in plain
    long = "Erster Satz. " * 40
    assert first_sentences(long, 100).endswith(".") and len(first_sentences(long, 100)) <= 101


async def test_summarizer_short_text_is_not_sent_to_llm():
    llm = FakeLLM(["Zusammenfassung."])
    s = Summarizer(llm, lambda: Settings())
    assert await s.summarize("Fertig, Tests grün.") == "Fertig, Tests grün."
    assert llm.calls == []
    long = "Ich habe " + "viele Dinge geändert. " * 30
    assert await s.summarize(long) == "Zusammenfassung."
    assert llm.calls[0]["model"] == "claude-haiku-4-5"
    failing = Summarizer(FakeLLM(error=RuntimeError("x")), lambda: Settings())
    assert (await failing.summarize(long)).startswith("Ich habe viele Dinge")


def test_format_helpers():
    assert Summarizer.format_needs_input("Welche DB?", ["Postgres", "SQLite"]) == (
        "Claude fragt: Welche DB? Optionen: Postgres, SQLite."
    )
    assert Summarizer.format_permission("Bash", {"command": "npm test", "description": "Run tests"}) == (
        "Claude möchte einen Befehl ausführen: Run tests. Erlauben?"
    )
    assert "config.py" in Summarizer.format_permission("Edit", {"file_path": "C:\\p\\config.py"})
    assert "Werkzeug mcp__x" in Summarizer.format_permission("mcp__x", {})


# --- speaker --------------------------------------------------------------------


async def test_speaker_fallback_chain_and_repeat():
    bus = EventBus()
    bus.bind(asyncio.get_running_loop())
    state = AppState(bus)
    out = FakeOutput()
    player = Player(out)
    bad = FakeEngine("elevenlabs", fail=True)
    good = FakeEngine("edge")
    speaker = Speaker({"elevenlabs": bad, "edge": good}, lambda: ["elevenlabs", "edge"], player, state, bus)
    speaker.speak("Hallo Welt")
    for _ in range(100):
        await asyncio.sleep(0.02)
        if good.texts and not speaker.is_speaking and state.mode == "idle":
            break
    assert bad.texts == ["Hallo Welt"] and good.texts == ["Hallo Welt"]
    assert speaker.last_text == "Hallo Welt"
    assert any(ev.type == "spoken" for ev in bus.history)
    speaker.repeat_last()
    for _ in range(100):
        await asyncio.sleep(0.02)
        if len(good.texts) == 2 and not speaker.is_speaking:
            break
    assert good.texts == ["Hallo Welt", "Hallo Welt"]
    await speaker.stop()


async def test_speaker_all_engines_fail_emits_error():
    bus = EventBus()
    bus.bind(asyncio.get_running_loop())
    state = AppState(bus)
    speaker = Speaker({"e": FakeEngine("e", fail=True)}, lambda: ["e"], Player(FakeOutput()), state, bus)
    speaker.speak("x")
    for _ in range(50):
        await asyncio.sleep(0.02)
        if any(ev.type == "error" for ev in bus.history):
            break
    assert any(ev.type == "error" and ev.data["module"] == "tts" for ev in bus.history)
    await speaker.stop()
