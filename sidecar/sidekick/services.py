"""Service container: everything the API routes and background tasks need.

`build_services()` wires real Windows backends (or fakes) together. The container grows
as modules are added; routes only ever touch attributes on this object.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Settings, load_settings
from .db import Database
from .events import EventBus
from .secrets import FakeSecretStore, KeyringSecretStore, SecretStore
from .state import AppState

log = logging.getLogger(__name__)


@dataclass
class Services:
    settings_path: Path
    settings: Settings
    bus: EventBus
    state: AppState
    db: Database
    secrets: SecretStore
    fake: bool = False
    components: list[Any] = field(default_factory=list)
    _started: bool = False

    # --- lifecycle -----------------------------------------------------
    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        self.bus.bind(asyncio.get_running_loop())
        for component in self.components:
            starter = getattr(component, "start", None)
            if starter is None:
                continue
            try:
                result = starter()
                if asyncio.iscoroutine(result):
                    await result
            except Exception:  # noqa: BLE001
                log.exception("failed to start %s", type(component).__name__)
                self.bus.publish("error", {"module": type(component).__name__, "message": "start failed"})

    async def stop(self) -> None:
        if not self._started:
            return
        self._started = False
        for component in reversed(self.components):
            stopper = getattr(component, "stop", None)
            if stopper is None:
                continue
            try:
                result = stopper()
                if asyncio.iscoroutine(result):
                    await asyncio.wait_for(result, timeout=5)
            except Exception:  # noqa: BLE001
                log.exception("failed to stop %s", type(component).__name__)
        self.db.close()

    # --- settings ------------------------------------------------------
    def apply_settings(self, new: Settings) -> None:
        old = self.settings
        self.settings = new
        for component in self.components:
            hook = getattr(component, "on_settings_changed", None)
            if hook is not None:
                try:
                    hook(old, new)
                except Exception:  # noqa: BLE001
                    log.exception("settings hook failed in %s", type(component).__name__)

    def on_secret_changed(self, name: str) -> None:
        for component in self.components:
            hook = getattr(component, "on_secret_changed", None)
            if hook is not None:
                try:
                    hook(name)
                except Exception:  # noqa: BLE001
                    log.exception("secret hook failed in %s", type(component).__name__)


def build_core(settings_path: Path, db_path: Path | str, fake: bool) -> Services:
    settings = load_settings(settings_path)
    bus = EventBus()
    state = AppState(bus)
    db = Database(db_path)
    secrets: SecretStore = FakeSecretStore() if fake else KeyringSecretStore()
    return Services(
        settings_path=settings_path,
        settings=settings,
        bus=bus,
        state=state,
        db=db,
        secrets=secrets,
        fake=fake,
    )


def build_services(settings_path: Path, db_path: Path | str, fake: bool = False) -> Services:
    """Build the full container. Later modules register their components here."""
    services = build_core(settings_path, db_path, fake)
    return services
