"""Cheap single-turn Claude calls (cleanup, summaries, btw) through the Claude Agent SDK.

The SDK bundles the Claude Code binary and reuses the user's Claude Code login, so no API
key is needed. Thinking is disabled and no tools are exposed, which brings a Haiku call
to roughly one second of API time. A warm `ClaudeSDKClient` per (model, system prompt)
saves the ~2 s process start; it is recycled after `max_calls` calls or `idle_s` seconds
of inactivity so the conversation context never grows large.
"""

from __future__ import annotations

import asyncio
import hashlib
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


_cli_log = logging.getLogger("claude.cli")


def cli_stderr(line: str) -> None:
    """Receives claude.exe's stderr. Registering a callback also makes the SDK pipe stderr
    instead of inheriting ours; in the packaged sidecar (spawned by Tauri) inheriting the
    stderr handle fails with [WinError 50] and no claude.exe can start at all."""
    if line.strip():
        _cli_log.debug("%s", line.rstrip())


def build_options(model: str, system: str, cli_path: str | None = None, thinking: bool = False) -> Any:
    from claude_agent_sdk import ClaudeAgentOptions

    return ClaudeAgentOptions(
        model=model or None,
        system_prompt=system,
        tools=[],
        allowed_tools=[],
        setting_sources=[],
        strict_mcp_config=True,
        thinking={"type": "adaptive"} if thinking else {"type": "disabled"},
        permission_mode="dontAsk",
        max_turns=1,
        cli_path=cli_path or None,
        env={"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"},
        stderr=cli_stderr,
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


def client_key(model: str, system: str) -> str:
    """Warm clients are keyed by model and system prompt (cleanup and summary share Haiku)."""
    return f"{model}|{hashlib.sha1(system.encode('utf-8')).hexdigest()[:12]}"


@dataclass
class _Warm:
    client: Any
    model: str
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

    @property
    def warm_keys(self) -> list[str]:
        return list(self._clients)

    async def complete(self, model: str, system: str, prompt: str) -> str:
        key = client_key(model, system)
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            self.calls_made += 1
            if self._warm_enabled:
                try:
                    return await asyncio.wait_for(
                        self._complete_warm(key, model, system, prompt), self._timeout_s
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning("warm claude client for %s failed (%s); retrying one-shot", model, exc)
                    await self._drop(key)
            return await asyncio.wait_for(self._complete_oneshot(model, system, prompt), self._timeout_s)

    async def generate(
        self, model: str, system: str, prompt: str, timeout_s: float = 300, thinking: bool = True
    ) -> str:
        """A long one-shot call for document generation: no warm client, own timeout,
        thinking allowed. Transient process-start failures are retried."""
        from claude_agent_sdk import query

        self.calls_made += 1
        options = build_options(model, system, self._cli_path, thinking=thinking)
        last: Exception | None = None
        for attempt in range(3):
            try:
                messages = [m async for m in _timed(query(prompt=prompt, options=options), timeout_s)]
                return collect_text(messages)
            except TimeoutError:
                raise
            except Exception as exc:  # noqa: BLE001
                last = exc
                if attempt == 2 or "WinError" not in str(exc) and "start" not in str(exc).lower():
                    raise
                log.warning("generate start failed (attempt %d): %s; retrying", attempt + 1, exc)
                await asyncio.sleep(0.7 * (attempt + 1))
        raise RuntimeError(str(last))

    async def warm_up(self, targets: Iterable[tuple[str, str]]) -> None:
        for model, system in targets:
            key = client_key(model, system)
            lock = self._locks.setdefault(key, asyncio.Lock())
            async with lock:
                if key in self._clients:
                    continue
                try:
                    await self._connect(key, model, system)
                except Exception as exc:  # noqa: BLE001
                    log.warning("warm-up for %s failed: %s", model, exc)

    async def close(self) -> None:
        for key in list(self._clients):
            await self._drop(key)

    # --- internals -----------------------------------------------------
    async def _connect(self, key: str, model: str, system: str) -> _Warm:
        from claude_agent_sdk import ClaudeSDKClient

        client = ClaudeSDKClient(build_options(model, system, self._cli_path))
        # Spawning claude.exe occasionally fails transiently on Windows ([WinError 50]
        # when several children start within milliseconds); a short retry fixes it.
        for attempt in range(3):
            try:
                await client.connect()
                break
            except Exception as exc:  # noqa: BLE001
                if attempt == 2 or "WinError" not in str(exc) and "start" not in str(exc).lower():
                    raise
                log.warning("claude client start failed (attempt %d): %s; retrying", attempt + 1, exc)
                await asyncio.sleep(0.5 * (attempt + 1))
        warm = _Warm(client=client, model=model, system=system)
        self._clients[key] = warm
        log.info("warm claude client ready for %s (%s)", model, key)
        return warm

    async def _drop(self, key: str) -> None:
        warm = self._clients.pop(key, None)
        if warm is None:
            return
        try:
            await asyncio.wait_for(warm.client.disconnect(), 5)
        except Exception:  # noqa: BLE001
            pass

    async def _complete_warm(self, key: str, model: str, system: str, prompt: str) -> str:
        warm = self._clients.get(key)
        stale = warm is not None and (
            warm.calls >= self._max_calls or time.time() - warm.last_used > self._idle_s
        )
        if warm is None or stale:
            await self._drop(key)
            warm = await self._connect(key, model, system)
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


async def _timed(agen: Any, timeout_s: float) -> Any:
    """Iterate an async generator with an overall deadline."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    it = agen.__aiter__()
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise TimeoutError("claude call timed out")
        try:
            item = await asyncio.wait_for(it.__anext__(), remaining)
        except StopAsyncIteration:
            return
        yield item


class FakeLLM:
    """Scripted responses for tests; records every call."""

    def __init__(self, responses: list[str] | None = None, error: Exception | None = None) -> None:
        self.responses = list(responses or [])
        self.error = error
        self.calls: list[dict[str, str]] = []
        # generate(): answer per file marker found in the prompt, else the scripted responses
        self.documents: dict[str, str] = {}
        self.generate_errors: dict[str, Exception] = {}

    async def complete(self, model: str, system: str, prompt: str) -> str:
        self.calls.append({"model": model, "system": system, "prompt": prompt})
        if self.error:
            raise self.error
        if not self.responses:
            return ""
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]

    async def generate(
        self, model: str, system: str, prompt: str, timeout_s: float = 300, thinking: bool = True
    ) -> str:
        self.calls.append({"model": model, "system": system, "prompt": prompt, "generate": "1"})
        # keys match the "…: <file>\n" line of the prompt, not cross-references in the brief
        for name, exc in self.generate_errors.items():
            if f": {name}\n" in prompt:
                self.generate_errors.pop(name)  # fail once, then succeed on retry
                raise exc
        for name, text in self.documents.items():
            if f": {name}\n" in prompt:
                return text
        return await self.complete(model, system, prompt)
