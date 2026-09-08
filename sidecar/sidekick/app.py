"""FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .api import routes_core, ws
from .services import Services

log = logging.getLogger(__name__)

ALLOWED_ORIGINS = [
    "http://localhost:1420",
    "http://127.0.0.1:1420",
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
]


def create_app(services: Services) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await services.start()
        try:
            yield
        finally:
            await services.stop()

    app = FastAPI(title="Sidekick sidecar", version=__version__, lifespan=lifespan)
    app.state.services = services
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(routes_core.router)
    app.include_router(ws.router)
    _include_optional_routers(app)
    return app


def _include_optional_routers(app: FastAPI) -> None:
    """Routers added by later modules; imported lazily so partial builds still boot."""
    import importlib

    for name in (
        "routes_audio",
        "routes_glasses",
        "routes_bluetooth",
        "routes_listen",
        "routes_tts",
        "routes_session",
        "routes_sessions",
        "routes_hooks",
        "routes_btw",
        "routes_gestures",
    ):
        try:
            module = importlib.import_module(f".api.{name}", package=__package__)
        except ModuleNotFoundError as exc:
            if exc.name and exc.name.endswith(name):
                continue
            raise
        app.include_router(module.router)
