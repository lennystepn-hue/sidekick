"""Embedded Claude Code session driven through the Claude Agent SDK.

Streams assistant text, tool calls and results to the UI, persists messages, and turns
`can_use_tool` callbacks into `PendingPermission`s the UI or the voice pipeline resolves.
Several sessions can run at once (see `sessions.SessionManager`); each instance owns its
`info` and reports changes through `notify`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from ..config import Settings
from ..db import Database, new_id, now_iso
from ..events import EventBus
from ..state import AppState, SessionInfo
from .idea import IdeaState, StreamFilter, split_idea_block

log = logging.getLogger(__name__)

DoneHandler = Callable[[str], Awaitable[None] | None]
LimitHandler = Callable[[dict[str, Any]], Awaitable[None] | None]
SETTING_SOURCES = ["user", "project", "local"]
TITLE_MAX = 60
BRAINSTORM_PROMPT = "brainstorm"


@dataclass
class PendingPermission:
    id: str
    session_id: str
    kind: str  # "permission" | "question"
    tool_name: str
    input: dict[str, Any]
    title: str
    description: str
    suggestions: list[Any]
    questions: list[dict[str, Any]]
    tool_use_id: str | None
    future: asyncio.Future = field(repr=False)
    ts: float = field(default_factory=time.time)
    snoozed_until: float | None = None

    @property
    def snoozed(self) -> bool:
        return self.snoozed_until is not None and self.snoozed_until > time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "snoozed_until": self.snoozed_until,
            "id": self.id,
            "session_id": self.session_id,
            "kind": self.kind,
            "tool_name": self.tool_name,
            "input": self.input,
            "title": self.title,
            "description": self.description,
            "suggestions": [_jsonable(s) for s in self.suggestions],
            "questions": self.questions,
            "tool_use_id": self.tool_use_id,
            "ts": self.ts,
        }


def _jsonable(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        from dataclasses import asdict

        return asdict(value)
    return value


def blocks_from_content(content: Any) -> list[dict[str, Any]]:
    """Convert SDK content blocks (or a plain string) into the UI's Block dicts."""
    from claude_agent_sdk import TextBlock, ThinkingBlock, ToolResultBlock, ToolUseBlock

    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    out: list[dict[str, Any]] = []
    for block in content or []:
        if isinstance(block, TextBlock):
            out.append({"type": "text", "text": block.text})
        elif isinstance(block, ThinkingBlock):
            out.append({"type": "thinking", "text": block.thinking})
        elif isinstance(block, ToolUseBlock):
            out.append({"type": "tool_use", "id": block.id, "name": block.name, "input": block.input})
        elif isinstance(block, ToolResultBlock):
            content_value = block.content
            if isinstance(content_value, list):
                texts = [
                    c.get("text", "")
                    for c in content_value
                    if isinstance(c, dict) and c.get("type") == "text"
                ]
                content_value = "\n".join(texts) if texts else str(content_value)
            out.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.tool_use_id,
                    "content": content_value if content_value is not None else "",
                    "is_error": bool(block.is_error),
                }
            )
        elif isinstance(block, dict):
            out.append(block)
    return out


_LIMIT_WORDS = ("usage limit", "rate limit", "nutzungslimit", "limit reached", "limit erreicht")


def is_limit_error(text: str) -> bool:
    """A failed turn that was really the account's usage limit."""
    low = (text or "").lower()
    return any(w in low for w in _LIMIT_WORDS)


def auto_title(text: str) -> str:
    first = " ".join(text.strip().split())
    return first if len(first) <= TITLE_MAX else first[: TITLE_MAX - 1] + "…"


class EmbeddedSession:
    def __init__(
        self,
        settings: Callable[[], Settings],
        state: AppState,
        bus: EventBus,
        db: Database,
        on_done: DoneHandler | None = None,
        on_needs_input: Callable[[PendingPermission], Awaitable[None] | None] | None = None,
        on_limit: LimitHandler | None = None,
        client_factory: Callable[[Any], Any] | None = None,
        attention_refresh: Callable[[], None] | None = None,
        notify: Callable[[EmbeddedSession], None] | None = None,
        session_id: str | None = None,
    ) -> None:
        self._settings = settings
        self._state = state
        self._bus = bus
        self._db = db
        self._on_done = on_done
        self._on_needs_input = on_needs_input
        self._on_limit = on_limit
        self._client_factory = client_factory or self._default_client
        self._attention_refresh = attention_refresh
        self._notify_cb = notify
        self._client: Any = None
        self._reader: asyncio.Task | None = None
        self.pending: dict[str, PendingPermission] = {}
        self.session_id: str | None = session_id
        self.sdk_session_id: str | None = None
        self.cwd: str | None = None
        self.info: SessionInfo | None = None
        self.title_auto = True
        self.kind: str = "code"
        self.idea: IdeaState | None = None
        self.project_path: str | None = None
        self.adopted_from: str | None = None  # terminal session id this one was forked from
        self._last_assistant_text = ""
        self._stream_message_id: str | None = None
        self._stream_filter: StreamFilter | None = None
        self._interrupted = False

    # --- helpers -------------------------------------------------------
    @staticmethod
    def _default_client(options: Any) -> Any:
        from claude_agent_sdk import ClaudeSDKClient

        return ClaudeSDKClient(options)

    @property
    def is_brainstorm(self) -> bool:
        return self.kind == "brainstorm"

    def _build_options(self, cwd: str, model: str | None, resume: str | None) -> Any:
        from claude_agent_sdk import ClaudeAgentOptions

        from .utility import cli_stderr, load_prompt

        settings = self._settings()
        cfg = settings.claude
        if self.is_brainstorm:
            # A conversation partner without tools or project settings: the system prompt
            # replaces Claude Code's, nothing from the scratch cwd leaks in.
            bs = settings.brainstorm
            return ClaudeAgentOptions(
                cwd=cwd,
                model=model or bs.model or None,
                system_prompt=load_prompt(BRAINSTORM_PROMPT),
                tools=[],
                allowed_tools=[],
                setting_sources=[],
                strict_mcp_config=True,
                thinking={"type": "adaptive"} if bs.thinking else {"type": "disabled"},
                permission_mode="dontAsk",
                include_partial_messages=True,
                cli_path=cfg.cli_path or None,
                resume=resume or None,
                env={"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"},
                stderr=cli_stderr,  # piped stderr; inheriting ours fails in the packaged app
            )
        return ClaudeAgentOptions(
            cwd=cwd,
            model=model or cfg.session_model or None,
            permission_mode=cfg.permission_mode,
            can_use_tool=self._can_use_tool,
            include_partial_messages=True,
            setting_sources=list(SETTING_SOURCES),
            cli_path=cfg.cli_path or None,
            resume=resume or None,
            fork_session=bool(resume) and getattr(self, "_fork", False),
            stderr=cli_stderr,
        )

    @property
    def running(self) -> bool:
        return self._client is not None and self._reader is not None and not self._reader.done()

    @property
    def client_active(self) -> bool:
        """A CLI process may still be attached even after the reader ended."""
        return self._client is not None

    @property
    def title(self) -> str:
        return self.info.title if self.info else ""

    def _notify(self) -> None:
        if self._notify_cb is not None:
            self._notify_cb(self)
        else:  # standalone use (tests): mirror into the single state slot
            self._state.update(session=self.info)

    def _set(self, **fields: Any) -> None:
        if self.info is None:
            return
        new = replace(self.info, **fields)
        if new == self.info:
            return
        self.info = new
        self._notify()

    def _clear_attention(self) -> None:
        if self._attention_refresh is not None:
            self._attention_refresh()
        else:
            self._state.update(attention="none")

    def summary(self) -> dict[str, Any]:
        info = self.info
        if info is None:
            return {}
        return {
            "id": info.id,
            "cwd": info.cwd,
            "title": info.title,
            "mode": info.mode,
            "status": info.status,
            "model": info.model,
            "permission_mode": info.permission_mode,
            "started_at": info.started_at,
            "last_active": info.last_active,
            "sdk_session_id": info.sdk_session_id,
            "message_count": self._db.count_messages(info.id),
            "pending": len(self.pending),
            "resumable": bool(info.sdk_session_id) and not self.running,
            "kind": info.kind,
            "project_path": info.project_path,
            "idea": self.idea.to_dict() if self.idea is not None else None,
        }

    # --- lifecycle -----------------------------------------------------
    async def start(
        self,
        cwd: str,
        model: str | None = None,
        resume: str | None = None,
        title: str | None = None,
        kind: str = "code",
        project_path: str | None = None,
        idea: IdeaState | None = None,
        fork: bool = False,
    ) -> SessionInfo:
        if self._client is not None:
            await self.stop()
        self._fork = fork
        self.session_id = self.session_id or new_id()
        self.sdk_session_id = resume
        self.cwd = cwd
        self.kind = kind
        self.project_path = project_path
        self.idea = idea
        self._last_assistant_text = ""
        self._interrupted = False
        # Brainstorms keep an automatic title as long as the user never renamed them: the
        # partner's idea title replaces the placeholder, not the first spoken sentence.
        self.title_auto = not title or (self.is_brainstorm and title == "Brainstorm")
        options = self._build_options(cwd, model, resume)
        client = self._client_factory(options)
        await client.connect()
        self._client = client
        settings = self._settings()
        cfg = settings.claude
        now = now_iso()
        if self.is_brainstorm:
            model = model or settings.brainstorm.model
            title = title or (idea.title if idea and idea.title else "Brainstorm")
        permission_mode = "dontAsk" if self.is_brainstorm else cfg.permission_mode
        self.info = SessionInfo(
            id=self.session_id,
            cwd=cwd,
            mode="embedded",
            status="idle",
            model=model or "",
            started_at=now,
            permission_mode=permission_mode,
            title=title or Path(cwd).name or cwd,
            sdk_session_id=resume,
            last_active=now,
            kind=kind,  # type: ignore[arg-type]
            project_path=project_path,
        )
        self._db.add_session(
            self.session_id,
            cwd,
            "embedded",
            title=self.info.title,
            model=model or "",
            permission_mode=permission_mode,
            sdk_session_id=resume,
            title_auto=self.title_auto,
            kind=kind,
        )
        self._notify()
        self._clear_attention()
        self._reader = asyncio.create_task(self._read_loop(), name=f"embedded-{self.session_id}")
        log.info("embedded session %s %s in %s", self.session_id, "resumed" if resume else "started", cwd)
        return self.info

    async def stop(self) -> None:
        for pending in list(self.pending.values()):
            if not pending.future.done():
                pending.future.set_result(("deny", None, "Session beendet"))
        self.pending.clear()
        reader, self._reader = self._reader, None
        if reader is not None and not reader.done():
            reader.cancel()
        client, self._client = self._client, None
        if client is not None:
            try:
                await asyncio.wait_for(client.disconnect(), 5)
            except Exception:  # noqa: BLE001
                pass
        if self.session_id:
            self._db.end_session(self.session_id)
        self._set(status="stopped")
        self._clear_attention()
        log.info("embedded session %s stopped", self.session_id)

    async def send(self, text: str) -> None:
        if not self.running or self.session_id is None:
            raise RuntimeError("Keine laufende Session")
        text = text.strip()
        if not text:
            return
        msg = self._db.add_message(self.session_id, "user", [{"type": "text", "text": text}])
        self._bus.publish("message", msg)
        fields: dict[str, Any] = {"status": "running", "last_active": now_iso()}
        if self.title_auto and self.info is not None and not self.is_brainstorm:
            fields["title"] = auto_title(text)
            self.title_auto = False
            self._db.update_session(self.session_id, title=fields["title"], title_auto=False)
        self._db.update_session(self.session_id, last_active=fields["last_active"])
        self._set(**fields)
        self._interrupted = False
        await self._client.query(text)

    def rename(self, title: str) -> None:
        title = " ".join(title.split())[:TITLE_MAX] or (self.info.title if self.info else "")
        self.title_auto = False
        if self.session_id:
            self._db.update_session(self.session_id, title=title, title_auto=False)
        self._set(title=title)

    async def interrupt(self) -> None:
        if self.running:
            self._interrupted = True
            await self._client.interrupt()

    async def set_model(self, model: str) -> None:
        """Switch the model of this session. Empty string = whatever Claude Code defaults to.
        Works while a session runs (verified against the CLI); stopped sessions keep it for
        the next resume."""
        model = (model or "").strip()
        if self.running and hasattr(self._client, "set_model"):
            await self._client.set_model(model or None)
            log.info("session %s switched to model %s", self.session_id, model or "(default)")
        if self.session_id:
            self._db.update_session(self.session_id, model=model)
        self._set(model=model)

    async def set_permission_mode(self, mode: str) -> None:
        """Switch the running session's permission mode (settings change)."""
        if self.running and hasattr(self._client, "set_permission_mode"):
            await self._client.set_permission_mode(mode)
            log.info("permission mode of %s switched to %s", self.session_id, mode)
            self._set(permission_mode=mode)

    def on_settings_changed(self, old: Settings, new: Settings) -> None:
        if self.is_brainstorm:
            return
        if old.claude.permission_mode != new.claude.permission_mode and self.running:
            asyncio.ensure_future(self.set_permission_mode(new.claude.permission_mode))

    # --- brainstorm ----------------------------------------------------
    def set_project_path(self, path: str | None) -> None:
        self.project_path = path
        if self.session_id:
            self._db.update_session(self.session_id, project_path=path)
        self._set(project_path=path)

    def _apply_idea(self, data: dict[str, Any] | None) -> None:
        if not data:
            return
        idea = IdeaState.from_dict(data, now_iso())
        if idea.is_empty and self.idea is not None:
            return  # a degenerate block never wipes a good state
        self.idea = idea
        if not self.session_id:
            return
        fields: dict[str, Any] = {"idea_state": json.dumps(idea.to_dict(), ensure_ascii=False)}
        if self.title_auto and idea.title:
            fields["title"] = " ".join(idea.title.split())[:TITLE_MAX]
        self._db.update_session(self.session_id, **fields)
        if "title" in fields:
            self._set(title=fields["title"])
        self._notify()
        self._bus.publish("idea_state", {"session_id": self.session_id, "state": idea.to_dict()})

    # --- permissions ---------------------------------------------------
    async def _can_use_tool(self, tool_name: str, tool_input: dict[str, Any], context: Any) -> Any:
        from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

        loop = asyncio.get_running_loop()
        kind = "question" if tool_name == "AskUserQuestion" else "permission"
        pending = PendingPermission(
            id=new_id(),
            session_id=self.session_id or "",
            kind=kind,
            tool_name=tool_name,
            input=tool_input or {},
            title=str(getattr(context, "title", None) or getattr(context, "display_name", None) or tool_name),
            description=str(
                getattr(context, "description", None) or getattr(context, "decision_reason", None) or ""
            ),
            suggestions=list(getattr(context, "suggestions", None) or []),
            questions=list((tool_input or {}).get("questions", [])) if kind == "question" else [],
            tool_use_id=getattr(context, "tool_use_id", None),
            future=loop.create_future(),
        )
        self.pending[pending.id] = pending
        self._state.update(attention="waiting_input")
        self._set(status="waiting")
        self._bus.publish("permission_request", pending.to_dict())
        if self._on_needs_input is not None:
            try:
                result = self._on_needs_input(pending)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:  # noqa: BLE001
                log.exception("on_needs_input failed")
        try:
            decision, answers, message = await pending.future
        finally:
            self.pending.pop(pending.id, None)
            if not self.pending:
                if self.info is not None and self.info.status == "waiting":
                    self._set(status="running")
                self._clear_attention()
            else:
                self._notify()
        self._bus.publish("permission_resolved", {"id": pending.id, "decision": decision})
        if decision == "deny":
            return PermissionResultDeny(message=message or "Vom Nutzer abgelehnt")
        updated_input = dict(tool_input or {})
        if kind == "question" and answers:
            updated_input["answers"] = answers
        updated_permissions = (
            pending.suggestions if decision == "allow_always" and pending.suggestions else None
        )
        return PermissionResultAllow(updated_input=updated_input, updated_permissions=updated_permissions)

    def resolve_permission(
        self,
        pending_id: str,
        decision: str,
        answers: dict[str, Any] | None = None,
        message: str | None = None,
    ) -> bool:
        if decision not in ("allow", "deny", "allow_always", "defer", "wake"):
            raise ValueError("decision must be allow, deny, allow_always, defer or wake")
        pending = self.pending.get(pending_id)
        if pending is None or pending.future.done():
            return False
        if decision == "defer":
            minutes = max(1, int(self._settings().claude.defer_minutes))
            pending.snoozed_until = time.time() + 60 * minutes
            self._clear_attention()
            self._notify()
            self._bus.publish(
                "permission_deferred",
                {"id": pending.id, "session_id": self.session_id, "until": pending.snoozed_until},
            )
            log.info("permission %s deferred for %d min", pending.id, minutes)
            return True
        if decision == "wake":
            self._wake(pending, announce=False)
            return True
        pending.future.set_result((decision, answers, message))
        return True

    def _wake(self, pending: PendingPermission, announce: bool) -> None:
        pending.snoozed_until = None
        self._state.update(attention="waiting_input")
        self._notify()
        self._bus.publish("permission_woken", {"id": pending.id, "session_id": self.session_id})
        if announce and self._on_needs_input is not None:
            asyncio.ensure_future(self._announce(pending))

    async def _announce(self, pending: PendingPermission) -> None:
        try:
            result = self._on_needs_input(pending)  # type: ignore[misc]
            if asyncio.iscoroutine(result):
                await result
        except Exception:  # noqa: BLE001
            log.exception("re-announce failed")

    def tick_snoozes(self, now: float | None = None) -> list[str]:
        """Wake deferred permissions whose snooze ran out; returns their ids."""
        now = time.time() if now is None else now
        woken: list[str] = []
        for pending in list(self.pending.values()):
            if (
                pending.snoozed_until is not None
                and pending.snoozed_until <= now
                and not pending.future.done()
            ):
                self._wake(pending, announce=True)
                woken.append(pending.id)
        return woken

    def wake_all(self) -> list[str]:
        return self.tick_snoozes(now=float("inf"))

    def any_pending_active(self) -> bool:
        return any(not p.snoozed for p in self.pending.values())

    def oldest_pending(self) -> PendingPermission | None:
        """The oldest request that is not snoozed (a spoken "ja" never hits a deferred one)."""
        candidates = [p for p in self.pending.values() if not p.snoozed]
        if not candidates:
            return None
        return min(candidates, key=lambda p: p.ts)

    # --- reading -------------------------------------------------------
    async def _read_loop(self) -> None:
        client = self._client
        ended_unexpectedly = False
        try:
            async for message in client.receive_messages():
                try:
                    await self._handle(message)
                except Exception:  # noqa: BLE001
                    log.exception("failed to handle sdk message")
            ended_unexpectedly = self._client is client
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            ended_unexpectedly = self._client is client
            if ended_unexpectedly:
                log.error("embedded session reader ended: %s", exc)
                self._bus.publish("error", {"module": "session", "message": f"Session abgebrochen: {exc}"})
        finally:
            if ended_unexpectedly:
                log.warning("embedded session %s CLI exited", self.session_id)
                for pending in list(self.pending.values()):
                    if not pending.future.done():
                        pending.future.set_result(("deny", None, "Session beendet"))
                self.pending.clear()
                self._set(status="stopped")
                self._clear_attention()

    def _strip_idea_blocks(self, blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Remove the idea-state block from text blocks and apply it; drop emptied blocks."""
        out: list[dict[str, Any]] = []
        for block in blocks:
            if block["type"] != "text":
                out.append(block)
                continue
            visible, data = split_idea_block(block.get("text") or "")
            if data is not None:
                self._apply_idea(data)
            if visible:
                out.append({**block, "text": visible})
        return out

    async def _handle_rate_limit(self, message: Any) -> None:
        info = message.rate_limit_info
        raw = getattr(info, "raw", None) or {}
        windows = {
            name: {"utilization": w.get("utilization"), "resets_at": w.get("resetsAt")}
            for name, w in (raw.get("unifiedWindows") or {}).items()
            if isinstance(w, dict)
        }
        data = {
            "status": info.status,
            "resets_at": info.resets_at,
            "rate_limit_type": info.rate_limit_type,
            "utilization": info.utilization,
            "windows": windows,
            "session_id": self.session_id,
            "ts": time.time(),
        }
        self._state.update(rate_limit=data)
        if self._on_limit is not None:
            try:
                result = self._on_limit(data)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:  # noqa: BLE001
                log.exception("on_limit failed")

    def _record_sdk_id(self, sdk_id: str | None) -> None:
        if sdk_id and sdk_id != self.sdk_session_id:
            self.sdk_session_id = sdk_id
            if self.session_id:
                self._db.update_session(self.session_id, sdk_session_id=sdk_id)
            self._set(sdk_session_id=sdk_id)

    async def _handle(self, message: Any) -> None:
        from claude_agent_sdk import (
            AssistantMessage,
            RateLimitEvent,
            ResultMessage,
            StreamEvent,
            SystemMessage,
            UserMessage,
        )

        sid = self.session_id or ""
        if isinstance(message, RateLimitEvent):
            await self._handle_rate_limit(message)
            return
        if isinstance(message, StreamEvent):
            ev = message.event or {}
            etype = ev.get("type")
            if etype == "message_start":
                self._stream_message_id = (ev.get("message") or {}).get("id") or new_id()
                self._stream_filter = StreamFilter() if self.is_brainstorm else None
            elif etype == "content_block_delta":
                delta = ev.get("delta") or {}
                if delta.get("type") == "text_delta" and delta.get("text"):
                    text = delta["text"]
                    if self._stream_filter is not None:
                        text = self._stream_filter.feed(text)
                    if text:
                        self._bus.publish(
                            "assistant_delta",
                            {
                                "session_id": sid,
                                "message_id": self._stream_message_id or "stream",
                                "text": text,
                            },
                        )
            elif etype == "message_stop":
                self._bus.publish(
                    "assistant_stream_end",
                    {"session_id": sid, "message_id": self._stream_message_id or "stream"},
                )
                self._stream_message_id = None
                self._stream_filter = None
            return
        if isinstance(message, SystemMessage):
            if message.subtype == "init":
                self._record_sdk_id((message.data or {}).get("session_id"))
            return
        if isinstance(message, AssistantMessage):
            blocks = [
                b
                for b in blocks_from_content(message.content)
                if not (b["type"] == "thinking" and not b.get("text"))
            ]
            if not blocks:
                return
            if self.is_brainstorm:
                blocks = self._strip_idea_blocks(blocks)
                if not blocks:
                    return
            text = "\n".join(b["text"] for b in blocks if b["type"] == "text").strip()
            if text:
                self._last_assistant_text = text
            msg = self._db.add_message(sid, "assistant", blocks)
            # The SDK emits one AssistantMessage per content block; all of them belong to the
            # API message whose id the deltas carried, so keep the id until message_stop.
            msg["stream_id"] = self._stream_message_id
            self._bus.publish("message", msg)
            return
        if isinstance(message, UserMessage):
            blocks = blocks_from_content(message.content)
            if any(b["type"] == "tool_result" for b in blocks):
                msg = self._db.add_message(sid, "tool", blocks)
                self._bus.publish("message", msg)
            return
        if isinstance(message, ResultMessage):
            self._record_sdk_id(message.session_id)
            now = now_iso()
            if self.session_id:
                self._db.update_session(self.session_id, last_active=now)
            self._set(status="idle", last_active=now)
            final = self._last_assistant_text or (message.result or "")
            interrupted, self._interrupted = self._interrupted, False
            if message.is_error:
                text = message.result or message.subtype or ""
                self._bus.publish("error", {"module": "session", "message": text})
                if is_limit_error(text) and self._on_limit is not None:
                    result = self._on_limit({"status": "rejected", "reason": text, "ts": time.time()})
                    if asyncio.iscoroutine(result):
                        await result
                return
            if interrupted:
                log.info("turn interrupted; not announcing")
                return
            if self._on_done is not None:
                try:
                    result = self._on_done(final)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:  # noqa: BLE001
                    log.exception("on_done failed")
            return
