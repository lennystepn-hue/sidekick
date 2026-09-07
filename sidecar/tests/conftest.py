from __future__ import annotations

from pathlib import Path

import pytest

from sidekick.db import Database
from sidekick.events import EventBus
from sidekick.secrets import FakeSecretStore
from sidekick.services import Services
from sidekick.state import AppState


@pytest.fixture
def core_services(tmp_path: Path) -> Services:
    from sidekick.config import Settings

    bus = EventBus()
    return Services(
        settings_path=tmp_path / "config.toml",
        settings=Settings(),
        bus=bus,
        state=AppState(bus),
        db=Database(tmp_path / "t.db"),
        secrets=FakeSecretStore(),
        fake=True,
    )
