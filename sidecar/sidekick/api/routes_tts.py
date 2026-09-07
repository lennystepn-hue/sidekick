"""Text to speech control."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..services import Services
from .deps import get_services

router = APIRouter()


class SpeakBody(BaseModel):
    text: str
    kind: str = "manual"


@router.post("/tts/speak")
async def tts_speak(body: SpeakBody, services: Services = Depends(get_services)) -> dict[str, Any]:
    if not body.text.strip():
        raise HTTPException(status_code=422, detail="text must not be empty")
    services.speaker.speak(body.text, kind=body.kind)
    return {"ok": True}


@router.post("/tts/stop")
async def tts_stop(services: Services = Depends(get_services)) -> dict[str, Any]:
    services.speaker.stop_speaking()
    return {"ok": True}


@router.post("/tts/repeat")
async def tts_repeat(services: Services = Depends(get_services)) -> dict[str, Any]:
    services.speaker.repeat_last()
    return {"ok": True, "text": services.speaker.last_text}
