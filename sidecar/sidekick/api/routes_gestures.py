"""Gesture / media key log for the gesture test view."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ..services import Services
from .deps import get_services

router = APIRouter()


@router.get("/gestures/log")
async def gesture_log(limit: int = 50, services: Services = Depends(get_services)) -> list[dict[str, Any]]:
    return services.gestures.entries(limit)
