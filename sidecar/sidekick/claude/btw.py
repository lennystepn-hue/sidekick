"""Side questions ("btw"): answered by a light model with read-only context, never in the main session."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..config import Settings
from ..db import Database, new_id
from ..events import EventBus
from ..state import AppState
from .utility import LLM, load_prompt

log = logging.getLogger(__name__)

SKIP_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "target",
    "dist",
    "build",
    "__pycache__",
    ".idea",
    ".vscode",
}


def project_file_list(cwd: str | Path | None, limit: int = 300) -> list[str]:
    if not cwd:
        return []
    root = Path(cwd)
    if not root.is_dir():
        return []
    if (root / ".git").exists():
        try:
            out = subprocess.run(
                ["git", "ls-files"],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if out.returncode == 0:
                files = [line.strip() for line in out.stdout.splitlines() if line.strip()]
                return files[:limit]
        except (OSError, subprocess.SubprocessError):
            pass
    files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        rel = os.path.relpath(dirpath, root)
        for name in sorted(filenames):
            files.append(name if rel == "." else f"{rel}/{name}".replace("\\", "/"))
            if len(files) >= limit:
                return files
    return files


ContextProvider = Callable[[], tuple[str | None, list[dict[str, str]], str | None]]


class BtwAssistant:
    """`context()` returns (session_id, messages[{role,text}], cwd)."""

    def __init__(
        self,
        llm: LLM,
        db: Database,
        settings: Callable[[], Settings],
        state: AppState,
        bus: EventBus,
        context: ContextProvider,
    ) -> None:
        self._llm = llm
        self._db = db
        self._settings = settings
        self._state = state
        self._bus = bus
        self._context = context
        self.system_prompt = load_prompt("btw")

    def build_prompt(
        self, question: str, cwd: str | None, messages: list[dict[str, str]], files: list[str]
    ) -> str:
        parts: list[str] = []
        parts.append(f"Projekt: {cwd or 'unbekannt'}")
        if files:
            parts.append("Dateien (Auszug):\n" + "\n".join(files))
        if messages:
            lines = []
            for m in messages:
                text = m.get("text", "").strip()
                if len(text) > 1500:
                    text = text[:1500] + " …"
                lines.append(f"[{m.get('role', '?')}] {text}")
            parts.append("Letzte Nachrichten der Hauptsession:\n<<<\n" + "\n\n".join(lines) + "\n>>>")
        else:
            parts.append("Letzte Nachrichten der Hauptsession: keine")
        parts.append(f"Nebenfrage des Entwicklers:\n<<<\n{question.strip()}\n>>>\n\nAntwort zum Vorlesen:")
        return "\n\n".join(parts)

    async def ask(self, question: str) -> dict[str, Any]:
        cfg = self._settings()
        session_id, messages, cwd = self._context()
        messages = messages[-cfg.btw.context_messages :]
        files = await asyncio.to_thread(project_file_list, cwd, cfg.btw.file_list_limit)
        prompt = self.build_prompt(question, cwd, messages, files)
        try:
            answer = await asyncio.wait_for(
                self._llm.complete(cfg.claude.btw_model, self.system_prompt, prompt), 60
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("btw failed")
            answer = f"Das konnte ich gerade nicht beantworten: {exc}"
        answer = (answer or "").strip() or "Dazu weiß ich nichts."
        record = self._db.add_btw(new_id(), session_id, question.strip(), answer)
        self._bus.publish("btw_answer", record)
        return record
