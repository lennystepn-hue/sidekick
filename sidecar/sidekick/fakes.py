"""Fake hardware backends for tests and `--fake` runs on machines without the glasses."""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from .audio.devices import AudioDevice, Flow
from .audio.player import OutputSink


class FakeOutputSink:
    def __init__(self, backend: FakeOutput, samplerate: int, channels: int, device: int | None) -> None:
        self.backend = backend
        self.samplerate = samplerate
        self.channels = channels
        self.device = device
        self.samples: list[np.ndarray] = []

    def write(self, samples: np.ndarray) -> None:
        self.samples.append(np.asarray(samples))

    def close(self) -> None:
        self.backend.closed.append(self)


class FakeOutput:
    def __init__(self) -> None:
        self.opened: list[FakeOutputSink] = []
        self.closed: list[FakeOutputSink] = []

    def open(self, samplerate: int, channels: int, device: int | None) -> OutputSink:
        sink = FakeOutputSink(self, samplerate, channels, device)
        self.opened.append(sink)
        return sink


class FakeAudioBackend:
    def __init__(self, devices: list[AudioDevice] | None = None) -> None:
        self.devices = devices or [
            AudioDevice(
                id="spk", name="Lautsprecher (Realtek High Definition Audio)", flow="render", is_default=True
            ),
            AudioDevice(id="rb-a2dp", name="Kopfhörer (Ray-Ban Meta Stereo)", flow="render"),
            AudioDevice(id="rb-hfp", name="Headset (Ray-Ban Meta Hands-Free AG Audio)", flow="render"),
            AudioDevice(
                id="mic", name="Mikrofon (Realtek High Definition Audio)", flow="capture", is_default=True
            ),
            AudioDevice(id="rb-mic", name="Headset (Ray-Ban Meta Hands-Free AG Audio)", flow="capture"),
        ]
        self.set_calls: list[str] = []

    def list_devices(self) -> list[AudioDevice]:
        return [replace(d) for d in self.devices]

    def get_default(self, flow: Flow) -> AudioDevice | None:
        for d in self.devices:
            if d.flow == flow and d.is_default:
                return replace(d)
        return None

    def set_default(self, device_id: str) -> None:
        target = next((d for d in self.devices if d.id == device_id), None)
        if target is None:
            raise KeyError(device_id)
        for d in self.devices:
            if d.flow == target.flow:
                d.is_default = d.id == device_id
        self.set_calls.append(device_id)
