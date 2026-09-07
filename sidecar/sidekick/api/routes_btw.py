"""Side questions."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..services import Services
from .deps import get_services

router = APIRouter()


class AskBody(BaseModel):
    question: str
    speak: bool = True


@router.get("/btw")
async def list_btw(limit: int = 50, services: Services = Depends(get_services)) -> list[dict[str, Any]]:
    return services.db.list_btw(limit)


@router.post("/btw/ask")
async def ask_btw(body: AskBody, services: Services = Depends(get_services)) -> dict[str, Any]:
    if not body.question.strip():
        raise HTTPException(status_code=422, detail="question must not be empty")
    record = await services.btw.ask(body.question)
    if body.speak:
        services.speaker.speak(record["answer"], kind="btw")
    return record
