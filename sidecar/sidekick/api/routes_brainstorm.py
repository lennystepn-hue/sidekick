"""Brainstorm sessions: idea state, materialization into a project, kickoff."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..claude.materialize import MaterializeOptions
from ..services import Services
from .deps import get_services

router = APIRouter()


class MaterializeBody(BaseModel):
    name: str | None = None
    base_dir: str | None = None
    git_init: bool | None = None
    start_session: bool | None = None


class OpenBody(BaseModel):
    path: str


def _materializer(services: Services):
    if services.materializer is None or services.sessions is None:
        raise HTTPException(status_code=503, detail="Brainstorm nicht verfügbar")
    return services.materializer


def _brainstorm_or_404(services: Services, session_id: str) -> dict[str, Any]:
    summary = services.sessions.summary(session_id) if services.sessions is not None else None
    if summary is None:
        raise HTTPException(status_code=404, detail="Unbekannte Session")
    if summary.get("kind") != "brainstorm":
        raise HTTPException(status_code=409, detail="Keine Brainstorm-Session")
    return summary


@router.get("/brainstorm/{session_id}")
async def brainstorm_state(session_id: str, services: Services = Depends(get_services)) -> dict[str, Any]:
    summary = _brainstorm_or_404(services, session_id)
    materializer = _materializer(services)
    path = summary.get("project_path")
    return {
        "state": summary.get("idea"),
        "project_path": path,
        "materialized": bool(path) and Path(path).is_dir(),
        "files": materializer.files(path),
        "job": materializer.job(session_id),
    }


@router.post("/brainstorm/{session_id}/materialize")
async def materialize(
    session_id: str, body: MaterializeBody, services: Services = Depends(get_services)
) -> dict[str, Any]:
    _brainstorm_or_404(services, session_id)
    materializer = _materializer(services)
    try:
        job = await materializer.start(
            session_id,
            MaterializeOptions(
                name=body.name or None,
                base_dir=body.base_dir or None,
                git_init=body.git_init,
                start_session=body.start_session,
            ),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, "job_id": job.job_id}


@router.post("/brainstorm/{session_id}/kickoff")
async def kickoff(session_id: str, services: Services = Depends(get_services)) -> dict[str, Any]:
    _brainstorm_or_404(services, session_id)
    materializer = _materializer(services)
    try:
        session = await materializer.kickoff(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unbekannte Session") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Session konnte nicht gestartet werden: {exc}") from exc
    return session.summary()


@router.get("/projects/suggest")
async def suggest_project(title: str = "", services: Services = Depends(get_services)) -> dict[str, Any]:
    return _materializer(services).suggest(title)


@router.post("/projects/open")
async def open_project(body: OpenBody, services: Services = Depends(get_services)) -> dict[str, Any]:
    path = Path(body.path).expanduser()
    if not path.is_dir():
        raise HTTPException(status_code=404, detail="Ordner nicht gefunden")
    if services.hardware and sys.platform == "win32":
        os.startfile(str(path))  # noqa: S606 - opens Explorer on a folder the user picked
    return {"ok": True, "path": str(path)}
