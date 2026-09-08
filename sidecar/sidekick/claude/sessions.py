"""Several embedded sessions at once, one of them active for voice input and the UI.

Sessions are persisted in SQLite (with the Claude Code session id), so a stopped session
can be resumed later with the full conversation. `AppState.sessions` carries the list of
summaries and `AppState.session` mirrors the active session.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from ..config import Settings
from ..db import Database
from ..events import EventBus
from ..state import AppState
from .embedded import EmbeddedSession, PendingPermission

log = logging.getLogger(__name__)

DoneHook = Callable[[str, EmbeddedSession], Awaitable[None] | None]
NeedsInputHook = Callable[[PendingPermission, EmbeddedSession], Awaitable[None] | None]


class SessionManager:
    def __init__(
        self,
        settings: Callable[[], Settings],
        state: AppState,
        bus: EventBus,
        db: Database,
        on_done: DoneHook | None = None,
        on_needs_input: NeedsInputHook | None = None,
        attention_refresh: Callable[[], None] | None = None,
        client_factory: Callable[[Any], Any] | None = None,
    ) -> None:
        self._settings = settings
        self._state = state
        self._bus = bus
        self._db = db
        self._on_done = on_done
        self._on_needs_input = on_needs_input
        self._attention_refresh = attention_refresh
        self._client_factory = client_factory
        self.live: dict[str, EmbeddedSession] = {}
        self.active_id: str | None = None
        self._lock = asyncio.Lock()

    # --- queries --------------------------------------------------------
    @property
    def active(self) -> EmbeddedSession | None:
        if self.active_id is None:
            return None
        return self.live.get(self.active_id)

    def get(self, session_id: str) -> EmbeddedSession | None:
        return self.live.get(session_id)

    def running(self) -> list[EmbeddedSession]:
        return [s for s in self.live.values() if s.running]

    def any_pending(self) -> bool:
        return any(s.pending for s in self.live.values())

    def sdk_ids(self) -> set[str]:
        return {s.sdk_session_id for s in self.live.values() if s.sdk_session_id}

    def find_pending(self, pending_id: str) -> tuple[EmbeddedSession, PendingPermission] | None:
        for s in self.live.values():
            p = s.pending.get(pending_id)
            if p is not None:
                return s, p
        return None

    def messages(self, session_id: str, limit: int = 200) -> list[dict[str, Any]]:
        return self._db.list_messages(session_id, limit)

    def summaries(self) -> list[dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        order: dict[str, int] = {}  # DB order (newest rowid first) breaks last_active ties
        for index, row in enumerate(self._db.list_sessions(200)):
            order[row["id"]] = index
            out[row["id"]] = {
                "id": row["id"],
                "cwd": row["cwd"],
                "title": row.get("title") or row["cwd"],
                "mode": row.get("mode") or "embedded",
                "status": "stopped",
                "model": row.get("model") or "",
                "permission_mode": row.get("permission_mode") or "",
                "started_at": row.get("started_at") or "",
                "last_active": row.get("last_active") or row.get("started_at") or "",
                "sdk_session_id": row.get("sdk_session_id"),
                "message_count": self._db.count_messages(row["id"]),
                "pending": 0,
                "resumable": bool(row.get("sdk_session_id")),
            }
        for s in self.live.values():
            summary = s.summary()
            if summary:
                out[summary["id"]] = summary
        return sorted(
            out.values(), key=lambda d: (d["last_active"] or "", -order.get(d["id"], 0)), reverse=True
        )

    def summary(self, session_id: str) -> dict[str, Any] | None:
        for d in self.summaries():
            if d["id"] == session_id:
                return d
        return None

    # --- state publishing -----------------------------------------------
    def publish(self) -> None:
        active = self.active
        self._state.update(
            sessions=self.summaries(),
            active_session_id=self.active_id,
            session=active.info if active is not None else None,
        )

    def _on_change(self, _session: EmbeddedSession) -> None:
        self.publish()

    # --- lifecycle --------------------------------------------------------
    def load(self) -> None:
        """Publish the persisted sessions (all stopped) at startup."""
        rows = self._db.list_sessions(1)
        if rows and self.active_id is None:
            self.active_id = rows[0]["id"]  # last used session is preselected (not resumed yet)
        self.publish()

    def _new(self, session_id: str | None) -> EmbeddedSession:
        holder: dict[str, EmbeddedSession] = {}

        async def on_done(text: str) -> None:
            if self._on_done is not None:
                result = self._on_done(text, holder["s"])
                if asyncio.iscoroutine(result):
                    await result

        async def on_needs_input(pending: PendingPermission) -> None:
            if self._on_needs_input is not None:
                result = self._on_needs_input(pending, holder["s"])
                if asyncio.iscoroutine(result):
                    await result

        session = EmbeddedSession(
            self._settings,
            self._state,
            self._bus,
            self._db,
            on_done,
            on_needs_input,
            client_factory=self._client_factory,
            attention_refresh=self._attention_refresh,
            notify=self._on_change,
            session_id=session_id,
        )
        holder["s"] = session
        return session

    async def create(self, cwd: str, model: str | None = None, title: str | None = None) -> EmbeddedSession:
        async with self._lock:
            session = self._new(None)
            await session.start(cwd, model, title=title)
            self.live[session.session_id] = session  # type: ignore[index]
            self.active_id = session.session_id
            self.publish()
            return session

    async def resume(self, session_id: str) -> EmbeddedSession:
        async with self._lock:
            live = self.live.get(session_id)
            if live is not None and live.running:
                self.active_id = session_id
                self.publish()
                return live
            row = self._db.get_session(session_id)
            if row is None:
                raise KeyError(session_id)
            sdk_id = (live.sdk_session_id if live else None) or row.get("sdk_session_id")
            if not sdk_id:
                raise RuntimeError("Session kann nicht fortgesetzt werden (keine Claude-Code-Session-ID)")
            if live is not None:
                await live.stop()
            session = self._new(session_id)
            session.title_auto = bool(row.get("title_auto", 1))
            await session.start(
                row["cwd"], row.get("model") or None, resume=sdk_id, title=row.get("title") or None
            )
            self.live[session_id] = session
            self.active_id = session_id
            self.publish()
            return session

    async def activate(self, session_id: str) -> dict[str, Any]:
        live = self.live.get(session_id)
        if live is not None and live.running:
            self.active_id = session_id
            self.publish()
        else:
            row = self._db.get_session(session_id)
            if row is None:
                raise KeyError(session_id)
            if (live.sdk_session_id if live else None) or row.get("sdk_session_id"):
                await self.resume(session_id)
            else:
                self.active_id = session_id
                self.publish()
        return self.summary(session_id) or {}

    async def stop(self, session_id: str) -> bool:
        live = self.live.get(session_id)
        if live is None:
            return False
        await live.stop()
        self.publish()
        return True

    async def delete(self, session_id: str) -> None:
        live = self.live.pop(session_id, None)
        if live is not None:
            await live.stop()
        self._db.delete_session(session_id)
        if self.active_id == session_id:
            self.active_id = None
            rows = self._db.list_sessions(1)
            if rows:
                self.active_id = rows[0]["id"]
        self.publish()

    def rename(self, session_id: str, title: str) -> dict[str, Any] | None:
        live = self.live.get(session_id)
        if live is not None:
            live.rename(title)
        else:
            if self._db.get_session(session_id) is None:
                return None
            self._db.update_session(session_id, title=" ".join(title.split())[:60], title_auto=False)
        self.publish()
        return self.summary(session_id)

    async def stop_all(self) -> None:
        for session in list(self.live.values()):
            if session.client_active:
                try:
                    await session.stop()
                except Exception:  # noqa: BLE001
                    log.exception("stopping session %s failed", session.session_id)

    def on_settings_changed(self, old: Settings, new: Settings) -> None:
        for session in self.live.values():
            session.on_settings_changed(old, new)
