import asyncio
import json

from sidekick.bluetooth_doctor import parse_health
from sidekick.claude import installer
from sidekick.claude.btw import BtwAssistant, project_file_list
from sidekick.claude.utility import FakeLLM
from sidekick.config import Settings
from sidekick.db import Database
from sidekick.events import EventBus
from sidekick.state import AppState

# --- installer ------------------------------------------------------------------


def test_install_is_idempotent_and_keeps_foreign_hooks(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    settings = project / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text(
        json.dumps(
            {
                "permissions": {"allow": ["Bash(npm test)"]},
                "hooks": {
                    "Stop": [{"hooks": [{"type": "command", "command": "echo done"}]}],
                    "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "lint"}]}],
                },
            }
        ),
        encoding="utf-8",
    )
    path = installer.install(project, "project", 47821)
    assert path == settings
    path = installer.install(project, "project", 47821)
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["permissions"] == {"allow": ["Bash(npm test)"]}
    stop_groups = data["hooks"]["Stop"]
    assert len(stop_groups) == 2
    assert stop_groups[0]["hooks"][0]["command"] == "echo done"
    assert stop_groups[1]["hooks"] == [
        {"type": "http", "url": "http://127.0.0.1:47821/hook/Stop", "timeout": 5}
    ]
    assert len(data["hooks"]["Notification"]) == 1
    assert data["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == "lint"
    status = installer.status(project, "project")
    assert status["installed"] is True and status["port"] == 47821
    assert set(status["events"]) == set(installer.HOOK_EVENTS)

    # port change replaces our entries instead of adding more
    installer.install(project, "project", 47900)
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert len(data["hooks"]["Stop"]) == 2 and "47900" in data["hooks"]["Stop"][1]["hooks"][0]["url"]

    installer.uninstall(project, "project")
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["hooks"]["Stop"] == [{"hooks": [{"type": "command", "command": "echo done"}]}]
    assert "Notification" not in data["hooks"] and "PreToolUse" in data["hooks"]
    assert installer.status(project, "project")["installed"] is False


def test_install_creates_file_and_local_scope(tmp_path):
    project = tmp_path / "p2"
    project.mkdir()
    path = installer.install(project, "local", 47821)
    assert path == project / ".claude" / "settings.local.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert list(data) == ["hooks"] and set(data["hooks"]) == set(installer.HOOK_EVENTS)
    installer.uninstall(project, "local")
    assert json.loads(path.read_text(encoding="utf-8")) == {}
    snippet = installer.hook_config_snippet(47821)
    assert snippet["hooks"]["PermissionRequest"][0]["hooks"][0]["url"].endswith("/hook/PermissionRequest")


def test_status_on_broken_json(tmp_path):
    project = tmp_path / "p3"
    (project / ".claude").mkdir(parents=True)
    (project / ".claude" / "settings.json").write_text("{not json", encoding="utf-8")
    s = installer.status(project, "project")
    assert s["installed"] is False and "error" in s


# --- btw ------------------------------------------------------------------------


def test_project_file_list_walk_and_git(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "junk.js").write_text("x", encoding="utf-8")
    (tmp_path / "README.md").write_text("x", encoding="utf-8")
    files = project_file_list(tmp_path)
    assert "README.md" in files and "src/a.py" in files and not any("node_modules" in f for f in files)
    assert project_file_list(tmp_path, limit=1) == ["README.md"]
    assert project_file_list(None) == [] and project_file_list(tmp_path / "nope") == []


async def test_btw_builds_context_and_stores(tmp_path):
    bus = EventBus()
    bus.bind(asyncio.get_running_loop())
    state = AppState(bus)
    llm = FakeLLM(["Die Tests liegen unter tests."])
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("x", encoding="utf-8")
    msgs = [{"role": "user", "text": "Mach X"}, {"role": "assistant", "text": "X gemacht"}]
    btw = BtwAssistant(
        llm, Database(tmp_path / "t.db"), lambda: Settings(), state, bus, lambda: ("s1", msgs, str(tmp_path))
    )
    record = await btw.ask("Wo liegen die Tests?")
    assert record["answer"] == "Die Tests liegen unter tests." and record["session_id"] == "s1"
    prompt = llm.calls[0]["prompt"]
    assert (
        "tests/test_x.py" in prompt and "[assistant] X gemacht" in prompt and "Wo liegen die Tests?" in prompt
    )
    assert llm.calls[0]["model"] == "claude-sonnet-5" and "btw" in llm.calls[0]["system"]
    assert any(e.type == "btw_answer" for e in bus.history)
    assert btw._db.list_btw()[0]["question"] == "Wo liegen die Tests?"
    failing = BtwAssistant(
        FakeLLM(error=RuntimeError("down")),
        Database(tmp_path / "t2.db"),
        lambda: Settings(),
        state,
        bus,
        lambda: (None, [], None),
    )
    rec = await failing.ask("Hm?")
    assert rec["answer"].startswith("Das konnte ich gerade nicht beantworten")


# --- bluetooth doctor -------------------------------------------------------------

REAL_JSON = (
    '{"FriendlyName":"Intel(R) Wireless Bluetooth(R)","Status":"Error","Problem":10,'
    '"ProblemDescription":"This device cannot start. (Code 10).","InstanceId":"USB\\\\VID_8087&PID_0029\\\\6&822DB66&0&3"}'
)


def test_parse_health_code_10_from_this_machine():
    h = parse_health(REAL_JSON)
    assert h.ok is False and h.problem_code == 10
    assert h.adapter_name.startswith("Intel") and h.instance_id.startswith("USB\\VID_8087")
    assert "Code 10" in h.problem_description


def test_parse_health_ok_and_empty():
    ok = parse_health(
        '[{"FriendlyName":"X","Status":"OK","Problem":0,"ProblemDescription":null,"InstanceId":"PCI\\\\1"}]'
    )
    assert ok.ok is True and ok.problem_code is None and ok.instance_id == "PCI\\1"
    assert parse_health("").ok is False and parse_health("garbage").ok is False
    two = parse_health(
        '[{"FriendlyName":"A","Status":"OK","Problem":0,"InstanceId":"1"},{"FriendlyName":"B","Status":"Error","Problem":43,"ProblemDescription":"x (Code 43).","InstanceId":"2"}]'
    )
    assert two.ok is False and two.adapter_name == "B" and two.problem_code == 43
