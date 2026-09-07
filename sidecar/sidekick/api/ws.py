"""WebSocket event stream: sends the full state first, then every bus event."""

from __future__ import annotations

import asyncio
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .deps import get_services_ws

log = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    services = get_services_ws(websocket)
    await websocket.accept()
    queue = services.bus.subscribe()
    try:
        await websocket.send_json({"type": "state", "ts": time.time(), "data": services.state.to_dict()})

        async def reader() -> None:
            while True:
                msg = await websocket.receive_json()
                if isinstance(msg, dict) and msg.get("type") == "ping":
                    await websocket.send_json({"type": "pong", "ts": time.time(), "data": {}})

        async def writer() -> None:
            while True:
                ev = await queue.get()
                await websocket.send_json(ev.to_dict())

        reader_task = asyncio.create_task(reader())
        writer_task = asyncio.create_task(writer())
        done, pending = await asyncio.wait({reader_task, writer_task}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc and not isinstance(exc, WebSocketDisconnect | RuntimeError):
                log.debug("ws task ended: %r", exc)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        log.debug("websocket closed: %r", exc)
    finally:
        services.bus.unsubscribe(queue)
