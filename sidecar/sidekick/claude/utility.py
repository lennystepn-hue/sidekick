"""Cheap single-turn Claude calls (cleanup, summaries, btw) through the Claude Agent SDK.

The SDK bundles the Claude Code binary and reuses the user's Claude Code login, so no API
key is needed. Thinking is disabled and no tools are exposed, which brings a Haiku call
to roughly one second of API time. A warm `ClaudeSDKClient` per (model, system prompt)
saves the ~2 s process start; it is recycled after `max_calls` calls or `idle_s` seconds
of inactivity so the conversation context never grows large.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..paths import prompts_dir

log = logging.getLogger(__name__)


class LLM(Protocol):
    async def complete(self, model: str, system: str, prompt: str) -> str: ...


def load_prompt(name: str, directory: Path | None = None) -> str:
    path = (directory or prompts_dir()) / f"{name}.md"
    return path.read_text(encoding="utf-8").strip()


def build_options(model: str, system: str, cli_path: str | None = None) -> Any:
    from claude_agent_sdk import ClaudeAgentOptions

    return ClaudeAgentOptions(
        model=model or None,
        system_prompt=system,
        tools=[],
        allowed_tools=[],
        setting_sources=[],
        strict_mcp_config=True,
        thinking={"type": "disabled"},
        permission_mode="dontAsk",
        max_turns=1,
        cli_path=cli_path or None,
        env={"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"},
    )


def collect_text(messages: Iterable[Any]) -> str:
    """Join the assistant text of a single-turn response; fall back to ResultMessage.result."""
    from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

    parts: list[str] = []
    result_text: str | None = None
    for m in messages:
        if isinstance(m, AssistantMessage):
            parts.extend(b.text for b in m.content if isinstance(b, TextBlock))
        elif isinstance(m, ResultMessage):
            if m.is_error:
                raise RuntimeError(f"claude call failed: {m.result or m.subtype}")
            result_text = m.result
    text = "\n".join(p for p in parts if p).strip()
    return text or (result_text or "").strip()


@dataclass
class _Warm:
    client: Any
    system: str
    calls: int = 0
    last_used: float = field(default_factory=time.time)


class UtilityLLM:
    def __init__(
        self,
        cli_path: str | None = None,
        warm: bool = True,
        max_calls: int = 20,
        idle_s: float = 900,
        timeout_s: float = 45,
    ) -> None:
        self._cli_path = cli_path or None
        self._warm_enabled = warm
        self._max_calls = max_calls
        self._idle_s = idle_s
        self._timeout_s = timeout_s
        self._clients: dict[str, _Warm] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self.calls_made = 0

    def set_cli_path(self, cli_path: str | None) -> None:
        self._cli_path = cli_path or None

    async def complete(self, model: str, system: str, prompt: str) -> str:
        lock = self._locks.setdefault(model, asyncio.Lock())
        async with lock:
            self.calls_made += 1
            if self._warm_enabled:
                try:
                    return await asyncio.wait_for(self._complete_warm(model, system, prompt), self._timeout_s)
                except Exception as exc:  # noqa: BLE001
                    log.warning("warm claude client for %s failed (%s); retrying one-shot", model, exc)
                    await self._drop(model)
            return await asyncio.wait_for(self._complete_oneshot(model, system, prompt), self._timeout_s)

    async def warm_up(self, targets: Iterable[tuple[str, str]]) -> None:
        for model, system in targets:
            lock = self._locks.setdefault(model, asyncio.Lock())
            async with lock:
                if model in self._clients:
                    continue
                try:
                    await self._connect(model, system)
                except Exception as exc:  # noqa: BLE001
                    log.warning("warm-up for %s failed: %s", model, exc)

    async def close(self) -> None:
        for model in list(self._clients):
            await self._drop(model)

    # --- internals -----------------------------------------------------
    async def _connect(self, model: str, system: str) -> _Warm:
        from claude_agent_sdk import ClaudeSDKClient

        client = ClaudeSDKClient(build_options(model, system, self._cli_path))
        await client.connect()
        warm = _Warm(client=client, system=system)
        self._clients[model] = warm
        log.info("warm claude client ready for %s", model)
        return warm

    async def _drop(self, model: str) -> None:
        warm = self._clients.pop(model, None)
        if warm is None:
            return
        try:
            await asyncio.wait_for(warm.client.disconnect(), 5)
        except Exception:  # noqa: BLE001
            pass

    async def _complete_warm(self, model: str, system: str, prompt: str) -> str:
        warm = self._clients.get(model)
        stale = warm is not None and (
            warm.system != system
            or warm.calls >= self._max_calls
            or time.time() - warm.last_used > self._idle_s
        )
        if warm is None or stale:
            await self._drop(model)
            warm = await self._connect(model, system)
        await warm.client.query(prompt)
        messages = [m async for m in warm.client.receive_response()]
        warm.calls += 1
        warm.last_used = time.time()
        return collect_text(messages)

    async def _complete_oneshot(self, model: str, system: str, prompt: str) -> str:
        from claude_agent_sdk import query

        messages = [
            m async for m in query(prompt=prompt, options=build_options(model, system, self._cli_path))
        ]
        return collect_text(messages)


class FakeLLM:
    """Scripted responses for tests; records every call."""

    def __init__(self, responses: list[str] | None = None, error: Exception | None = None) -> None:
        self.responses = list(responses or [])
        self.error = error
        self.calls: list[dict[str, str]] = []

    async def complete(self, model: str, system: str, prompt: str) -> str:
        self.calls.append({"model": model, "system": system, "prompt": prompt})
        if self.error:
            raise self.error
        if not self.responses:
            return ""
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
