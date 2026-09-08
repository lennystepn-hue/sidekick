"""Brainstorm mode: idea-state parsing, brainstorm sessions, materialization, API."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from claude_agent_sdk import AssistantMessage, StreamEvent, TextBlock
from fastapi.testclient import TestClient

from sidekick.app import create_app
from sidekick.claude.idea import IdeaState, StreamFilter, slugify, split_idea_block
from sidekick.claude.materialize import DOC_SPECS, MaterializeOptions, Materializer, strip_fence
from sidekick.claude.sessions import SessionManager
from sidekick.claude.summarize import spoken_reply
from sidekick.claude.utility import FakeLLM
from sidekick.config import Settings
from sidekick.db import Database
from sidekick.events import EventBus
from sidekick.services import build_services
from sidekick.state import AppState
from tests.test_sessions import FakeClient, _result, _settle

STATE = {
    "title": "Pflanzen-Butler",
    "one_liner": "Erinnert ans Gießen",
    "problem": "Pflanzen vertrocknen",
    "users": "Leute mit vielen Pflanzen",
    "core_features": ["Erinnerung", "Pflanzenliste"],
    "non_goals": ["Sensorik"],
    "stack": ["Tauri", "Vue"],
    "decisions": ["Windows only"],
    "open_questions": ["Cloud-Sync?"],
    "next_steps": [],
    "readiness": 85,
    "ready": True,
}


def _block(state=STATE, fenced=False) -> str:
    body = json.dumps(state, ensure_ascii=False)
    if fenced:
        body = f"```json\n{body}\n```"
    return f"<idea-state>\n{body}\n</idea-state>"


# --- parsing -----------------------------------------------------------------------


def test_split_idea_block_variants():
    visible, data = split_idea_block("Klingt gut. Welche Plattform?\n\n" + _block())
    assert visible == "Klingt gut. Welche Plattform?" and data["title"] == "Pflanzen-Butler"
    visible, data = split_idea_block("Ohne Block.")
    assert visible == "Ohne Block." and data is None
    visible, data = split_idea_block("Text " + _block(fenced=True) + " Nachsatz")
    assert visible == "Text\n\nNachsatz" and data["readiness"] == 85
    # missing closing tag (truncated) and trailing comma still parse
    visible, data = split_idea_block('Hi <idea-state>{"title": "X", "readiness": 10,}')
    assert visible == "Hi" and data == {"title": "X", "readiness": 10}
    visible, data = split_idea_block("Kaputt <idea-state> kein json </idea-state>")
    assert visible == "Kaputt" and data is None


def test_idea_state_from_dict_is_tolerant():
    idea = IdeaState.from_dict(
        {"title": "  A  B ", "core_features": "eins", "readiness": "120", "stack": None}
    )
    assert idea.title == "A B" and idea.core_features == ["eins"] and idea.readiness == 100
    assert idea.ready is True and idea.stack == []
    assert IdeaState.from_dict({"readiness": 79}).ready is False
    assert "Nutzer" in IdeaState.from_dict({"problem": "p"}).gaps()
    assert IdeaState.from_dict({}).is_empty


def test_stream_filter_hides_block_even_when_tag_is_split():
    f = StreamFilter()
    out = f.feed("Hallo ") + f.feed("Welt <id") + f.feed("ea-st") + f.feed("ate>{...}") + f.feed("more")
    assert out == "Hallo Welt " and f.muted
    g = StreamFilter()
    assert g.feed("a < b") + g.feed(" und <i") + g.flush() == "a < b und <i"


def test_slugify_and_fence_and_spoken():
    assert slugify("Grüße für Österreich! v2") == "gruesse-fuer-oesterreich-v2"
    assert slugify("???") == "projekt"
    assert strip_fence("```markdown\n# Hi\n```") == "# Hi"
    assert strip_fence("# Hi") == "# Hi"
    long = "Satz eins. " * 200
    spoken = spoken_reply("**Fett** und `code`\n\n- Punkt")
    assert spoken == "Fett und code Punkt"
    assert spoken_reply(long).endswith(".") and len(spoken_reply(long)) <= 900


# --- sessions ---------------------------------------------------------------------


async def _manager(tmp_path, db=None, settings=None):
    bus = EventBus()
    bus.bind(asyncio.get_running_loop())
    state = AppState(bus)
    done = []
    events = []
    queue = bus.subscribe()

    async def drain():
        while True:
            ev = await queue.get()
            events.append(ev)

    task = asyncio.create_task(drain())
    mgr = SessionManager(
        lambda: settings or Settings(),
        state,
        bus,
        db or Database(tmp_path / "s.db"),
        on_done=lambda text, s: done.append((s.kind, text)),
        client_factory=FakeClient,
        scratch_dir=tmp_path / "scratch",
    )
    return mgr, state, done, events, task


def _delta(text):
    return StreamEvent(
        uuid="u",
        session_id="s",
        event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}},
    )


async def test_brainstorm_session_profile_and_idea_state(tmp_path):
    mgr, state, done, events, task = await _manager(tmp_path)
    s = await mgr.create(None, kind="brainstorm")
    client = FakeClient.instances[-1]
    assert s.is_brainstorm and s.title == "Brainstorm" and Path(s.cwd).is_dir()  # noqa: ASYNC240
    assert Path(s.cwd).parent == tmp_path / "scratch"
    opts = client.options
    assert opts.tools == [] and opts.permission_mode == "dontAsk" and opts.setting_sources == []
    assert "Brainstorm-Partner" in opts.system_prompt and opts.model == "claude-opus-5"
    assert state.data.session.kind == "brainstorm" and mgr.summary(s.session_id)["kind"] == "brainstorm"

    await s.send("Ich will eine App die ans Gießen erinnert")
    assert s.title == "Brainstorm"  # no title from the first sentence; the idea title comes later
    client.queue.put_nowait(
        StreamEvent(uuid="u", session_id="s", event={"type": "message_start", "message": {"id": "m1"}})
    )
    client.queue.put_nowait(_delta("Klingt gut. "))
    client.queue.put_nowait(_delta("Welche Plattform?\n\n<idea-st"))
    client.queue.put_nowait(_delta('ate>\n{"title": "Pflanzen'))
    client.queue.put_nowait(
        AssistantMessage(content=[TextBlock(text="Klingt gut. Welche Plattform?\n\n" + _block())], model="m")
    )
    client.queue.put_nowait(StreamEvent(uuid="u", session_id="s", event={"type": "message_stop"}))
    client.queue.put_nowait(_result("sdk-b"))
    await _settle(lambda: bool(done))
    deltas = "".join(e.data["text"] for e in events if e.type == "assistant_delta")
    assert deltas == "Klingt gut. Welche Plattform?\n\n"
    stored = mgr.messages(s.session_id)
    assert (
        stored[-1]["role"] == "assistant"
        and stored[-1]["blocks"][0]["text"] == "Klingt gut. Welche Plattform?"
    )
    assert done == [("brainstorm", "Klingt gut. Welche Plattform?")]
    idea_events = [e for e in events if e.type == "idea_state"]
    assert idea_events and idea_events[-1].data["state"]["readiness"] == 85
    assert s.idea is not None and s.idea.ready and s.title == "Pflanzen-Butler"
    summary = mgr.summary(s.session_id)
    assert summary["idea"]["title"] == "Pflanzen-Butler" and summary["title"] == "Pflanzen-Butler"

    # a manual rename sticks even when the idea title changes again
    mgr.rename(s.session_id, "Mein Butler")
    client.queue.put_nowait(
        AssistantMessage(content=[TextBlock(text="Ok.\n" + _block({**STATE, "title": "Neu"}))], model="m")
    )
    await _settle(lambda: s.idea.title == "Neu")
    assert s.title == "Mein Butler"
    # a degenerate block never wipes the state
    client.queue.put_nowait(
        AssistantMessage(content=[TextBlock(text="Hm.\n<idea-state>{}</idea-state>")], model="m")
    )
    await _settle(lambda: mgr.messages(s.session_id)[-1]["blocks"][0]["text"] == "Hm.")
    assert s.idea.title == "Neu"
    await mgr.stop_all()
    task.cancel()


async def test_brainstorm_resume_restores_kind_idea_and_project(tmp_path):
    db = Database(tmp_path / "p.db")
    mgr, state, done, events, task = await _manager(tmp_path, db)
    s = await mgr.create(None, kind="brainstorm")
    FakeClient.instances[-1].queue.put_nowait(
        AssistantMessage(content=[TextBlock(text="x\n" + _block())], model="m")
    )
    FakeClient.instances[-1].queue.put_nowait(_result("sdk-bs"))
    await _settle(lambda: s.sdk_session_id == "sdk-bs" and s.idea is not None)
    mgr.set_project_path(s.session_id, str(tmp_path / "proj"))
    await mgr.stop_all()
    task.cancel()

    mgr2, state2, _, _, task2 = await _manager(tmp_path, db)
    mgr2.load()
    row = state2.data.sessions[0]
    assert row["kind"] == "brainstorm" and row["idea"]["title"] == "Pflanzen-Butler"
    assert row["project_path"] == str(tmp_path / "proj") and state2.data.session.kind == "brainstorm"
    resumed = mgr2.get((await mgr2.activate(s.session_id))["id"])
    assert resumed.is_brainstorm and resumed.idea.title == "Pflanzen-Butler"
    assert resumed.project_path == str(tmp_path / "proj") and resumed.title == "Pflanzen-Butler"
    assert FakeClient.instances[-1].options.resume == "sdk-bs"
    assert "Brainstorm-Partner" in FakeClient.instances[-1].options.system_prompt
    await mgr2.stop_all()
    task2.cancel()


# --- materialization ------------------------------------------------------------------


def _fake_git(calls):
    def run(args, cwd):
        calls.append((args[0] if args[0] != "-c" else "commit", Path(cwd)))
        return 0, ""

    return run


async def test_materialize_writes_docs_git_and_starts_session(tmp_path):
    settings = Settings()
    settings.projects.base_dir = str(tmp_path / "Projects")
    mgr, state, done, events, task = await _manager(tmp_path, settings=settings)
    s = await mgr.create(None, kind="brainstorm")
    await s.send("Meine Idee")
    FakeClient.instances[-1].queue.put_nowait(
        AssistantMessage(content=[TextBlock(text="Super.\n" + _block())], model="m")
    )
    await _settle(lambda: s.idea is not None)
    llm = FakeLLM(["fallback"])
    llm.documents = {spec.path: f"# {spec.path}\n\nInhalt" for spec in DOC_SPECS}
    llm.documents["docs/SPEC.md"] = "```markdown\n# Spec\n\nfenced\n```"
    llm.generate_errors["docs/PLAN.md"] = RuntimeError("flaky")  # fails once, retry succeeds
    git_calls = []
    mat = Materializer(lambda: settings, mgr._bus, mgr._db, mgr, llm, git_runner=_fake_git(git_calls))
    job = await mat.start(s.session_id, MaterializeOptions())
    with pytest.raises(RuntimeError):
        await mat.start(s.session_id)  # one job at a time
    job = await mat.wait(s.session_id)
    assert job.status == "done" and job.warnings == [] and job.project_path.endswith("pflanzen-butler")
    project = Path(job.project_path)
    assert (project / "README.md").read_text(encoding="utf-8").startswith("# README.md")
    assert (project / "docs" / "SPEC.md").read_text(encoding="utf-8") == "# Spec\n\nfenced\n"
    assert (project / "docs" / "PLAN.md").exists() and (project / ".gitignore").exists()
    brainstorm_md = (project / "docs" / "BRAINSTORM.md").read_text(encoding="utf-8")
    assert "Entwickler: Meine Idee" in brainstorm_md and "Partner: Super." in brainstorm_md
    kickoff = (project / "docs" / "KICKOFF.md").read_text(encoding="utf-8")
    assert "Meilenstein 1" in kickoff and str(project) in kickoff
    assert [c[0] for c in git_calls] == ["init", "add", "commit"] and git_calls[0][1] == project
    # docs prompt carries idea and transcript, docs model is Opus
    gen = [c for c in llm.calls if c.get("generate")]
    assert len(gen) == len(DOC_SPECS) + 1 and all(c["model"] == "claude-opus-5" for c in gen)
    assert "Pflanzen-Butler" in gen[0]["prompt"] and "Entwickler: Meine Idee" in gen[0]["prompt"]
    # the brainstorm knows its project, a code session runs in it with the kickoff prompt
    assert s.project_path == str(project) and mgr.summary(s.session_id)["project_path"] == str(project)
    code = mgr.get(job.code_session_id)
    assert (
        code is not None and code.kind == "code" and code.cwd == str(project) and code.title == project.name
    )
    assert FakeClient.instances[-1].queries[0].startswith(f"Du arbeitest im neuen Projekt {project.name}")
    assert mgr.active_id == code.session_id
    progress = [e.data for e in events if e.type == "materialize_progress"]
    assert progress[0]["label"] == "Ordner anlegen" and progress[-1]["status"] == "done"
    assert (
        progress[-1]["code_session_id"] == code.session_id and progress[-1]["step"] == progress[-1]["total"]
    )
    assert mat.files(str(project)) == [
        "CLAUDE.md",
        "README.md",
        "docs/BRAINSTORM.md",
        "docs/DECISIONS.md",
        "docs/KICKOFF.md",
        "docs/OPEN_QUESTIONS.md",
        "docs/PLAN.md",
        "docs/SPEC.md",
    ]
    plan_calls = [c for c in gen if ": docs/PLAN.md\n" in c["prompt"]]
    assert len(plan_calls) == 2  # failed once, retried
    # a second run gets a fresh folder name and does not touch the first
    job2 = await mat.start(s.session_id, MaterializeOptions(start_session=False, git_init=False))
    job2 = await mat.wait(s.session_id)
    assert job2.project_path.endswith("pflanzen-butler-2") and job2.code_session_id is None
    assert len(git_calls) == 3
    await mgr.stop_all()
    task.cancel()


async def test_materialize_placeholders_and_thin_idea(tmp_path):
    settings = Settings()
    settings.projects.base_dir = str(tmp_path / "P")
    settings.projects.start_session_after_create = False
    mgr, state, done, events, task = await _manager(tmp_path, settings=settings)
    s = await mgr.create(None, kind="brainstorm")  # no idea state at all
    llm = FakeLLM(error=RuntimeError("down"))
    git_calls = []
    mat = Materializer(lambda: settings, mgr._bus, mgr._db, mgr, llm, git_runner=_fake_git(git_calls))
    await mat.start(s.session_id, MaterializeOptions(name="Mein Test Projekt"))
    job = await mat.wait(s.session_id)
    assert job.status == "done" and job.project_path.endswith("mein-test-projekt")
    assert any("Bereitschaft nur 0" in w for w in job.warnings)
    assert sum("Platzhalter" in w for w in job.warnings) == len(DOC_SPECS)
    readme = (Path(job.project_path) / "README.md").read_text(encoding="utf-8")
    assert "nicht automatisch erzeugt" in readme and "down" in readme
    assert job.code_session_id is None
    await mgr.stop_all()
    task.cancel()


# --- API ------------------------------------------------------------------------------


def test_brainstorm_api_roundtrip(tmp_path):
    services = build_services(tmp_path / "config.toml", tmp_path / "t.db", fake=True, hardware=False)
    services.settings.projects.base_dir = str(tmp_path / "Projects")
    services.sessions._client_factory = FakeClient
    services.materializer._git = _fake_git([])
    with TestClient(create_app(services)) as c:
        created = c.post("/sessions", json={"kind": "brainstorm"}).json()
        sid = created["id"]
        assert (
            created["kind"] == "brainstorm" and created["title"] == "Brainstorm" and created["idea"] is None
        )
        assert c.get("/state").json()["session"]["kind"] == "brainstorm"
        assert c.post("/sessions", json={}).status_code == 422  # code sessions need a folder
        info = c.get(f"/brainstorm/{sid}").json()
        assert info == {"state": None, "project_path": None, "materialized": False, "files": [], "job": None}
        assert c.get("/brainstorm/nope").status_code == 404
        assert c.post(f"/brainstorm/{sid}/kickoff").status_code == 409
        sug = c.get("/projects/suggest", params={"title": "Pflanzen Butler"}).json()
        assert sug["slug"] == "pflanzen-butler" and sug["exists"] is False
        assert Path(sug["path"]).parent == tmp_path / "Projects"
        assert c.post("/projects/open", json={"path": str(tmp_path / "missing")}).status_code == 404
        assert c.post("/projects/open", json={"path": str(tmp_path)}).json()["ok"] is True
        r = c.post(
            f"/brainstorm/{sid}/materialize", json={"name": "Demo", "start_session": False, "git_init": False}
        )
        assert r.status_code == 200 and r.json()["ok"] is True
        for _ in range(200):
            job = c.get(f"/brainstorm/{sid}").json()["job"]
            if job and job["status"] != "running":
                break
            import time

            time.sleep(0.02)
        assert job["status"] == "done"
        info = c.get(f"/brainstorm/{sid}").json()
        assert info["materialized"] is True and "README.md" in info["files"]
        assert info["project_path"].endswith("demo")
        assert c.get("/sessions").json()[0]["project_path"] == info["project_path"]
        kicked = c.post(f"/brainstorm/{sid}/kickoff").json()
        assert (
            kicked["kind"] == "code" and kicked["cwd"] == info["project_path"] and kicked["title"] == "demo"
        )
        assert c.get("/state").json()["active_session_id"] == kicked["id"]
        assert c.get(f"/brainstorm/{kicked['id']}").status_code == 409
        c.put("/settings", json={"brainstorm": {"auto_listen": True}, "projects": {"git_init": False}})
        assert (
            services.settings.brainstorm.auto_listen is True and services.settings.projects.git_init is False
        )
