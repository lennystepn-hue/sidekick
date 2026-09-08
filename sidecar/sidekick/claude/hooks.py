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
    adopted_by: str | None = None  # Sidekick session that forked this one; announcements muted
    snoozed_until: float | None = None
    last_prompt: str = ""

    @property
    def snoozed(self) -> bool:
        return self.snoozed_until is not None and self.snoozed_until > time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "cwd": self.cwd,
            "transcript_path": self.transcript_path,
            "last_event": self.last_event,
            "last_ts": self.last_ts,
            "attention": self.attention,
            "active": self.active,
            "adopted_by": self.adopted_by,
            "snoozed_until": self.snoozed_until,
            "last_prompt": self.last_prompt,
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
        quiet: Callable[[], bool] | None = None,
    ) -> None:
        self._quiet = quiet or (lambda: False)
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
        active = [s for s in self.sessions.values() if s.active and not s.adopted_by]
        if not active:
            return None
        return max(active, key=lambda s: (s.last_ts, s.seq))

    def waiting(self) -> ExternalSession | None:
        """The external session whose prompt is open and not deferred, newest first."""
        open_ = [
            s
            for s in self.sessions.values()
            if s.active and s.attention and not s.snoozed and not s.adopted_by
        ]
        if not open_:
            return None
        return max(open_, key=lambda s: (s.last_ts, s.seq))

    # --- adoption / deferral --------------------------------------------
    def mark_adopted(self, session_id: str, by: str | None) -> None:
        session = self.sessions.get(session_id)
        if session is not None:
            session.adopted_by = by
            session.attention = False if by else session.attention
            self._refresh_state()

    def defer(self, session_id: str, minutes: int) -> float | None:
        session = self.sessions.get(session_id)
        if session is None or not session.attention:
            return None
        session.snoozed_until = time.time() + 60 * max(1, minutes)
        self._bus.publish(
            "permission_deferred",
            {"id": session_id, "session_id": session_id, "until": session.snoozed_until},
        )
        self._refresh_state()
        return session.snoozed_until

    def wake(self, session_id: str, announce: bool = False) -> bool:
        session = self.sessions.get(session_id)
        if session is None or session.snoozed_until is None:
            return False
        session.snoozed_until = None
        self._bus.publish("permission_woken", {"id": session_id, "session_id": session_id})
        if announce and session.attention and session.active and session.last_prompt:
            self._sounds.play("needs_input")
            self._speaker.speak(session.last_prompt, kind="needs_input")
        self._refresh_state()
        return True

    def tick_snoozes(self, now: float | None = None) -> list[str]:
        now = time.time() if now is None else now
        woken = [
            s.session_id
            for s in self.sessions.values()
            if s.snoozed_until is not None and s.snoozed_until <= now
        ]
        for sid in woken:
            self.wake(sid, announce=True)
        return woken

    def wake_all_snoozed(self) -> list[str]:
        return self.tick_snoozes(now=float("inf"))

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
            session.snoozed_until = None
            if session.adopted_by:
                session.adopted_by = None  # the user is typing in the terminal again
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
        session.snoozed_until = None
        if session.adopted_by:
            return "Fertig (in Sidekick übernommen)"
        text = str(payload.get("last_assistant_message") or "").strip()
        if not text:
            text = last_assistant_text(session.transcript_path) or ""
        self._sounds.play("done")
        if self._quiet():
            log.info("quiet period: not reading the summary for %s", session.session_id)
            return "Fertig (still, du warst gerade selbst dran)"
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
        return self._announce(session, spoken)

    def _announce(self, session: ExternalSession, spoken: str) -> str:
        session.attention = True
        session.snoozed_until = None
        session.last_prompt = spoken
        if session.adopted_by:
            return spoken
        self._sounds.play("needs_input")
        self._speaker.speak(spoken, kind="needs_input")
        return spoken

    async def _on_permission(self, session: ExternalSession, payload: dict[str, Any]) -> str:
        tool_name = str(payload.get("tool_name") or "")
        tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
        keys = self._perm_keys(session.session_id, payload.get("tool_use_id"), tool_name, tool_input)
        if self._duplicate(*keys):
            return ""
        spoken = self._summarizer.format_permission(tool_name, tool_input)
        return self._announce(session, spoken)

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
        waiting = (
            any(s.attention and not s.snoozed and not s.adopted_by for s in active)
            or self._embedded_waiting()
        )
        self._state.update(
            external_sessions=len(active),
            attention="waiting_input" if waiting else "none",
        )

    _refresh_state = refresh_state
