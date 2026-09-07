"""Listen mode, transcripts, review decisions."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..services import Services
from .deps import get_services

router = APIRouter()


class ToggleBody(BaseModel):
    mode: str = "main"


class SendBody(BaseModel):
    text: str | None = None


@router.post("/listen/toggle")
async def listen_toggle(
    body: ToggleBody | None = None, services: Services = Depends(get_services)
) -> dict[str, Any]:
    mode = (body.mode if body else "main") or "main"
    if mode not in ("main", "btw"):
        raise HTTPException(status_code=422, detail="mode must be main or btw")
    listening = await services.listen.toggle(mode)
    return {"listening": listening}


@router.post("/listen/stop")
async def listen_stop(services: Services = Depends(get_services)) -> dict[str, Any]:
    await services.listen.stop()
    return {"ok": True}


@router.post("/listen/cancel")
async def listen_cancel(services: Services = Depends(get_services)) -> dict[str, Any]:
    await services.listen.cancel()
    return {"ok": True}


@router.get("/transcripts")
async def list_transcripts(
    limit: int = 50, services: Services = Depends(get_services)
) -> list[dict[str, Any]]:
    recent = {t["id"]: t for t in services.listen.recent}
    out: list[dict[str, Any]] = []
    for row in services.db.list_transcripts(limit):
        out.append(
            recent.get(row["id"], {**row, "review_deadline_ts": None, "mode": "main", "cleaned_ok": True})
        )
    return out


@router.post("/transcript/{transcript_id}/send")
async def transcript_send(
    transcript_id: str, body: SendBody | None = None, services: Services = Depends(get_services)
) -> dict[str, Any]:
    if not services.listen.send_now(transcript_id, body.text if body else None):
        raise HTTPException(status_code=404, detail="transcript not in review")
    return {"ok": True}


@router.post("/transcript/{transcript_id}/cancel")
async def transcript_cancel(transcript_id: str, services: Services = Depends(get_services)) -> dict[str, Any]:
    if not services.listen.cancel_review(transcript_id):
        raise HTTPException(status_code=404, detail="transcript not in review")
    return {"ok": True}
