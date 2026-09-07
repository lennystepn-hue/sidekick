from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request, WebSocket

if TYPE_CHECKING:
    from ..services import Services


def get_services(request: Request) -> Services:
    return request.app.state.services


def get_services_ws(websocket: WebSocket) -> Services:
    return websocket.app.state.services
