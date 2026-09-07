"""Audio devices, routing, sounds."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..audio.sounds import SOUND_NAMES
from ..services import Services
from .deps import get_services

router = APIRouter()


class RouteBody(BaseModel):
    target: str = "glasses"


class PlayBody(BaseModel):
    sound: str


@router.get("/audio/devices")
async def audio_devices(services: Services = Depends(get_services)) -> list[dict[str, Any]]:
    devices = await asyncio.to_thread(services.router.devices)
    return [d.to_dict() for d in devices]


@router.post("/audio/route")
async def audio_route(body: RouteBody, services: Services = Depends(get_services)) -> dict[str, Any]:
    try:
        if body.target == "glasses":
            dev = await asyncio.to_thread(services.router.route_to_glasses)
            return {"ok": True, "output_device": dev.name}
        if body.target == "restore":
            dev = await asyncio.to_thread(services.router.restore)
            return {"ok": True, "output_device": dev.name if dev else services.state.data.audio.output_device}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    raise HTTPException(status_code=422, detail="target must be glasses or restore")


@router.post("/audio/play")
async def audio_play(body: PlayBody, services: Services = Depends(get_services)) -> dict[str, Any]:
    if body.sound not in SOUND_NAMES:
        raise HTTPException(status_code=404, detail=f"unknown sound {body.sound}")
    services.sounds.play(body.sound)
    return {"ok": True}
