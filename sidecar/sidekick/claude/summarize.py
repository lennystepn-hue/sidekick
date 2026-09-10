"""Spoken summaries of Claude's output and spoken renderings of questions/permissions."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from typing import Any

from ..config import Settings
from .utility import LLM, load_prompt

log = logging.getLogger(__name__)

_CODE_FENCE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`([^`]*)`")
_MD_MARKS = re.compile(r"(^\s{0,3}#{1,6}\s+|\*\*|__|^\s*[-*+]\s+|^\s*\d+\.\s+|>\s?)", re.MULTILINE)
_LINKS = re.compile(r"\[([^\]]+)\]\([^)]+\)")


def strip_markdown(text: str) -> str:
    out = _CODE_FENCE.sub(" Codeblock ", text)
    out = _LINKS.sub(r"\1", out)
    out = _INLINE_CODE.sub(r"\1", out)
    out = _MD_MARKS.sub("", out)
    out = re.sub(r"[ \t]+", " ", out)
    out = re.sub(r"\n{2,}", "\n", out)
    return out.strip()


def first_sentences(text: str, limit: int = 240) -> str:
    plain = strip_markdown(text).replace("\n", " ")
    if len(plain) <= limit:
        return plain
    cut = plain[:limit]
    for sep in (". ", "! ", "? "):
        idx = cut.rfind(sep)
        if idx > limit // 2:
            return cut[: idx + 1]
    return cut.rstrip() + "…"


def spoken_reply(text: str, limit: int = 900) -> str:
    """A brainstorm reply read out as is: markdown removed, cut at a sentence end if very long."""
    plain = strip_markdown(text).replace("\n", " ")
    plain = re.sub(r"\s{2,}", " ", plain).strip()
    if len(plain) <= limit:
        return plain
    cut = plain[:limit]
    for sep in (". ", "! ", "? "):
        idx = cut.rfind(sep)
        if idx > limit // 2:
            return cut[: idx + 1]
    return cut.rstrip() + "…"


MODEL_LABELS = {
    "claude-opus-5": "Opus 5",
    "claude-sonnet-5": "Sonnet 5",
    "claude-haiku-4-5": "Haiku 4.5",
    "claude-fable-5-1": "Fable 5.1",
}


def model_label(model: str) -> str:
    """Spoken name of a model id ("claude-sonnet-5" -> "Sonnet 5")."""
    model = (model or "").strip()
    if not model:
        return "das Standardmodell"
    if model in MODEL_LABELS:
        return MODEL_LABELS[model]
    name = model.removeprefix("claude-").replace("-", " ")
    return name[:1].upper() + name[1:]


TOOL_VERBS = {
    "Bash": "einen Befehl ausführen",
    "PowerShell": "einen Befehl ausführen",
    "Edit": "eine Datei ändern",
    "MultiEdit": "eine Datei ändern",
    "Write": "eine Datei schreiben",
    "Read": "eine Datei lesen",
    "WebFetch": "eine Webseite laden",
    "WebSearch": "im Web suchen",
}


def short_value(value: Any, limit: int = 120) -> str:
    if isinstance(value, str):
        s = value.strip().replace("\n", " ")
    else:
        s = str(value)
    return s if len(s) <= limit else s[: limit - 1] + "…"


class Summarizer:
    def __init__(self, llm: LLM, settings: Callable[[], Settings], timeout_s: float = 25) -> None:
        self._llm = llm
        self._settings = settings
        self._timeout = timeout_s
        self.system_prompt = load_prompt("summarize")

    async def summarize(self, assistant_text: str) -> str:
        text = (assistant_text or "").strip()
        if not text:
            return "Claude ist fertig."
        cfg = self._settings()
        if not cfg.tts.summarize_before_speaking or (len(text) < 200 and "```" not in text):
            return first_sentences(text, 400)
        prompt = f"Letzte Antwort von Claude Code:\n<<<\n{text[:12000]}\n>>>\n\nZusammenfassung zum Vorlesen:"
        try:
            out = await asyncio.wait_for(
                self._llm.complete(cfg.claude.summary_model, self.system_prompt, prompt), self._timeout
            )
            out = strip_markdown(out)
            if out:
                return out
        except Exception as exc:  # noqa: BLE001
            log.warning("summary failed, falling back to first sentences: %s", exc)
        return first_sentences(text)

    @staticmethod
    def format_needs_input(question: str, options: list[str] | None = None) -> str:
        q = strip_markdown(question or "Claude braucht eine Eingabe.")
        if options:
            opts = ", ".join(str(o) for o in options[:6])
            return f"Claude fragt: {q} Optionen: {opts}."
        return f"Claude fragt: {q}"

    @staticmethod
    def format_permission(
        tool_name: str, tool_input: dict[str, Any] | None, description: str | None = None
    ) -> str:
        tool_input = tool_input or {}
        detail = ""
        if tool_name == "Bash":
            detail = short_value(tool_input.get("description") or tool_input.get("command", ""))
        elif tool_name in ("Edit", "Write", "MultiEdit", "NotebookEdit", "Read"):
            path = str(tool_input.get("file_path", ""))
            detail = path.replace("\\", "/").rsplit("/", 1)[-1]
        elif tool_name == "WebFetch":
            detail = short_value(tool_input.get("url", ""), 80)
        elif description:
            detail = short_value(description)
        else:
            for value in tool_input.values():
                if isinstance(value, str) and value.strip():
                    detail = short_value(value, 80)
                    break
        verb = TOOL_VERBS.get(tool_name, f"das Werkzeug {tool_name} benutzen")
        return f"Claude möchte {verb}: {detail}. Erlauben?" if detail else f"Claude möchte {verb}. Erlauben?"

    @staticmethod
    def format_relay(tool_name: str, description: str, input_preview: str = "") -> str:
        """Spoken form of a relayed permission prompt (Claude Code channels): the summary
        when it says something, else the start of the arguments."""
        verb = TOOL_VERBS.get(tool_name, f"das Werkzeug {tool_name} benutzen")
        summary = (description or "").strip()
        if not summary or summary.lower() in ("run shell command", "shell command"):
            summary = (input_preview or "").strip()
        detail = short_value(strip_markdown(summary), 120) if summary else ""
        return f"Claude möchte {verb}: {detail}. Erlauben?" if detail else f"Claude möchte {verb}. Erlauben?"
