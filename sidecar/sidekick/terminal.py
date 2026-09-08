"""Terminal sessions: register the Sidekick channel with Claude Code and launch
`claude` in Windows Terminal with the right flags (Remote Control, channel)."""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .claude import installer
from .paths import channel_script

log = logging.getLogger(__name__)

MCP_NAME = "sidekick"
CHANNEL_SPEC = f"server:{MCP_NAME}"
Runner = Callable[[list[str]], tuple[int, str]]


def bundled_claude() -> Path | None:
    try:
        import claude_agent_sdk

        path = Path(claude_agent_sdk.__file__).resolve().parent / "_bundled" / "claude.exe"
        return path if path.exists() else None
    except Exception:  # noqa: BLE001
        return None


def claude_executable() -> str | None:
    """The Claude Code binary for management commands: the SDK's bundled exe (no cmd.exe
    hop), else whatever `claude` is on PATH."""
    bundled = bundled_claude()
    if bundled is not None:
        return str(bundled)
    return shutil.which("claude")


def claude_in_terminal() -> str:
    """How to invoke Claude Code inside the launched terminal: the user's own install when
    it is on PATH, else the bundled exe."""
    if shutil.which("claude"):
        return "claude"
    bundled = bundled_claude()
    return str(bundled) if bundled is not None else "claude"


def node_executable() -> str | None:
    return shutil.which("node")


def install_command(script: Path, claude: str, node: str = "node") -> list[str]:
    return [claude, "mcp", "add", "--scope", "user", MCP_NAME, "--", node, str(script)]


def uninstall_command(claude: str) -> list[str]:
    return [claude, "mcp", "remove", "--scope", "user", MCP_NAME]


def get_command(claude: str) -> list[str]:
    return [claude, "mcp", "get", MCP_NAME]


def build_launch_command(
    cwd: str,
    remote_control: bool = True,
    channel: bool = True,
    name: str | None = None,
    claude: str = "claude",
) -> list[str]:
    cmd = ["wt.exe", "-d", cwd, "cmd.exe", "/k", claude]
    if remote_control:
        cmd.append("--remote-control")
        if name:
            cmd.append(name)
    if channel:
        cmd += ["--dangerously-load-development-channels", CHANNEL_SPEC]
    return cmd


def run(cmd: list[str], timeout: float = 60) -> tuple[int, str]:
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0  # type: ignore[attr-defined]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=flags,
        timeout=timeout,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


class ChannelSetup:
    """Registers the channel server as a user-scope MCP server named `sidekick`."""

    def __init__(
        self, runner: Runner | None = None, claude: str | None = None, script: Path | None = None
    ) -> None:
        self._run = runner or run
        self._claude = claude
        self._script = script

    @property
    def claude(self) -> str | None:
        return self._claude or claude_executable()

    @property
    def script(self) -> Path:
        return self._script or channel_script()

    def status(self) -> dict[str, Any]:
        claude = self.claude
        script = self.script
        installed = False
        output = ""
        if claude:
            try:
                code, output = self._run(get_command(claude))
                installed = code == 0 and MCP_NAME in output and "not found" not in output.lower()
            except Exception as exc:  # noqa: BLE001
                output = str(exc)
        return {
            "installed": installed,
            "script": str(script),
            "script_found": script.exists(),
            "node": node_executable(),
            "claude": claude,
            "output": output.strip()[-400:],
            "launch_hint": " ".join(
                build_launch_command("<projekt>", True, True, None, claude_in_terminal())[5:]
            ),
        }

    def install(self) -> dict[str, Any]:
        claude = self.claude
        node = node_executable()
        if not claude:
            raise RuntimeError("Claude Code wurde nicht gefunden")
        if not node:
            raise RuntimeError("Node.js wurde nicht gefunden (wird für den Kanal gebraucht)")
        script = self.script
        if not script.exists():
            raise RuntimeError(f"Kanal-Skript fehlt: {script}")
        self._run(uninstall_command(claude))  # replace a stale entry silently
        code, output = self._run(install_command(script, claude, node))
        if code != 0:
            raise RuntimeError(output.strip()[-400:] or "claude mcp add fehlgeschlagen")
        log.info("channel server registered: %s", script)
        return self.status()

    def uninstall(self) -> dict[str, Any]:
        claude = self.claude
        if claude:
            self._run(uninstall_command(claude))
        return self.status()


def launch(
    cwd: str,
    port: int,
    remote_control: bool = True,
    channel: bool = True,
    name: str | None = None,
    spawn: Callable[[list[str], str], Any] | None = None,
) -> dict[str, Any]:
    """Open Windows Terminal with a Claude Code session in `cwd`. Installs Sidekick's HTTP
    hooks in the project's local settings first so announcements work either way."""
    path = Path(cwd).expanduser()
    if not path.is_dir():
        raise ValueError(f"Kein Verzeichnis: {cwd}")
    if not shutil.which("wt.exe") and sys.platform == "win32":
        raise RuntimeError("Windows Terminal (wt.exe) wurde nicht gefunden")
    try:
        if not installer.status(path, "local").get("installed"):
            installer.install(path, "local", port)
    except Exception as exc:  # noqa: BLE001
        log.warning("hook install for %s failed: %s", path, exc)
    cmd = build_launch_command(str(path), remote_control, channel, name, claude_in_terminal())
    if spawn is not None:
        spawn(cmd, str(path))
    else:
        subprocess.Popen(cmd, cwd=str(path))  # noqa: S603 - our own command line
    log.info("launched terminal session: %s", " ".join(cmd))
    return {"ok": True, "command": cmd}
