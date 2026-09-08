"""Route system audio to the glasses (A2DP) and back."""

from __future__ import annotations

import logging
from collections.abc import Callable

from ..config import Settings
from ..state import AppState
from .devices import (
    AudioDevice,
    AudioDeviceBackend,
    GlassesEndpoints,
    classify_endpoint,
    pick_glasses_endpoints,
)

log = logging.getLogger(__name__)


class AudioRouteError(RuntimeError):
    pass


class AudioRouter:
    def __init__(
        self, backend: AudioDeviceBackend, state: AppState, settings: Callable[[], Settings]
    ) -> None:
        self._backend = backend
        self._state = state
        self._settings = settings
        self._previous: AudioDevice | None = None

    @property
    def glasses_name(self) -> str:
        return self._settings().audio.glasses_device_name

    def devices(self) -> list[AudioDevice]:
        devs = self._backend.list_devices()
        for d in devs:
            d.role = classify_endpoint(d.name, self.glasses_name)
        return devs

    def endpoints(self) -> GlassesEndpoints:
        return pick_glasses_endpoints(self._backend.list_devices(), self.glasses_name)

    def refresh(self) -> None:
        current = self._backend.get_default("render")
        self._state.update_audio(output_device=current.name if current else None)

    def current_default_name(self) -> str | None:
        """Name of Windows' current default render endpoint (thread-safe, COM per call)."""
        try:
            current = self._backend.get_default("render")
        except Exception:  # noqa: BLE001
            return None
        return current.name if current else None

    def route_to_glasses(self) -> AudioDevice:
        eps = self.endpoints()
        if eps.render_a2dp is None:
            raise AudioRouteError(f"Kein A2DP-Ausgabegerät mit Namen '{self.glasses_name}' gefunden")
        current = self._backend.get_default("render")
        if current is not None and current.id == eps.render_a2dp.id:
            self._state.update_audio(output_device=current.name, routed_to_glasses=True)
            return eps.render_a2dp
        # Remember only a "real" previous device: when a headset connects Windows often makes
        # its Hands-Free endpoint the default, and restoring to that later would fail.
        if (
            current is not None
            and not self._state.data.audio.routed_to_glasses
            and classify_endpoint(current.name, self.glasses_name) == "other"
        ):
            self._previous = current
        self._backend.set_default(eps.render_a2dp.id)
        self._state.update_audio(
            output_device=eps.render_a2dp.name,
            previous_output_device=self._previous.name if self._previous else None,
            routed_to_glasses=True,
        )
        return eps.render_a2dp

    def restore(self) -> AudioDevice | None:
        if not self._settings().audio.restore_previous_device:
            self._state.update_audio(routed_to_glasses=False)
            return None
        prev = self._previous
        if prev is None:
            self._state.update_audio(routed_to_glasses=False)
            return None
        try:
            self._backend.set_default(prev.id)
        except Exception as exc:
            log.warning("could not restore previous output %s: %s", prev.name, exc)
            self._previous = None
            self._state.update_audio(previous_output_device=None, routed_to_glasses=False)
            raise
        self._previous = None
        self._state.update_audio(
            output_device=prev.name, previous_output_device=None, routed_to_glasses=False
        )
        return prev

    def ensure_a2dp(self) -> None:
        """After the HFP microphone was open, make sure output is back on the A2DP endpoint."""
        if not self._state.data.audio.routed_to_glasses:
            return
        eps = self.endpoints()
        current = self._backend.get_default("render")
        if eps.render_a2dp and (current is None or current.id != eps.render_a2dp.id):
            self._backend.set_default(eps.render_a2dp.id)

    def output_device_name(self) -> str | None:
        """Name to hand to the player: the A2DP endpoint while routed, else system default."""
        if not self._state.data.audio.routed_to_glasses:
            return None
        eps = self.endpoints()
        return eps.render_a2dp.name if eps.render_a2dp else None
