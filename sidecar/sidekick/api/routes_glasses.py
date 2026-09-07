"""Glasses connection (manual override of presence)."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..services import Services
from .deps import get_services

router = APIRouter()


@router.get("/glasses")
async def glasses(services: Services = Depends(get_services)) -> dict[str, Any]:
    data = services.state.data
    return {
        "connected": data.glasses == "connected",
        "device_name": services.settings.audio.glasses_device_name,
        "battery": data.battery,
        "routed_to_glasses": data.audio.routed_to_glasses,
    }


@router.post("/glasses/connect")
async def glasses_connect(services: Services = Depends(get_services)) -> dict[str, Any]:
    name = services.settings.audio.glasses_device_name
    messages: list[str] = []
    services.state.update(presence_manual=True)
    bt = services.bluetooth
    if hasattr(bt, "connect"):
        try:
            messages.append(await asyncio.to_thread(bt.connect, name))
        except Exception as exc:  # noqa: BLE001
            messages.append(f"Bluetooth: {exc}")
    try:
        dev = await asyncio.to_thread(services.router.route_to_glasses)
        messages.append(f"Audio auf {dev.name}")
        services.sounds.play("connected")
        ok = True
    except Exception as exc:  # noqa: BLE001
        messages.append(str(exc))
        ok = False
    if services.presence is not None:
        await services.presence.tick()
    return {"ok": ok, "message": "; ".join(messages)}


@router.post("/glasses/disconnect")
async def glasses_disconnect(services: Services = Depends(get_services)) -> dict[str, Any]:
    name = services.settings.audio.glasses_device_name
    messages: list[str] = []
    services.state.update(presence_manual=True)
    try:
        prev = await asyncio.to_thread(services.router.restore)
        messages.append(f"Audio zurück auf {prev.name}" if prev else "Audio-Routing aufgehoben")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    bt = services.bluetooth
    if hasattr(bt, "disconnect"):
        try:
            messages.append(await asyncio.to_thread(bt.disconnect, name))
        except Exception as exc:  # noqa: BLE001
            messages.append(f"Bluetooth: {exc}")
    return {"ok": True, "message": "; ".join(messages)}
