"""Part C: Sidekick channel hub, terminal launcher and setup commands."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sidekick import terminal
from sidekick.app import create_app
from sidekick.claude.summarize import Summarizer
from sidekick.services import RoutedDeliverer, build_services


def _services(tmp_path):
    services = build_services(tmp_path / "config.toml", tmp_path / "t.db", fake=True, hardware=False)
    spoken: list = []
    services.speaker.speak = lambda text, kind="summary": spoken.append((text, kind))
    return services, spoken


def _recv(ws, wanted: str, tries: int = 50):
    """Read frames until one of the wanted type arrives (pings are interleaved)."""
    for _ in range(tries):
        msg = ws.receive_json()
        if msg.get("type") == wanted:
            return msg
    raise AssertionError(f"no {wanted} frame")


def test_format_relay():
    assert (
        Summarizer.format_relay("Bash", "Run shell command", '{"command": "git status"}')
        == 'Claude möchte einen Befehl ausführen: {"command": "git status"}. Erlauben?'
    )
    assert Summarizer.format_relay("Bash", "Tests laufen lassen", "pytest -q").startswith(
        "Claude möchte einen Befehl ausführen: Tests laufen lassen."
    )
    assert Summarizer.format_relay("Write", "", "") == "Claude möchte eine Datei schreiben. Erlauben?"
    assert "das Werkzeug Foo benutzen" in Summarizer.format_relay("Foo", "x", "")


def test_terminal_commands(tmp_path):
    script = tmp_path / "sidekick-channel.mjs"
    assert terminal.install_command(script, "claude.exe", "node") == [
        "claude.exe",
        "mcp",
        "add",
        "--scope",
        "user",
        "sidekick",
        "--",
        "node",
        str(script),
    ]
    assert terminal.uninstall_command("claude") == ["claude", "mcp", "remove", "--scope", "user", "sidekick"]
    cmd = terminal.build_launch_command(r"C:\p", True, True, "blog", "claude")
    assert cmd == [
        "wt.exe",
        "-d",
        r"C:\p",
        "cmd.exe",
        "/k",
        "claude",
        "--remote-control",
        "blog",
        "--dangerously-load-development-channels",
        "server:sidekick",
    ]
    assert terminal.build_launch_command(r"C:\p", False, False, None, "claude")[-1] == "claude"
    assert terminal.build_launch_command(r"C:\p", True, False, None, "claude")[-1] == "--remote-control"


def test_channel_setup_status_install_uninstall(tmp_path, monkeypatch):
    script = tmp_path / "sidekick-channel.mjs"
    script.write_text("// bundle", encoding="utf-8")
    calls: list[list[str]] = []
    state = {"installed": False}

    def runner(cmd):
        calls.append(cmd)
        if cmd[1:3] == ["mcp", "add"]:
            state["installed"] = True
            return 0, "Added stdio MCP server sidekick"
        if cmd[1:3] == ["mcp", "remove"]:
            state["installed"] = False
            return 0, "removed"
        if cmd[1:3] == ["mcp", "get"]:
            return (
                (0, "sidekick:\n  Command: node")
                if state["installed"]
                else (1, "No MCP server found with name: sidekick")
            )
        return 1, "?"

    monkeypatch.setattr(terminal, "node_executable", lambda: r"C:\node\node.exe")
    setup = terminal.ChannelSetup(runner=runner, claude="claude.exe", script=script)
    info = setup.status()
    assert info["installed"] is False and info["script_found"] and info["node"].endswith("node.exe")
    assert "--dangerously-load-development-channels server:sidekick" in info["launch_hint"]
    info = setup.install()
    assert info["installed"] is True
    add = next(c for c in calls if c[1:3] == ["mcp", "add"])
    assert add == [
        "claude.exe",
        "mcp",
        "add",
        "--scope",
        "user",
        "sidekick",
        "--",
        r"C:\node\node.exe",
        str(script),
    ]
    assert setup.uninstall()["installed"] is False
    monkeypatch.setattr(terminal, "node_executable", lambda: None)
    with pytest.raises(RuntimeError, match="Node"):
        setup.install()


def test_channel_hub_over_websocket(tmp_path):
    services, spoken = _services(tmp_path)
    with TestClient(create_app(services)) as c:
        assert c.get("/channel/status").json()["connections"] == []
        assert c.post("/channel/push", json={"text": "hi"}).status_code == 404
        with c.websocket_connect("/channel") as ws:
            ws.send_json(
                {"type": "hello", "cwd": str(tmp_path), "pid": 4711, "name": "sidekick", "version": "0.1.0"}
            )
            for _ in range(50):
                status = c.get("/channel/status").json()
                if status["connections"]:
                    break
                time.sleep(0.01)
            conn = status["connections"][0]
            assert conn["cwd"] == str(tmp_path) and conn["pid"] == 4711
            # a hooked terminal session in the same folder shows the channel flag
            c.post("/hook/SessionStart", json={"session_id": "term-c", "cwd": str(tmp_path)})
            for _ in range(50):
                ext = [e for e in c.get("/sessions/external").json() if e["session_id"] == "term-c"]
                if ext:
                    break
                time.sleep(0.01)
            assert ext and ext[0]["channel"] is True
            # push from the UI reaches the channel
            r = c.post("/channel/push", json={"text": "hallo Terminal"})
            assert r.status_code == 200
            push = _recv(ws, "push")
            assert push["content"] == "hallo Terminal" and push["meta"] == {"kind": "text"}
            # spoken text goes to the channel when no embedded session runs
            loop = services.bus._loop
            target = asyncio.run_coroutine_threadsafe(
                RoutedDeliverer(services).deliver("mach die Tests grün", "main"), loop
            ).result(timeout=5)
            assert target == "channel"
            push = _recv(ws, "push")
            assert push["content"] == "mach die Tests grün" and push["meta"]["kind"] == "voice"
            # permission relay: announced on the glasses, answered by voice
            ws.send_json(
                {
                    "type": "permission_request",
                    "request_id": "abcde",
                    "tool_name": "Bash",
                    "description": "Run shell command",
                    "input_preview": '{"command": "git status"}',
                }
            )
            for _ in range(100):
                pending = c.get("/channel/status").json()["pending"]
                if pending:
                    break
                time.sleep(0.01)
            assert pending[0]["id"] == "abcde" and pending[0]["source"] == "channel"
            assert c.get("/state").json()["attention"] == "waiting_input"
            assert spoken[-1][1] == "needs_input" and "git status" in spoken[-1][0]
            # "später" defers, "ja" answers
            assert (
                asyncio.run_coroutine_threadsafe(
                    RoutedDeliverer(services).deliver("später", "main"), loop
                ).result(timeout=5)
                == "answer"
            )
            assert c.get("/state").json()["attention"] == "none"
            assert c.get("/channel/status").json()["pending"][0]["snoozed_until"] > time.time()
            assert c.post("/channel/permission/abcde", json={"behavior": "wake"}).json()["ok"] is True
            assert (
                asyncio.run_coroutine_threadsafe(
                    RoutedDeliverer(services).deliver("ja", "main"), loop
                ).result(timeout=5)
                == "answer"
            )
            verdict = _recv(ws, "permission")
            assert verdict == {"type": "permission", "request_id": "abcde", "behavior": "allow"}
            assert c.get("/channel/status").json()["pending"] == []
            assert c.post("/channel/permission/abcde", json={"behavior": "allow"}).status_code == 404
            # UI verdict on a second request, invalid behavior rejected
            ws.send_json(
                {
                    "type": "permission_request",
                    "request_id": "fghij",
                    "tool_name": "Write",
                    "description": "",
                    "input_preview": "",
                }
            )
            for _ in range(100):
                if c.get("/channel/status").json()["pending"]:
                    break
                time.sleep(0.01)
            assert c.post("/channel/permission/fghij", json={"behavior": "maybe"}).status_code == 422
            assert c.post("/channel/permission/fghij", json={"behavior": "deny"}).json()["ok"] is True
            assert _recv(ws, "permission")["behavior"] == "deny"
            # Claude replies through the channel: spoken
            ws.send_json({"type": "reply", "text": "Tests sind grün."})
            for _ in range(100):
                if spoken and spoken[-1] == ("Tests sind grün.", "channel"):
                    break
                time.sleep(0.01)
            assert spoken[-1] == ("Tests sind grün.", "channel")
            ws.send_json({"type": "pong"})
        for _ in range(100):
            if not c.get("/channel/status").json()["connections"]:
                break
            time.sleep(0.01)
        assert c.get("/channel/status").json()["connections"] == []
        assert c.get("/channel/status").json()["pending"] == []


def test_terminal_launch_route(tmp_path):
    services, spoken = _services(tmp_path)
    spawned: list = []
    services.terminal_spawn = lambda cmd, cwd: spawned.append((cmd, cwd))
    with TestClient(create_app(services)) as c:
        assert (
            c.post("/terminal/launch", json={"cwd": str(tmp_path / "nope"), "channel": False}).status_code
            == 422
        )
        r = c.post("/terminal/launch", json={"cwd": str(tmp_path), "channel": False, "name": "blog"})
        assert r.status_code == 200, r.text
        cmd, cwd = spawned[-1]
        assert cwd == str(tmp_path) and cmd[:4] == ["wt.exe", "-d", str(tmp_path), "cmd.exe"]
        assert "--remote-control" in cmd and "blog" in cmd and "server:sidekick" not in cmd
        # hooks were installed for the project (local scope) on the way
        local = tmp_path / ".claude" / "settings.local.json"
        assert local.exists() and "hook/Stop" in local.read_text(encoding="utf-8")
        assert json.loads(local.read_text(encoding="utf-8"))["hooks"]
        # channel requested but no setup available in this build (hardware=False)
        assert c.post("/terminal/launch", json={"cwd": str(tmp_path), "channel": True}).status_code == 200
        assert "server:sidekick" in spawned[-1][0]


def test_channel_script_path_from_source():
    from sidekick.paths import channel_script

    p = channel_script()
    assert p.name == "sidekick-channel.mjs" and Path(p).parts[-4:-1] == ("channels", "sidekick", "dist")


def test_relay_and_hook_prompt_are_announced_once(tmp_path):
    services, spoken = _services(tmp_path)
    with TestClient(create_app(services)) as c:
        with c.websocket_connect("/channel") as ws:
            ws.send_json(
                {"type": "hello", "cwd": str(tmp_path), "pid": 1, "name": "sidekick", "version": "0"}
            )
            for _ in range(50):
                if c.get("/channel/status").json()["connections"]:
                    break
                time.sleep(0.01)
            # the hook arrives first, the relay a moment later: one announcement
            c.post(
                "/hook/PermissionRequest",
                json={
                    "session_id": "t-dd",
                    "cwd": str(tmp_path),
                    "tool_name": "Bash",
                    "tool_input": {"command": "ls", "description": "list"},
                },
            )
            for _ in range(100):
                if any(s[1] == "needs_input" for s in spoken):
                    break
                time.sleep(0.01)
            ws.send_json(
                {
                    "type": "permission_request",
                    "request_id": "aaaaa",
                    "tool_name": "Bash",
                    "description": "list",
                    "input_preview": "ls",
                }
            )
            for _ in range(100):
                if c.get("/channel/status").json()["pending"]:
                    break
                time.sleep(0.01)
            time.sleep(0.1)
            assert sum(1 for s in spoken if s[1] == "needs_input") == 1
            # deferring the relay also quiets the hook-side prompt; a verdict clears it
            c.post("/channel/permission/aaaaa", json={"behavior": "defer"})
            ext = next(e for e in c.get("/sessions/external").json() if e["session_id"] == "t-dd")
            assert ext["snoozed_until"] and c.get("/state").json()["attention"] == "none"
            c.post("/channel/permission/aaaaa", json={"behavior": "wake"})
            ext = next(e for e in c.get("/sessions/external").json() if e["session_id"] == "t-dd")
            assert ext["snoozed_until"] is None and c.get("/state").json()["attention"] == "waiting_input"
            c.post("/channel/permission/aaaaa", json={"behavior": "deny"})
            assert _recv(ws, "permission")["behavior"] == "deny"
            ext = next(e for e in c.get("/sessions/external").json() if e["session_id"] == "t-dd")
            assert ext["attention"] is False and c.get("/state").json()["attention"] == "none"
            # relay first, then the hook: still one announcement; the hook-side defer mirrors back
            n = sum(1 for s in spoken if s[1] == "needs_input")
            ws.send_json(
                {
                    "type": "permission_request",
                    "request_id": "bbbbb",
                    "tool_name": "Write",
                    "description": "write x",
                    "input_preview": "",
                }
            )
            for _ in range(100):
                if sum(1 for s in spoken if s[1] == "needs_input") > n:
                    break
                time.sleep(0.01)
            c.post(
                "/hook/PermissionRequest",
                json={
                    "session_id": "t-dd",
                    "cwd": str(tmp_path),
                    "tool_name": "Write",
                    "tool_input": {"file_path": "x"},
                },
            )
            for _ in range(50):
                ext = next(e for e in c.get("/sessions/external").json() if e["session_id"] == "t-dd")
                if ext["attention"]:
                    break
                time.sleep(0.01)
            time.sleep(0.1)
            assert sum(1 for s in spoken if s[1] == "needs_input") == n + 1
            assert c.post("/sessions/external/t-dd/defer").status_code == 200
            assert c.get("/channel/status").json()["pending"][0]["snoozed_until"] is not None
            assert c.get("/state").json()["attention"] == "none"


def test_launch_permission_mode(tmp_path):
    cmd = terminal.build_launch_command(r"C:\p", False, True, None, "claude", "default")
    assert cmd[5:8] == ["claude", "--permission-mode", "default"]
    services, spoken = _services(tmp_path)
    spawned: list = []
    services.terminal_spawn = lambda cmd, cwd: spawned.append(cmd)
    with TestClient(create_app(services)) as c:
        assert (
            c.post(
                "/terminal/launch", json={"cwd": str(tmp_path), "channel": False, "permission_mode": "yolo"}
            ).status_code
            == 422
        )
        assert (
            c.post(
                "/terminal/launch",
                json={"cwd": str(tmp_path), "channel": False, "permission_mode": "default"},
            ).status_code
            == 200
        )
        assert "--permission-mode" in spawned[-1] and "default" in spawned[-1]
