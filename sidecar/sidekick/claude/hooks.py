"""Claude Code hook events from external (terminal) sessions.

The endpoint stores the payload, returns immediately and lets this handler decide what
to play and say. Attention (yellow tray) is set while an external session waits for
input and cleared when the user submits a prompt or the session stops.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..config import Settings
from ..db import Database
from ..events import EventBus
from ..state import AppState
from .summarize import Summarizer
from .transcript import last_assistant_text

log = logging.getLogger(__name__)

NEEDS_INPUT_TYPES = {
    "permission_prompt",
    "idle_prompt",
    "agent_needs_input",
    "elicitation_dialog",
    "elicitation_url_dialog",
}
IGNORED_NOTIFICATIONS = {
    "auth_success",
    "elicitation_complete",
    "elicitation_response",
    "agent_completed",
    "quota_auto_resume_fired",
    "quota_auto_resume_stale",
    "quota_auto_resume_disabled",
}
DEDUPE_WINDOW_S = 5.0


class SoundsLike(Protocol):
    def play(self, name: str, block: bool = False) -> None: ...


class SpeakerLike(Protocol):
    def speak(self, text: str, kind: str = "summary") -> None: ...


@dataclass
class ExternalSession:
    session_id: str
    cwd: str = ""
    transcript_path: str = ""
    last_event: str = ""
    last_ts: float = field(default_factory=time.time)
    attention: bool = False
    active: bool = True
    last_summary: str = ""
    seq: int = 0  # ordering tie-breaker (time.time() resolution on Windows is ~15 ms)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "cwd": self.cwd,
            "transcript_path": self.transcript_path,
            "last_event": self.last_event,
            "last_ts": self.last_ts,
            "attention": self.attention,
            "active": self.active,
        }


class HookHandler:
    def __init__(
        self,
        state: AppState,
        bus: EventBus,
        db: Database,
        sounds: SoundsLike,
        speaker: SpeakerLike,
        summarizer: Summarizer,
        settings: Callable[[], Settings],
        embedded_waiting: Callable[[], bool] | None = None,
        ignore_session_ids: Callable[[], set[str]] | None = None,
    ) -> None:
        self._state = state
        self._bus = bus
        self._db = db
        self._sounds = sounds
        self._speaker = speaker
        self._summarizer = summarizer
        self._settings = settings
        self._embedded_waiting = embedded_waiting or (lambda: False)
        self._ignore_session_ids = ignore_session_ids or (lambda: set())
        self.sessions: dict[str, ExternalSession] = {}
        self._recent: dict[str, float] = {}
        self._seq = 0

    # --- queries ---------------------------------------------------------
    def list_sessions(self) -> list[dict[str, Any]]:
        return [
            s.to_dict()
            for s in sorted(self.sessions.values(), key=lambda s: (s.last_ts, s.seq), reverse=True)
        ]

    def latest(self) -> ExternalSession | None:
        active = [s for s in self.sessions.values() if s.active]
        if not active:
            return None
        return max(active, key=lambda s: (s.last_ts, s.seq))

    # --- handling --------------------------------------------------------
    async def handle(self, event: str | None, payload: dict[str, Any]) -> None:
        event = str(payload.get("hook_event_name") or event or "unknown")
        sid = str(payload.get("session_id") or "unknown")
        cwd = str(payload.get("cwd") or "")
        self._db.add_hook_event(event, sid, payload)
        if sid in self._ignore_session_ids():
            # The embedded session loads the project's settings, so its own hooks fire too;
            # the SDK already tells us everything about that session.
            log.debug("ignoring hook %s from embedded session %s", event, sid)
            return
        session = self.sessions.get(sid)
        if session is None:
            session = ExternalSession(session_id=sid)
            self.sessions[sid] = session
        session.cwd = cwd or session.cwd
        session.transcript_path = str(payload.get("transcript_path") or session.transcript_path)
        session.last_event = event
        session.last_ts = time.time()
        self._seq += 1
        session.seq = self._seq
        session.active = True
        summary = ""
        log.info("hook %s from session %s (%s)", event, sid, session.cwd or "?")
        try:
            summary = await self._dispatch(event, session, payload)
        except Exception:  # noqa: BLE001
            log.exception("hook %s failed", event)
            self._bus.publish(
                "error", {"module": "hooks", "message": f"Hook {event} konnte nicht verarbeitet werden"}
            )
        self._bus.publish(
            "hook_event", {"event": event, "session_id": sid, "cwd": session.cwd, "summary": summary}
        )
        self._refresh_state()

    async def _dispatch(self, event: str, session: ExternalSession, payload: dict[str, Any]) -> str:
        if event == "SessionStart":
            return "Session gestartet"
        if event == "SessionEnd":
            session.active = False
            session.attention = False
            return "Session beendet"
        if event == "UserPromptSubmit":
            session.attention = False
            return "Eingabe gesendet"
        if event == "Stop":
            return await self._on_stop(session, payload)
        if event == "Notification":
            return await self._on_notification(session, payload)
        if event == "PermissionRequest":
            return await self._on_permission(session, payload)
        return ""

    async def _on_stop(self, session: ExternalSession, payload: dict[str, Any]) -> str:
        session.attention = False
        text = str(payload.get("last_assistant_message") or "").strip()
        if not text:
            text = last_assistant_text(session.transcript_path) or ""
        self._sounds.play("done")
        summary = await self._summarizer.summarize(text)
        session.last_summary = summary
        self._speaker.speak(summary, kind="done")
        return summary

    async def _on_notification(self, session: ExternalSession, payload: dict[str, Any]) -> str:
        ntype = str(payload.get("notification_type") or "")
        data = payload.get("notification_data") or {}
        message = str(payload.get("message") or "").strip()
        if ntype in IGNORED_NOTIFICATIONS:
            return ""
        if ntype and ntype not in NEEDS_INPUT_TYPES and not message:
            return ""
        if ntype == "permission_prompt" or (isinstance(data, dict) and data.get("tool_name")):
            tool_name = str(data.get("tool_name") or "")
            tool_input = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
            keys = self._perm_keys(
                session.session_id,
                data.get("tool_use_id") or payload.get("tool_use_id"),
                tool_name,
                tool_input,
            )
            if self._duplicate(*keys):
                return ""
            spoken = self._summarizer.format_permission(tool_name, tool_input, message or None)
        else:
            spoken = self._summarizer.format_needs_input(message or "Claude wartet auf deine Eingabe.")
            if self._duplicate(
                f"{session.session_id}:{ntype}:{hashlib.sha1(spoken.encode()).hexdigest()[:8]}"
            ):
                return ""
        session.attention = True
        self._sounds.play("needs_input")
        self._speaker.speak(spoken, kind="needs_input")
        return spoken

    async def _on_permission(self, session: ExternalSession, payload: dict[str, Any]) -> str:
        tool_name = str(payload.get("tool_name") or "")
        tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
        keys = self._perm_keys(session.session_id, payload.get("tool_use_id"), tool_name, tool_input)
        if self._duplicate(*keys):
            return ""
        session.attention = True
        spoken = self._summarizer.format_permission(tool_name, tool_input)
        self._sounds.play("needs_input")
        self._speaker.speak(spoken, kind="needs_input")
        return spoken

    # --- helpers ---------------------------------------------------------
    @staticmethod
    def _perm_keys(sid: str, tool_use_id: Any, tool_name: str, tool_input: dict[str, Any]) -> list[str]:
        """Both an id-based and a content-based key, so PermissionRequest and the matching
        Notification dedupe each other even when only one of them carries the tool_use_id."""
        digest = hashlib.sha1(json.dumps(tool_input, sort_keys=True, default=str).encode()).hexdigest()[:10]
        keys = [f"{sid}:perm:{tool_name}:{digest}"]
        if tool_use_id:
            keys.append(f"{sid}:perm:{tool_use_id}")
        return keys

    def _duplicate(self, *keys: str) -> bool:
        now = time.time()
        for k, ts in list(self._recent.items()):
            if now - ts > DEDUPE_WINDOW_S:
                del self._recent[k]
        seen = any(k in self._recent for k in keys)
        for k in keys:
            self._recent[k] = now
        return seen

    def refresh_state(self) -> None:
        """Recompute attention/external session count (also called by the embedded session)."""
        active = [s for s in self.sessions.values() if s.active]
        waiting = any(s.attention for s in active) or self._embedded_waiting()
        self._state.update(
            external_sessions=len(active),
            attention="waiting_input" if waiting else "none",
        )

    _refresh_state = refresh_state
