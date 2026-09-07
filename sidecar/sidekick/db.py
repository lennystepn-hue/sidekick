"""SQLite persistence (WAL, single connection guarded by a lock)."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY, cwd TEXT NOT NULL, mode TEXT NOT NULL,
  started_at TEXT NOT NULL, ended_at TEXT
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, role TEXT NOT NULL,
  content TEXT NOT NULL, ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
CREATE TABLE IF NOT EXISTS transcripts (
  id TEXT PRIMARY KEY, raw TEXT NOT NULL, cleaned TEXT NOT NULL, sent INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'reviewing', target TEXT NOT NULL DEFAULT '', ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS btw_exchanges (
  id TEXT PRIMARY KEY, session_id TEXT, question TEXT NOT NULL, answer TEXT NOT NULL, ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hook_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, event TEXT NOT NULL, session_id TEXT,
  payload TEXT NOT NULL, ts TEXT NOT NULL
);
"""

HOOK_EVENT_LIMIT = 500


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        if self.path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # --- sessions -------------------------------------------------------
    def add_session(self, id: str, cwd: str, mode: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO sessions(id, cwd, mode, started_at) VALUES (?,?,?,?)",
                (id, cwd, mode, now_iso()),
            )
            self._conn.commit()

    def end_session(self, id: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE sessions SET ended_at=? WHERE id=?", (now_iso(), id))
            self._conn.commit()

    def list_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM sessions ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # --- messages -------------------------------------------------------
    def add_message(self, session_id: str, role: str, blocks: list[dict[str, Any]]) -> dict[str, Any]:
        ts = now_iso()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO messages(session_id, role, content, ts) VALUES (?,?,?,?)",
                (session_id, role, json.dumps(blocks, ensure_ascii=False), ts),
            )
            self._conn.commit()
            mid = cur.lastrowid
        return {"id": mid, "session_id": session_id, "role": role, "blocks": blocks, "ts": ts}

    def list_messages(self, session_id: str, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        out = [
            {
                "id": r["id"],
                "session_id": r["session_id"],
                "role": r["role"],
                "blocks": json.loads(r["content"]),
                "ts": r["ts"],
            }
            for r in rows
        ]
        out.reverse()
        return out

    # --- transcripts ----------------------------------------------------
    def add_transcript(
        self, id: str, raw: str, cleaned: str, status: str = "reviewing", target: str = ""
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO transcripts(id, raw, cleaned, sent, status, target, ts) VALUES (?,?,?,?,?,?,?)",
                (id, raw, cleaned, 0, status, target, now_iso()),
            )
            self._conn.commit()

    def mark_transcript(
        self, id: str, status: str, sent: bool, target: str | None = None, cleaned: str | None = None
    ) -> None:
        with self._lock:
            if target is None and cleaned is None:
                self._conn.execute(
                    "UPDATE transcripts SET status=?, sent=? WHERE id=?", (status, int(sent), id)
                )
            else:
                row = self._conn.execute(
                    "SELECT target, cleaned FROM transcripts WHERE id=?", (id,)
                ).fetchone()
                if row is None:
                    return
                self._conn.execute(
                    "UPDATE transcripts SET status=?, sent=?, target=?, cleaned=? WHERE id=?",
                    (
                        status,
                        int(sent),
                        target if target is not None else row["target"],
                        cleaned if cleaned is not None else row["cleaned"],
                        id,
                    ),
                )
            self._conn.commit()

    def list_transcripts(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM transcripts ORDER BY ts DESC LIMIT ?", (limit,)
            ).fetchall()
        return [{**dict(r), "sent": bool(r["sent"])} for r in rows]

    # --- btw ------------------------------------------------------------
    def add_btw(self, id: str, session_id: str | None, question: str, answer: str) -> dict[str, Any]:
        ts = now_iso()
        with self._lock:
            self._conn.execute(
                "INSERT INTO btw_exchanges(id, session_id, question, answer, ts) VALUES (?,?,?,?,?)",
                (id, session_id, question, answer, ts),
            )
            self._conn.commit()
        return {"id": id, "session_id": session_id, "question": question, "answer": answer, "ts": ts}

    def list_btw(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM btw_exchanges ORDER BY ts DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # --- hook events (debug ring buffer) --------------------------------
    def add_hook_event(self, event: str, session_id: str | None, payload: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO hook_events(event, session_id, payload, ts) VALUES (?,?,?,?)",
                (event, session_id, json.dumps(payload, ensure_ascii=False)[:20000], now_iso()),
            )
            self._conn.execute(
                "DELETE FROM hook_events WHERE id NOT IN (SELECT id FROM hook_events ORDER BY id DESC LIMIT ?)",
                (HOOK_EVENT_LIMIT,),
            )
            self._conn.commit()

    def list_hook_events(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM hook_events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [{**dict(r), "payload": json.loads(r["payload"])} for r in rows]

    def count_hook_events(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM hook_events").fetchone()[0])
