"""Sidekick channel hub: terminal sessions that run the Sidekick channel server connect here.

The channel server (channels/sidekick, a Claude Code channel) opens a WebSocket to the
sidecar. Through it Sidekick pushes spoken text straight into the terminal session,
receives that session's permission prompts (relay) so the glasses can ask and a spoken
"ja"/"nein" answers them, and speaks replies Claude sends through the `reply` tool.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from ..config import Settings
from ..db import new_id
from ..events import EventBus
from ..state import AppState
from .summarize import Summarizer

log = logging.getLogger(__name__)

Sender = Callable[[dict[str, Any]], Awaitable[None]]
RELAY_TTL_S = 15 * 60


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(path)) if path else ""


@dataclass
class Channel:
    id: str
    cwd: str
    pid: int
    name: str
    version: str
    send: Sender = field(repr=False)
    connected_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "cwd": self.cwd,
            "pid": self.pid,
            "name": self.name,
            "version": self.version,
            "connected_at": self.connected_at,
        }


@dataclass
class RelayRequest:
    request_id: str
    channel_id: str
    tool_name: str
    description: str
    input_preview: str
    spoken: str = ""
    ts: float = field(default_factory=time.time)
    snoozed_until: float | None = None

    @property
    def snoozed(self) -> bool:
        return self.snoozed_until is not None and self.snoozed_until > time.time()

    def to_dict(self) -> dict[str, Any]:
        """Shaped like an embedded PermissionRequest so the UI can reuse its card."""
        return {
            "id": self.request_id,
            "session_id": f"channel:{self.channel_id}",
            "kind": "permission",
            "source": "channel",
            "tool_name": self.tool_name,
            "input": {"preview": self.input_preview},
            "title": self.tool_name,
            "description": self.description,
            "suggestions": [],
            "questions": [],
            "tool_use_id": None,
            "ts": self.ts,
            "snoozed_until": self.snoozed_until,
        }


class ChannelHub:
    def __init__(
        self,
        state: AppState,
        bus: EventBus,
        settings: Callable[[], Settings],
        sounds: Any,
        speaker: Any,
        summarizer: Summarizer,
        attention_refresh: Callable[[], None] | None = None,
    ) -> None:
        self._state = state
        self._bus = bus
        self._settings = settings
        self._sounds = sounds
        self._speaker = speaker
        self._summarizer = summarizer
        self._attention_refresh = attention_refresh
        self.channels: dict[str, Channel] = {}
        self.relays: dict[str, RelayRequest] = {}

    # --- queries ---------------------------------------------------------
    def cwds(self) -> set[str]:
        return {_norm(c.cwd) for c in self.channels.values() if c.cwd}

    def for_cwd(self, cwd: str | None) -> Channel | None:
        if not cwd:
            return None
        target = _norm(cwd)
        matches = [c for c in self.channels.values() if _norm(c.cwd) == target]
        return max(matches, key=lambda c: c.connected_at) if matches else None

    def latest(self) -> Channel | None:
        if not self.channels:
            return None
        return max(self.channels.values(), key=lambda c: c.connected_at)

    def pick(self, cwd: str | None) -> Channel | None:
        """The channel of the given project, else the most recently connected one."""
        return self.for_cwd(cwd) or self.latest()

    def any_active(self) -> bool:
        return any(not r.snoozed for r in self.relays.values())

    def oldest_relay(self) -> RelayRequest | None:
        open_ = [r for r in self.relays.values() if not r.snoozed]
        return min(open_, key=lambda r: r.ts) if open_ else None

    def status(self) -> dict[str, Any]:
        return {
            "connections": [
                c.to_dict() for c in sorted(self.channels.values(), key=lambda c: c.connected_at)
            ],
            "pending": [r.to_dict() for r in sorted(self.relays.values(), key=lambda r: r.ts)],
        }

    # --- lifecycle -------------------------------------------------------
    async def connect(self, hello: dict[str, Any], send: Sender) -> Channel:
        channel = Channel(
            id=new_id(),
            cwd=str(hello.get("cwd") or ""),
            pid=int(hello.get("pid") or 0),
            name=str(hello.get("name") or "sidekick"),
            version=str(hello.get("version") or ""),
            send=send,
        )
        self.channels[channel.id] = channel
        log.info("channel %s connected from %s (pid %s)", channel.id, channel.cwd or "?", channel.pid)
        self._bus.publish("channel_connected", channel.to_dict())
        self._refresh()
        return channel

    async def disconnect(self, channel_id: str) -> None:
        channel = self.channels.pop(channel_id, None)
        if channel is None:
            return
        for relay in [r for r in self.relays.values() if r.channel_id == channel_id]:
            del self.relays[relay.request_id]
            self._bus.publish("permission_resolved", {"id": relay.request_id, "decision": "dropped"})
        log.info("channel %s disconnected", channel_id)
        self._bus.publish("channel_disconnected", channel.to_dict())
        self._refresh()

    async def handle(self, channel_id: str, msg: dict[str, Any]) -> None:
        kind = msg.get("type")
        if kind == "pong":
            return
        if kind == "hello":
            channel = self.channels.get(channel_id)
            if channel is not None:
                channel.cwd = str(msg.get("cwd") or channel.cwd)
                channel.pid = int(msg.get("pid") or channel.pid)
                self._bus.publish("channel_connected", channel.to_dict())
            return
        if kind == "permission_request":
            self._on_permission_request(channel_id, msg)
            return
        if kind == "reply":
            text = str(msg.get("text") or "").strip()
            if text:
                self._bus.publish("channel_reply", {"channel_id": channel_id, "text": text})
                self._speaker.speak(text, kind="channel")
            return
        log.debug("channel %s sent unknown message %r", channel_id, kind)

    # --- permission relay --------------------------------------------------
    def _on_permission_request(self, channel_id: str, msg: dict[str, Any]) -> None:
        request_id = str(msg.get("request_id") or "").strip()
        if not request_id or channel_id not in self.channels:
            return
        relay = RelayRequest(
            request_id=request_id,
            channel_id=channel_id,
            tool_name=str(msg.get("tool_name") or "Tool"),
            description=str(msg.get("description") or ""),
            input_preview=str(msg.get("input_preview") or ""),
        )
        relay.spoken = self._summarizer.format_relay(relay.tool_name, relay.description, relay.input_preview)
        self.relays[request_id] = relay
        self._bus.publish("permission_request", relay.to_dict())
        self._refresh()
        self._sounds.play("needs_input")
        self._speaker.speak(relay.spoken, kind="needs_input")

    async def verdict(self, request_id: str, behavior: str) -> bool:
        if behavior not in ("allow", "deny"):
            raise ValueError("behavior must be allow or deny")
        relay = self.relays.pop(request_id, None)
        if relay is None:
            return False
        channel = self.channels.get(relay.channel_id)
        if channel is not None:
            try:
                await channel.send({"type": "permission", "request_id": request_id, "behavior": behavior})
            except Exception as exc:  # noqa: BLE001
                log.warning("sending verdict to channel %s failed: %s", relay.channel_id, exc)
        self._bus.publish("permission_resolved", {"id": request_id, "decision": behavior})
        self._refresh()
        return True

    def defer(self, request_id: str, minutes: int) -> float | None:
        relay = self.relays.get(request_id)
        if relay is None:
            return None
        relay.snoozed_until = time.time() + 60 * max(1, minutes)
        self._bus.publish(
            "permission_deferred",
            {"id": request_id, "session_id": f"channel:{relay.channel_id}", "until": relay.snoozed_until},
        )
        self._refresh()
        return relay.snoozed_until

    def wake(self, request_id: str, announce: bool = False) -> bool:
        relay = self.relays.get(request_id)
        if relay is None or relay.snoozed_until is None:
            return False
        relay.snoozed_until = None
        self._bus.publish("permission_woken", {"id": request_id, "session_id": f"channel:{relay.channel_id}"})
        self._refresh()
        if announce and relay.spoken:
            self._sounds.play("needs_input")
            self._speaker.speak(relay.spoken, kind="needs_input")
        return True

    def tick_snoozes(self, now: float | None = None) -> list[str]:
        now = time.time() if now is None else now
        # A relay the terminal already answered never gets a verdict from us; drop it after a while.
        stale = [r.request_id for r in self.relays.values() if now - r.ts > RELAY_TTL_S]
        for request_id in stale:
            del self.relays[request_id]
            self._bus.publish("permission_resolved", {"id": request_id, "decision": "dropped"})
        if stale:
            self._refresh()
        due = [
            r.request_id
            for r in self.relays.values()
            if r.snoozed_until is not None and r.snoozed_until <= now
        ]
        for request_id in due:
            self.wake(request_id, announce=True)
        return due

    def wake_all_snoozed(self) -> list[str]:
        return self.tick_snoozes(now=float("inf"))

    # --- pushing text into the session -------------------------------------
    async def push(self, channel_id: str, content: str, meta: dict[str, str] | None = None) -> bool:
        channel = self.channels.get(channel_id)
        if channel is None:
            return False
        await channel.send({"type": "push", "content": content, "meta": dict(meta or {})})
        self._bus.publish("channel_push", {"channel_id": channel_id, "content": content, "meta": meta or {}})
        return True

    # --- helpers -----------------------------------------------------------
    def _refresh(self) -> None:
        if self._attention_refresh is not None:
            self._attention_refresh()
        else:
            self._state.update(attention="waiting_input" if self.any_active() else "none")
