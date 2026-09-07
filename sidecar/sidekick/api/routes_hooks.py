"""Hook endpoint for external Claude Code sessions, plus the hook installer."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..claude import installer
from ..services import Services
from .deps import get_services

log = logging.getLogger(__name__)
router = APIRouter()


async def _payload(request: Request) -> dict[str, Any]:
    body = await request.body()
    if not body:
        return {}
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return {"raw": body.decode("utf-8", errors="replace")[:2000]}
    return data if isinstance(data, dict) else {"raw": data}


@router.post("/hook")
async def hook_root(request: Request, services: Services = Depends(get_services)) -> dict[str, Any]:
    payload = await _payload(request)
    asyncio.create_task(services.hooks.handle(None, payload))
    return {}


@router.post("/hook/{event}")
async def hook_event(event: str, request: Request, services: Services = Depends(get_services)) -> dict[str, Any]:
    payload = await _payload(request)
    asyncio.create_task(services.hooks.handle(event, payload))
    return {}


@router.get("/sessions/external")
async def external_sessions(services: Services = Depends(get_services)) -> list[dict[str, Any]]:
    return services.hooks.list_sessions()


@router.get("/hooks/events")
async def hook_events(limit: int = 50, services: Services = Depends(get_services)) -> list[dict[str, Any]]:
    return services.db.list_hook_events(limit)


class InstallBody(BaseModel):
    path: str | None = None
    scope: str = "project"


def _validate(body: InstallBody) -> tuple[str | None, str]:
    if body.scope not in ("project", "local", "user"):
        raise HTTPException(status_code=422, detail="scope must be project, local or user")
    if body.scope != "user":
        if not body.path:
            raise HTTPException(status_code=422, detail="path required")
        if not Path(body.path).expanduser().is_dir():
            raise HTTPException(status_code=422, detail=f"Kein Verzeichnis: {body.path}")
    return body.path, body.scope


@router.get("/hooks/status")
async def hooks_status(path: str | None = None, scope: str = "project", services: Services = Depends(get_services)) -> dict[str, Any]:
    project, scope = _validate(InstallBody(path=path, scope=scope))
    return installer.status(project, scope)


@router.get("/hooks/snippet")
async def hooks_snippet(services: Services = Depends(get_services)) -> dict[str, Any]:
    return installer.hook_config_snippet(services.settings.server.port)


@router.post("/hooks/install")
async def hooks_install(body: InstallBody, services: Services = Depends(get_services)) -> dict[str, Any]:
    project, scope = _validate(body)
    try:
        path = installer.install(project, scope, services.settings.server.port)
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=f"Settings-Datei nicht lesbar: {exc}") from exc
    return {"ok": True, "file": str(path), **installer.status(project, scope)}


@router.post("/hooks/uninstall")
async def hooks_uninstall(body: InstallBody, services: Services = Depends(get_services)) -> dict[str, Any]:
    project, scope = _validate(body)
    try:
        path = installer.uninstall(project, scope)
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=f"Settings-Datei nicht lesbar: {exc}") from exc
    return {"ok": True, "file": str(path), **installer.status(project, scope)}
