"""API keys live in the Windows Credential Manager (via keyring), never in config.toml."""

from __future__ import annotations

import logging
from typing import Protocol

log = logging.getLogger(__name__)

SERVICE_NAME = "sidekick"
SECRET_NAMES: tuple[str, ...] = ("elevenlabs", "deepgram")


class SecretStore(Protocol):
    def get(self, name: str) -> str | None: ...
    def set(self, name: str, value: str) -> None: ...
    def delete(self, name: str) -> None: ...


class KeyringSecretStore:
    def __init__(self, service: str = SERVICE_NAME) -> None:
        self.service = service

    def get(self, name: str) -> str | None:
        import keyring

        try:
            return keyring.get_password(self.service, name)
        except Exception as exc:  # keyring backends throw all sorts of things
            log.warning("keyring get failed for %s: %s", name, exc)
            return None

    def set(self, name: str, value: str) -> None:
        import keyring

        keyring.set_password(self.service, name, value)

    def delete(self, name: str) -> None:
        import keyring
        from keyring.errors import PasswordDeleteError

        try:
            keyring.delete_password(self.service, name)
        except PasswordDeleteError:
            pass


class FakeSecretStore:
    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self.values: dict[str, str] = dict(initial or {})

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def set(self, name: str, value: str) -> None:
        self.values[name] = value

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


def secret_status(store: SecretStore) -> dict[str, bool]:
    return {name: bool(store.get(name)) for name in SECRET_NAMES}
