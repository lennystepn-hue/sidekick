"""Active-session routes (kept for the original contract; they act on the active session)."""

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
    manager = services.sessions
    active = manager.active if manager else None
    pending = []
    if manager is not None:
        for s in manager.live.values():
            pending.extend(p.to_dict() for p in s.pending.values())
    return {
        "session": services.state.to_dict()["session"],
        "pending": pending,
        "sdk_session_id": active.sdk_session_id if active else None,
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
        await services.sessions.create(str(cwd), body.model or None)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Session konnte nicht gestartet werden: {exc}") from exc
    services.settings.claude.last_cwd = str(cwd)
    try:
        save_settings(services.settings_path, services.settings)
    except OSError:
        pass
    payload = _session_payload(services)
    # Contract: returns the Session; the wrapper fields are added for convenience.
    return {**(payload["session"] or {}), **payload}


@router.post("/session/stop")
async def stop_session(services: Services = Depends(get_services)) -> dict[str, Any]:
    active = services.session
    if active is not None:
        await services.sessions.stop(active.session_id)
    return {"ok": True}


@router.post("/session/interrupt")
async def interrupt_session(services: Services = Depends(get_services)) -> dict[str, Any]:
    active = services.session
    if active is not None:
        await active.interrupt()
    return {"ok": True}


@router.post("/session/send")
async def send_to_session(body: SendBody, services: Services = Depends(get_services)) -> dict[str, Any]:
    active = services.session
    if active is None or not active.running:
        raise HTTPException(status_code=409, detail="Keine laufende Session")
    await active.send(body.text)
    return {"ok": True}


@router.post("/session/permission/{pending_id}")
async def resolve_permission(
    pending_id: str, body: PermissionBody, services: Services = Depends(get_services)
) -> dict[str, Any]:
    found = services.sessions.find_pending(pending_id) if services.sessions else None
    if found is None:
        raise HTTPException(status_code=404, detail="Keine offene Anfrage mit dieser ID")
    session, _pending = found
    try:
        ok = session.resolve_permission(pending_id, body.decision, body.answers, body.message)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=404, detail="Keine offene Anfrage mit dieser ID")
    return {"ok": True}


@router.get("/session/messages")
async def session_messages(
    limit: int = 200, services: Services = Depends(get_services)
) -> list[dict[str, Any]]:
    manager = services.sessions
    sid = manager.active_id if manager else None
    if sid is None:
        return []
    return services.db.list_messages(sid, limit)
