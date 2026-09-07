"""Embedded session control."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..config import save_settings
from ..services import Services
from .deps import get_services

router = APIRouter()


class StartBody(BaseModel):
    cwd: str
    model: str | None = None


class SendBody(BaseModel):
    text: str


class PermissionBody(BaseModel):
    decision: str
    answers: dict[str, Any] | None = None
    message: str | None = None


def _session_payload(services: Services) -> dict[str, Any]:
    info = services.state.session
    return {
        "session": None if info is None else services.state.to_dict()["session"],
        "pending": [p.to_dict() for p in services.session.pending.values()],
        "sdk_session_id": services.session.sdk_session_id,
    }


@router.get("/session")
async def get_session(services: Services = Depends(get_services)) -> dict[str, Any]:
    return _session_payload(services)


@router.post("/session/start")
async def start_session(body: StartBody, services: Services = Depends(get_services)) -> dict[str, Any]:
    cwd = Path(body.cwd).expanduser()
    if not cwd.is_dir():
        raise HTTPException(status_code=422, detail=f"Kein Verzeichnis: {cwd}")
    try:
        await services.session.start(str(cwd), body.model or None)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Session konnte nicht gestartet werden: {exc}") from exc
    services.settings.claude.last_cwd = str(cwd)
    try:
        save_settings(services.settings_path, services.settings)
    except OSError:
        pass
    return _session_payload(services)


@router.post("/session/stop")
async def stop_session(services: Services = Depends(get_services)) -> dict[str, Any]:
    await services.session.stop()
    return {"ok": True}


@router.post("/session/interrupt")
async def interrupt_session(services: Services = Depends(get_services)) -> dict[str, Any]:
    await services.session.interrupt()
    return {"ok": True}


@router.post("/session/send")
async def send_to_session(body: SendBody, services: Services = Depends(get_services)) -> dict[str, Any]:
    try:
        await services.session.send(body.text)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/session/permission/{pending_id}")
async def resolve_permission(
    pending_id: str, body: PermissionBody, services: Services = Depends(get_services)
) -> dict[str, Any]:
    try:
        ok = services.session.resolve_permission(pending_id, body.decision, body.answers, body.message)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=404, detail="Keine offene Anfrage mit dieser ID")
    return {"ok": True}


@router.get("/session/messages")
async def session_messages(
    limit: int = 200, services: Services = Depends(get_services)
) -> list[dict[str, Any]]:
    sid = services.session.session_id
    if sid is None:
        info = services.state.session
        sid = info.id if info else None
    if sid is None:
        return []
    return services.db.list_messages(sid, limit)
