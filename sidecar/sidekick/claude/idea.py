"""The structured idea state a brainstorm session maintains.

Every reply of the brainstorm partner ends with an `<idea-state>…</idea-state>` block that
holds a JSON snapshot of the idea. This module parses that block, strips it from what the
user sees and hears, and keeps streamed deltas from leaking it.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any

OPEN_TAG = "<idea-state>"
CLOSE_TAG = "</idea-state>"
READY_AT = 80
LIST_FIELDS = ("core_features", "non_goals", "stack", "decisions", "open_questions", "next_steps")
TEXT_FIELDS = ("title", "one_liner", "problem", "users")


@dataclass(slots=True)
class IdeaState:
    title: str = ""
    one_liner: str = ""
    problem: str = ""
    users: str = ""
    core_features: list[str] = field(default_factory=list)
    non_goals: list[str] = field(default_factory=list)
    stack: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    readiness: int = 0
    ready: bool = False
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None, updated_at: str = "") -> IdeaState:
        data = data or {}
        out = cls()
        for name in TEXT_FIELDS:
            setattr(out, name, _clean_text(data.get(name)))
        for name in LIST_FIELDS:
            setattr(out, name, _clean_list(data.get(name)))
        out.readiness = _clamp_int(data.get("readiness"))
        ready = data.get("ready")
        out.ready = bool(ready) if isinstance(ready, bool) else out.readiness >= READY_AT
        out.updated_at = str(data.get("updated_at") or updated_at or "")
        return out

    @property
    def is_empty(self) -> bool:
        return not (self.title or self.one_liner or self.problem or self.core_features)

    def gaps(self) -> list[str]:
        """What is still missing for solid project documents (used in the docs prompt)."""
        missing: list[str] = []
        if not self.problem:
            missing.append("Problem")
        if not self.users:
            missing.append("Nutzer")
        if not self.core_features:
            missing.append("Kernfunktionen")
        if not self.non_goals:
            missing.append("Nicht-Ziele")
        if not self.stack:
            missing.append("Technik")
        return missing


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split()).strip()


def _clean_list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, dict):
            item = item.get("text") or item.get("title") or json.dumps(item, ensure_ascii=False)
        text = _clean_text(item)
        if text:
            out.append(text)
    return out[:40]


def _clamp_int(value: Any) -> int:
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, n))


_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def parse_state_json(raw: str) -> dict[str, Any] | None:
    """Tolerant JSON parsing: code fences, stray text around the object, trailing commas."""
    text = _FENCE.sub("", raw.strip())
    start, end = text.find("{"), text.rfind("}")
    if start < 0:
        return None
    candidate = text[start : end + 1] if end > start else text[start:] + "}"
    for attempt in (candidate, re.sub(r",\s*([}\]])", r"\1", candidate)):
        try:
            data = json.loads(attempt)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None


def split_idea_block(text: str) -> tuple[str, dict[str, Any] | None]:
    """Return (visible text without the block, parsed state or None)."""
    if not text:
        return "", None
    idx = text.find(OPEN_TAG)
    if idx < 0:
        return text.strip(), None
    visible = text[:idx].rstrip()
    rest = text[idx + len(OPEN_TAG) :]
    close = rest.find(CLOSE_TAG)
    inner = rest if close < 0 else rest[:close]
    tail = "" if close < 0 else rest[close + len(CLOSE_TAG) :].strip()
    if tail:  # anything the model says after the block still belongs to the user
        visible = (visible + "\n\n" + tail).strip()
    return visible, parse_state_json(inner)


class StreamFilter:
    """Holds back streamed text that could be the start of the idea block.

    `feed(delta)` returns the part that is safe to show; once the opening tag is seen,
    nothing more is emitted for this message.
    """

    def __init__(self) -> None:
        self._pending = ""
        self.muted = False

    def feed(self, delta: str) -> str:
        if self.muted:
            return ""
        buf = self._pending + delta
        idx = buf.find(OPEN_TAG)
        if idx >= 0:
            self.muted = True
            self._pending = ""
            return buf[:idx]
        # keep a suffix that is a proper prefix of the tag (e.g. "<idea-st")
        keep = 0
        for n in range(min(len(OPEN_TAG) - 1, len(buf)), 0, -1):
            if buf.endswith(OPEN_TAG[:n]):
                keep = n
                break
        if keep:
            self._pending = buf[-keep:]
            return buf[:-keep]
        self._pending = ""
        return buf

    def flush(self) -> str:
        out, self._pending = self._pending, ""
        return "" if self.muted else out


# --- project names ------------------------------------------------------------------

_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"})


def slugify(name: str, fallback: str = "projekt") -> str:
    text = unicodedata.normalize("NFKD", name.translate(_UMLAUTS))
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    text = re.sub(r"-{2,}", "-", text)
    return text[:48].strip("-") or fallback
