"""Write/remove Sidekick's HTTP hooks in a Claude Code settings file, idempotently."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

HOOK_EVENTS = ["Stop", "Notification", "PermissionRequest", "UserPromptSubmit", "SessionStart", "SessionEnd"]
HOOK_TIMEOUT_S = 5


def hook_url(port: int, event: str) -> str:
    return f"http://127.0.0.1:{port}/hook/{event}"


_SIDEKICK_URL = re.compile(r"^https?://(127\.0\.0\.1|localhost):\d+/hook(/[A-Za-z]+)?/?$")


def is_sidekick_hook(hook: Any) -> bool:
    if not isinstance(hook, dict) or hook.get("type") != "http":
        return False
    return bool(_SIDEKICK_URL.match(str(hook.get("url", "")).strip()))


def settings_file(project: str | Path | None, scope: str) -> Path:
    if scope == "user":
        return Path.home() / ".claude" / "settings.json"
    if project is None:
        raise ValueError("project path required for project/local scope")
    base = Path(project).expanduser() / ".claude"
    if scope == "local":
        return base / "settings.local.json"
    if scope == "project":
        return base / "settings.json"
    raise ValueError(f"unknown scope {scope!r}")


def hook_entry(port: int, event: str) -> dict[str, Any]:
    return {"hooks": [{"type": "http", "url": hook_url(port, event), "timeout": HOOK_TIMEOUT_S}]}


def hook_config_snippet(port: int) -> dict[str, Any]:
    return {"hooks": {event: [hook_entry(port, event)] for event in HOOK_EVENTS}}


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"{path} enthält kein JSON-Objekt")
    return data


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _strip_ours(groups: list[Any]) -> list[Any]:
    kept: list[Any] = []
    for group in groups:
        if not isinstance(group, dict):
            kept.append(group)
            continue
        hooks = group.get("hooks")
        if not isinstance(hooks, list):
            kept.append(group)
            continue
        remaining = [h for h in hooks if not is_sidekick_hook(h)]
        if remaining:
            kept.append({**group, "hooks": remaining})
    return kept


def install(project: str | Path | None, scope: str, port: int) -> Path:
    path = settings_file(project, scope)
    data = _load(path)
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
    for event in HOOK_EVENTS:
        groups = hooks.get(event)
        groups = _strip_ours(groups) if isinstance(groups, list) else []
        groups.append(hook_entry(port, event))
        hooks[event] = groups
    data["hooks"] = hooks
    _write(path, data)
    return path


def uninstall(project: str | Path | None, scope: str) -> Path:
    path = settings_file(project, scope)
    data = _load(path)
    hooks = data.get("hooks")
    if isinstance(hooks, dict):
        for event in list(hooks):
            groups = hooks[event]
            if isinstance(groups, list):
                groups = _strip_ours(groups)
                if groups:
                    hooks[event] = groups
                else:
                    del hooks[event]
        if not hooks:
            del data["hooks"]
    if path.exists():
        _write(path, data)
    return path


def status(project: str | Path | None, scope: str) -> dict[str, Any]:
    path = settings_file(project, scope)
    try:
        data = _load(path)
    except (ValueError, json.JSONDecodeError) as exc:
        return {"installed": False, "file": str(path), "events": [], "port": None, "error": str(exc)}
    hooks = data.get("hooks") if isinstance(data.get("hooks"), dict) else {}
    events: list[str] = []
    port: int | None = None
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            continue
        for group in groups:
            for hook in group.get("hooks", []) if isinstance(group, dict) else []:
                if is_sidekick_hook(hook):
                    events.append(event)
                    try:
                        port = int(str(hook["url"]).split("127.0.0.1:")[1].split("/")[0])
                    except (IndexError, ValueError, KeyError):
                        pass
                    break
    return {
        "installed": all(e in events for e in HOOK_EVENTS),
        "file": str(path),
        "events": events,
        "port": port,
    }
