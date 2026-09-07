"""Embedded Claude Code session driven through the Claude Agent SDK.

Streams assistant text, tool calls and results to the UI, persists messages, and turns
`can_use_tool` callbacks into `PendingPermission`s the UI or the voice pipeline resolves.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from ..config import Settings
from ..db import Database, new_id, now_iso
from ..events import EventBus
from ..state import AppState, SessionInfo

log = logging.getLogger(__name__)

DoneHandler = Callable[[str], Awaitable[None] | None]


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

    def to_dict(self) -> dict[str, Any]:
        return {
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
                texts = [c.get("text", "") for c in content_value if isinstance(c, dict) and c.get("type") == "text"]
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


class EmbeddedSession:
    def __init__(
        self,
        settings: Callable[[], Settings],
        state: AppState,
        bus: EventBus,
        db: Database,
        on_done: DoneHandler | None = None,
        on_needs_input: Callable[[PendingPermission], Awaitable[None] | None] | None = None,
        client_factory: Callable[[Any], Any] | None = None,
    ) -> None:
        self._settings = settings
        self._state = state
        self._bus = bus
        self._db = db
        self._on_done = on_done
        self._on_needs_input = on_needs_input
        self._client_factory = client_factory or self._default_client
        self._client: Any = None
        self._reader: asyncio.Task | None = None
        self.pending: dict[str, PendingPermission] = {}
        self.session_id: str | None = None
        self.sdk_session_id: str | None = None
        self.cwd: str | None = None
        self._last_assistant_text = ""
        self._stream_message_id: str | None = None

    # --- helpers -------------------------------------------------------
    @staticmethod
    def _default_client(options: Any) -> Any:
        from claude_agent_sdk import ClaudeSDKClient

        return ClaudeSDKClient(options)

    def _build_options(self, cwd: str, model: str | None) -> Any:
        from claude_agent_sdk import ClaudeAgentOptions

        cfg = self._settings().claude
        return ClaudeAgentOptions(
            cwd=cwd,
            model=model or cfg.session_model or None,
            permission_mode="default",
            can_use_tool=self._can_use_tool,
            include_partial_messages=True,
            cli_path=cfg.cli_path or None,
        )

    @property
    def running(self) -> bool:
        return self._client is not None and self._reader is not None and not self._reader.done()

    def info(self) -> SessionInfo | None:
        return self._state.session

    # --- lifecycle -----------------------------------------------------
    async def start(self, cwd: str, model: str | None = None) -> SessionInfo:
        if self.running:
            await self.stop()
        self.session_id = new_id()
        self.cwd = cwd
        self._last_assistant_text = ""
        options = self._build_options(cwd, model)
        self._client = self._client_factory(options)
        await self._client.connect()
        info = SessionInfo(
            id=self.session_id, cwd=cwd, mode="embedded", status="idle", model=model or "", started_at=now_iso()
        )
        self._db.add_session(self.session_id, cwd, "embedded")
        self._state.update(session=info, attention="none")
        self._reader = asyncio.create_task(self._read_loop(), name="embedded-reader")
        log.info("embedded session %s started in %s", self.session_id, cwd)
        return info

    async def stop(self) -> None:
        for pending in list(self.pending.values()):
            if not pending.future.done():
                pending.future.set_result(("deny", None, "Session beendet"))
        self.pending.clear()
        if self._reader:
            self._reader.cancel()
            self._reader = None
        client, self._client = self._client, None
        if client is not None:
            try:
                await asyncio.wait_for(client.disconnect(), 5)
            except Exception:  # noqa: BLE001
                pass
        if self.session_id:
            self._db.end_session(self.session_id)
        if self._state.session is not None:
            self._state.update_session(status="stopped")
        self._state.update(attention="none")
        log.info("embedded session stopped")

    async def send(self, text: str) -> None:
        if not self.running or self.session_id is None:
            raise RuntimeError("Keine laufende Session")
        text = text.strip()
        if not text:
            return
        msg = self._db.add_message(self.session_id, "user", [{"type": "text", "text": text}])
        self._bus.publish("message", msg)
        self._state.update_session(status="running")
        await self._client.query(text)

    async def interrupt(self) -> None:
        if self.running:
            await self._client.interrupt()

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
            description=str(getattr(context, "description", None) or getattr(context, "decision_reason", None) or ""),
            suggestions=list(getattr(context, "suggestions", None) or []),
            questions=list((tool_input or {}).get("questions", [])) if kind == "question" else [],
            tool_use_id=getattr(context, "tool_use_id", None),
            future=loop.create_future(),
        )
        self.pending[pending.id] = pending
        self._state.update(attention="waiting_input")
        self._state.update_session(status="waiting")
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
                self._state.update(attention="none")
                self._state.update_session(status="running")
        self._bus.publish("permission_resolved", {"id": pending.id, "decision": decision})
        if decision == "deny":
            return PermissionResultDeny(message=message or "Vom Nutzer abgelehnt")
        updated_input = dict(tool_input or {})
        if kind == "question" and answers:
            updated_input["answers"] = answers
        updated_permissions = pending.suggestions if decision == "allow_always" and pending.suggestions else None
        return PermissionResultAllow(updated_input=updated_input, updated_permissions=updated_permissions)

    def resolve_permission(
        self, pending_id: str, decision: str, answers: dict[str, Any] | None = None, message: str | None = None
    ) -> bool:
        if decision not in ("allow", "deny", "allow_always"):
            raise ValueError("decision must be allow, deny or allow_always")
        pending = self.pending.get(pending_id)
        if pending is None or pending.future.done():
            return False
        pending.future.set_result((decision, answers, message))
        return True

    def oldest_pending(self) -> PendingPermission | None:
        if not self.pending:
            return None
        return min(self.pending.values(), key=lambda p: p.ts)

    # --- reading -------------------------------------------------------
    async def _read_loop(self) -> None:
        try:
            async for message in self._client.receive_messages():
                try:
                    await self._handle(message)
                except Exception:  # noqa: BLE001
                    log.exception("failed to handle sdk message")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.error("embedded session reader ended: %s", exc)
            self._bus.publish("error", {"module": "session", "message": f"Session abgebrochen: {exc}"})
            if self._state.session is not None:
                self._state.update_session(status="stopped")

    async def _handle(self, message: Any) -> None:
        from claude_agent_sdk import AssistantMessage, ResultMessage, StreamEvent, SystemMessage, UserMessage

        sid = self.session_id or ""
        if isinstance(message, StreamEvent):
            ev = message.event or {}
            etype = ev.get("type")
            if etype == "message_start":
                self._stream_message_id = (ev.get("message") or {}).get("id") or new_id()
            elif etype == "content_block_delta":
                delta = ev.get("delta") or {}
                if delta.get("type") == "text_delta" and delta.get("text"):
                    self._bus.publish(
                        "assistant_delta",
                        {"session_id": sid, "message_id": self._stream_message_id or "stream", "text": delta["text"]},
                    )
            elif etype == "message_stop":
                self._bus.publish("assistant_stream_end", {"session_id": sid, "message_id": self._stream_message_id or "stream"})
                self._stream_message_id = None
            return
        if isinstance(message, SystemMessage):
            if message.subtype == "init":
                self.sdk_session_id = (message.data or {}).get("session_id")
            return
        if isinstance(message, AssistantMessage):
            blocks = [b for b in blocks_from_content(message.content) if not (b["type"] == "thinking" and not b.get("text"))]
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
            self.sdk_session_id = message.session_id or self.sdk_session_id
            self._state.update_session(status="idle")
            final = self._last_assistant_text or (message.result or "")
            if message.is_error:
                self._bus.publish("error", {"module": "session", "message": message.result or message.subtype})
            if self._on_done is not None:
                try:
                    result = self._on_done(final)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:  # noqa: BLE001
                    log.exception("on_done failed")
            return
