"""Multiple embedded sessions: list, create, activate, resume, stop, delete, rename."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..config import save_settings
from ..services import Services
from .deps import get_services

router = APIRouter()


class CreateBody(BaseModel):
    cwd: str
    model: str | None = None
    title: str | None = None


class RenameBody(BaseModel):
    title: str


class SendBody(BaseModel):
    text: str


def _manager(services: Services):
    if services.sessions is None:
        raise HTTPException(status_code=503, detail="Session-Manager nicht verfügbar")
    return services.sessions


def _summary_or_404(services: Services, session_id: str) -> dict[str, Any]:
    summary = _manager(services).summary(session_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Unbekannte Session")
    return summary


@router.get("/sessions")
async def list_sessions(services: Services = Depends(get_services)) -> list[dict[str, Any]]:
    return _manager(services).summaries()


@router.post("/sessions")
async def create_session(body: CreateBody, services: Services = Depends(get_services)) -> dict[str, Any]:
    cwd = Path(body.cwd).expanduser()
    if not cwd.is_dir():
        raise HTTPException(status_code=422, detail=f"Kein Verzeichnis: {cwd}")
    try:
        session = await _manager(services).create(str(cwd), body.model or None, body.title or None)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Session konnte nicht gestartet werden: {exc}") from exc
    services.settings.claude.last_cwd = str(cwd)
    try:
        save_settings(services.settings_path, services.settings)
    except OSError:
        pass
    return session.summary()


@router.post("/sessions/{session_id}/activate")
async def activate_session(session_id: str, services: Services = Depends(get_services)) -> dict[str, Any]:
    try:
        return await _manager(services).activate(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unbekannte Session") from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Session konnte nicht aktiviert werden: {exc}") from exc


@router.post("/sessions/{session_id}/resume")
async def resume_session(session_id: str, services: Services = Depends(get_services)) -> dict[str, Any]:
    try:
        session = await _manager(services).resume(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unbekannte Session") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail=f"Session konnte nicht fortgesetzt werden: {exc}"
        ) from exc
    return session.summary()


@router.post("/sessions/{session_id}/stop")
async def stop_session(session_id: str, services: Services = Depends(get_services)) -> dict[str, Any]:
    _summary_or_404(services, session_id)
    await _manager(services).stop(session_id)
    return {"ok": True}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, services: Services = Depends(get_services)) -> dict[str, Any]:
    _summary_or_404(services, session_id)
    await _manager(services).delete(session_id)
    return {"ok": True}


@router.patch("/sessions/{session_id}")
async def rename_session(
    session_id: str, body: RenameBody, services: Services = Depends(get_services)
) -> dict[str, Any]:
    if not body.title.strip():
        raise HTTPException(status_code=422, detail="title must not be empty")
    summary = _manager(services).rename(session_id, body.title)
    if summary is None:
        raise HTTPException(status_code=404, detail="Unbekannte Session")
    return summary


@router.get("/sessions/{session_id}/messages")
async def session_messages(
    session_id: str, limit: int = 200, services: Services = Depends(get_services)
) -> list[dict[str, Any]]:
    _summary_or_404(services, session_id)
    return _manager(services).messages(session_id, limit)


@router.post("/sessions/{session_id}/send")
async def send_to_session(
    session_id: str, body: SendBody, services: Services = Depends(get_services)
) -> dict[str, Any]:
    session = _manager(services).get(session_id)
    if session is None or not session.running:
        raise HTTPException(status_code=409, detail="Session läuft nicht")
    await session.send(body.text)
    return {"ok": True}


@router.post("/sessions/{session_id}/interrupt")
async def interrupt_session(session_id: str, services: Services = Depends(get_services)) -> dict[str, Any]:
    session = _manager(services).get(session_id)
    if session is not None:
        await session.interrupt()
    return {"ok": True}
