"""Cleanup pass: fix spelling, drop fillers, canonical tech terms. Never rewrites meaning."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable

from ..claude.utility import LLM, load_prompt
from ..config import Settings

log = logging.getLogger(__name__)

_FENCE = re.compile(r"^```[a-zA-Z0-9_-]*\s*|\s*```$", re.MULTILINE)
_PREFIX = re.compile(r"^(bereinigt|bereinigter text|cleaned|output|text)\s*:\s*", re.IGNORECASE)


def strip_wrapping(text: str) -> str:
    out = _FENCE.sub("", text.strip()).strip()
    out = _PREFIX.sub("", out).strip()
    if len(out) >= 2 and out[0] == out[-1] and out[0] in "\"'„“”":
        out = out[1:-1].strip()
    if out.startswith("„") and out.endswith("“"):
        out = out[1:-1].strip()
    return out


class Cleaner:
    def __init__(self, llm: LLM, settings: Callable[[], Settings], timeout_s: float = 20) -> None:
        self._llm = llm
        self._settings = settings
        self._timeout = timeout_s
        self.system_prompt = load_prompt("cleanup")

    async def clean(self, raw: str, hotwords: list[str] | None = None) -> tuple[str, bool]:
        """Return (text, cleaned). On any failure the raw text comes back with cleaned=False."""
        raw = raw.strip()
        if not raw:
            return raw, False
        cfg = self._settings()
        if not cfg.stt.cleanup_enabled:
            return raw, False
        terms = ", ".join(t.strip() for t in (hotwords or []) if t.strip())
        known = f"Bekannte Begriffe: {terms}\n\n" if terms else ""
        prompt = f"{known}Transkript:\n<<<\n{raw}\n>>>\n\nBereinigter Text:"
        try:
            out = await asyncio.wait_for(
                self._llm.complete(cfg.claude.cleanup_model, self.system_prompt, prompt), self._timeout
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("cleanup failed, using raw transcript: %s", exc)
            return raw, False
        out = strip_wrapping(out)
        if not out or len(out) > max(400, len(raw) * 3):
            log.warning("cleanup returned implausible output, using raw transcript")
            return raw, False
        return out, True
