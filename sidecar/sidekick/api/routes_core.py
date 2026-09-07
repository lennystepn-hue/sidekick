"""Health, state, settings, secrets, shutdown."""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import __version__
from ..config import merge_settings, save_settings
from ..secrets import SECRET_NAMES, secret_status
from ..services import Services
from .deps import get_services

router = APIRouter()
_started = time.time()


@router.get("/health")
async def health(services: Services = Depends(get_services)) -> dict[str, Any]:
    return {
        "ok": True,
        "version": __version__,
        "port": services.settings.server.port,
        "uptime_s": round(time.time() - _started, 1),
        "fake": services.fake,
    }


@router.get("/state")
async def get_state(services: Services = Depends(get_services)) -> dict[str, Any]:
    return services.state.to_dict()


@router.get("/settings")
async def get_settings(services: Services = Depends(get_services)) -> dict[str, Any]:
    return services.settings.model_dump(mode="json")


@router.put("/settings")
async def put_settings(patch: dict[str, Any], services: Services = Depends(get_services)) -> dict[str, Any]:
    try:
        new = merge_settings(services.settings, patch)
    except Exception as exc:  # pydantic ValidationError
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    services.apply_settings(new)
    save_settings(services.settings_path, new)
    services.bus.publish("settings", new.model_dump(mode="json"))
    return new.model_dump(mode="json")


class SecretBody(BaseModel):
    value: str


@router.get("/secrets")
async def get_secrets(services: Services = Depends(get_services)) -> dict[str, bool]:
    return secret_status(services.secrets)


@router.put("/secrets/{name}")
async def put_secret(name: str, body: SecretBody, services: Services = Depends(get_services)) -> dict[str, Any]:
    if name not in SECRET_NAMES:
        raise HTTPException(status_code=404, detail=f"unknown secret {name}")
    if not body.value.strip():
        raise HTTPException(status_code=422, detail="value must not be empty")
    services.secrets.set(name, body.value.strip())
    services.on_secret_changed(name)
    return {"ok": True}


@router.delete("/secrets/{name}")
async def delete_secret(name: str, services: Services = Depends(get_services)) -> dict[str, Any]:
    if name not in SECRET_NAMES:
        raise HTTPException(status_code=404, detail=f"unknown secret {name}")
    services.secrets.delete(name)
    services.on_secret_changed(name)
    return {"ok": True}


@router.post("/shutdown")
async def shutdown(services: Services = Depends(get_services)) -> dict[str, Any]:
    async def _exit() -> None:
        await asyncio.sleep(0.2)
        try:
            await services.stop()
        finally:
            os._exit(0)

    asyncio.create_task(_exit())
    return {"ok": True}
