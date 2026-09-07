"""Bluetooth adapter health and reset."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..bluetooth_doctor import reset_adapter
from ..services import Services
from .deps import get_services

router = APIRouter()


@router.get("/bluetooth/health")
async def bluetooth_health(services: Services = Depends(get_services)) -> dict[str, Any]:
    health = await services.bluetooth_doctor.check()
    return health.to_dict()


@router.post("/bluetooth/reset-adapter")
async def bluetooth_reset(services: Services = Depends(get_services)) -> dict[str, Any]:
    health = services.bluetooth_doctor.last or await services.bluetooth_doctor.check()
    if not health.instance_id:
        raise HTTPException(status_code=404, detail="Kein Bluetooth-Adapter gefunden")
    ok, message = await reset_adapter(health.instance_id)
    await services.bluetooth_doctor.check()
    return {"ok": ok, "message": message}
