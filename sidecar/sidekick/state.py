"""Application state: single source of truth, broadcast on every change."""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Literal

from .events import EventBus

Presence = Literal["unknown", "present", "absent"]
Glasses = Literal["unknown", "disconnected", "connected"]
Mode = Literal["idle", "listening", "transcribing", "reviewing", "speaking", "btw_listening"]
Attention = Literal["none", "waiting_input"]
SessionStatus = Literal["idle", "running", "waiting", "stopped"]
SessionKind = Literal["code", "brainstorm"]


@dataclass(slots=True)
class AudioState:
    output_device: str | None = None
    previous_output_device: str | None = None
    routed_to_glasses: bool = False


@dataclass(slots=True)
class SessionInfo:
    id: str
    cwd: str
    mode: Literal["embedded", "external"]
    status: SessionStatus = "idle"
    model: str = ""
    started_at: str = ""
    permission_mode: str = "auto"
    title: str = ""
    sdk_session_id: str | None = None
    last_active: str = ""
    kind: SessionKind = "code"
    project_path: str | None = None


@dataclass(slots=True)
class AdapterState:
    ok: bool = True
    problem_code: int | None = None
    name: str | None = None
    instance_id: str | None = None


@dataclass(slots=True)
class ModelsState:
    whisper_loaded: bool = False
    whisper_model: str = ""


@dataclass(slots=True)
class AppStateData:
    presence: Presence = "unknown"
    presence_manual: bool = False
    glasses: Glasses = "unknown"
    glasses_name: str = ""
    battery: int | None = None
    audio: AudioState = field(default_factory=AudioState)
    mode: Mode = "idle"
    attention: Attention = "none"
    session: SessionInfo | None = None
    bluetooth_adapter: AdapterState = field(default_factory=AdapterState)
    models: ModelsState = field(default_factory=ModelsState)
    external_sessions: int = 0
    sessions: list[dict[str, Any]] = field(default_factory=list)
    active_session_id: str | None = None


class AppState:
    """Mutable holder around `AppStateData` that publishes a `state` event on change."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._data = AppStateData()
        self._lock = threading.RLock()

    @property
    def data(self) -> AppStateData:
        return self._data

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return asdict(self._data)

    def update(self, **fields: Any) -> list[str]:
        """Update top-level fields. Returns the names that actually changed."""
        changed: list[str] = []
        with self._lock:
            for name, value in fields.items():
                if not hasattr(self._data, name):
                    raise AttributeError(f"unknown state field {name!r}")
                if getattr(self._data, name) != value:
                    setattr(self._data, name, value)
                    changed.append(name)
        if changed:
            self._bus.publish("state", self.to_dict())
        return changed

    def update_audio(self, **fields: Any) -> None:
        with self._lock:
            new = replace(self._data.audio, **fields)
            if new == self._data.audio:
                return
            self._data.audio = new
        self._bus.publish("state", self.to_dict())

    def update_session(self, **fields: Any) -> None:
        with self._lock:
            if self._data.session is None:
                return
            new = replace(self._data.session, **fields)
            if new == self._data.session:
                return
            self._data.session = new
        self._bus.publish("state", self.to_dict())

    def set_adapter(self, **fields: Any) -> None:
        with self._lock:
            new = replace(self._data.bluetooth_adapter, **fields)
            if new == self._data.bluetooth_adapter:
                return
            self._data.bluetooth_adapter = new
        self._bus.publish("state", self.to_dict())

    def set_models(self, **fields: Any) -> None:
        with self._lock:
            new = replace(self._data.models, **fields)
            if new == self._data.models:
                return
            self._data.models = new
        self._bus.publish("state", self.to_dict())

    # Convenience accessors used all over the place.
    @property
    def mode(self) -> Mode:
        return self._data.mode

    @property
    def glasses_connected(self) -> bool:
        return self._data.glasses == "connected"

    @property
    def session(self) -> SessionInfo | None:
        return self._data.session
