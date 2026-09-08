"""Sidekick channel (Claude Code channels preview) and the terminal launcher."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from .. import terminal
from ..services import Services
from .deps import get_services, get_services_ws

log = logging.getLogger(__name__)
router = APIRouter()

PING_S = 20.0
HELLO_TIMEOUT_S = 10.0


class VerdictBody(BaseModel):
    behavior: str  # allow | deny | defer | wake


class PushBody(BaseModel):
    text: str
    channel_id: str | None = None
    meta: dict[str, str] | None = None


class LaunchBody(BaseModel):
    cwd: str
    remote_control: bool = True
    channel: bool = True
    name: str | None = None


def _hub(services: Services):
    if services.channels is None:
        raise HTTPException(status_code=503, detail="Kanal nicht verfügbar")
    return services.channels


@router.websocket("/channel")
async def channel_socket(websocket: WebSocket) -> None:
    services = get_services_ws(websocket)
    hub = services.channels
    await websocket.accept()
    if hub is None:
        await websocket.close(code=1011)
        return
    channel = None
    try:
        hello = await asyncio.wait_for(websocket.receive_json(), HELLO_TIMEOUT_S)
        if not isinstance(hello, dict) or hello.get("type") != "hello":
            await websocket.close(code=1002)
            return

        async def send(msg: dict[str, Any]) -> None:
            await websocket.send_json(msg)

        channel = await hub.connect(hello, send)

        async def pinger() -> None:
            while True:
                await asyncio.sleep(PING_S)
                await send({"type": "ping"})

        ping_task = asyncio.create_task(pinger(), name=f"channel-ping-{channel.id}")
        try:
            while True:
                msg = await websocket.receive_json()
                if isinstance(msg, dict):
                    await hub.handle(channel.id, msg)
        finally:
            ping_task.cancel()
    except (WebSocketDisconnect, TimeoutError):
        pass
    except Exception as exc:  # noqa: BLE001
        log.debug("channel socket closed: %r", exc)
    finally:
        if channel is not None:
            await hub.disconnect(channel.id)


@router.get("/channel/status")
async def channel_status(services: Services = Depends(get_services)) -> dict[str, Any]:
    hub = _hub(services)
    setup = services.channel_setup
    info = await asyncio.to_thread(setup.status) if setup is not None else {}
    return {**info, **hub.status()}


@router.post("/channel/install")
async def channel_install(services: Services = Depends(get_services)) -> dict[str, Any]:
    setup = services.channel_setup
    if setup is None:
        raise HTTPException(status_code=503, detail="Kanal nicht verfügbar")
    try:
        return await asyncio.to_thread(setup.install)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/channel/uninstall")
async def channel_uninstall(services: Services = Depends(get_services)) -> dict[str, Any]:
    setup = services.channel_setup
    if setup is None:
        raise HTTPException(status_code=503, detail="Kanal nicht verfügbar")
    return await asyncio.to_thread(setup.uninstall)


@router.post("/channel/permission/{request_id}")
async def channel_permission(
    request_id: str, body: VerdictBody, services: Services = Depends(get_services)
) -> dict[str, Any]:
    hub = _hub(services)
    if body.behavior == "defer":
        until = hub.defer(request_id, services.settings.claude.defer_minutes)
        if until is None:
            raise HTTPException(status_code=404, detail="Keine offene Anfrage mit dieser ID")
        return {"ok": True, "until": until}
    if body.behavior == "wake":
        if not hub.wake(request_id, announce=False):
            raise HTTPException(status_code=404, detail="Nichts zurückgestellt")
        return {"ok": True}
    try:
        ok = await hub.verdict(request_id, body.behavior)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=404, detail="Keine offene Anfrage mit dieser ID")
    return {"ok": True}


@router.post("/channel/push")
async def channel_push(body: PushBody, services: Services = Depends(get_services)) -> dict[str, Any]:
    hub = _hub(services)
    channel = hub.channels.get(body.channel_id) if body.channel_id else hub.latest()
    if channel is None:
        raise HTTPException(status_code=404, detail="Kein Kanal verbunden")
    if not body.text.strip():
        raise HTTPException(status_code=422, detail="text fehlt")
    await hub.push(channel.id, body.text.strip(), body.meta or {"kind": "text"})
    return {"ok": True, "channel_id": channel.id}


@router.post("/terminal/launch")
async def terminal_launch(body: LaunchBody, services: Services = Depends(get_services)) -> dict[str, Any]:
    if body.channel and services.channel_setup is not None:
        info = await asyncio.to_thread(services.channel_setup.status)
        if not info.get("installed"):
            raise HTTPException(
                status_code=409, detail="Sidekick-Kanal ist nicht eingerichtet (Einstellungen → Hooks)"
            )
    try:
        return await asyncio.to_thread(
            terminal.launch,
            body.cwd,
            services.settings.server.port,
            body.remote_control,
            body.channel,
            body.name,
            services.terminal_spawn,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
