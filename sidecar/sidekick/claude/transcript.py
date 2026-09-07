"""Read Claude Code transcript files (JSONL) written for external sessions."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        return "\n".join(p for p in parts if p).strip()
    return ""


def _has_tool_result(content: Any) -> bool:
    return isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content
    )


def _entries(path: Path, max_lines: int = 4000) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        log.debug("transcript unreadable %s: %s", path, exc)
        return []
    out: list[dict[str, Any]] = []
    for line in lines[-max_lines:]:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _role_and_text(entry: dict[str, Any]) -> tuple[str, str] | None:
    etype = entry.get("type")
    message = entry.get("message") or {}
    if etype not in ("user", "assistant") or not isinstance(message, dict):
        return None
    content = message.get("content")
    if etype == "user" and _has_tool_result(content):
        return None
    text = _text_of(content)
    if not text:
        return None
    return etype, text


def last_assistant_text(path: str | Path | None) -> str | None:
    if not path:
        return None
    for entry in reversed(_entries(Path(path))):
        rt = _role_and_text(entry)
        if rt and rt[0] == "assistant":
            return rt[1]
    return None


def recent_messages(path: str | Path | None, n: int = 12) -> list[dict[str, str]]:
    if not path:
        return []
    msgs: list[dict[str, str]] = []
    for entry in reversed(_entries(Path(path))):
        rt = _role_and_text(entry)
        if rt:
            msgs.append({"role": rt[0], "text": rt[1]})
            if len(msgs) >= n:
                break
    msgs.reverse()
    return msgs
