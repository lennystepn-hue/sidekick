"""PortAudio device-list refresh and host-API helpers.

PortAudio enumerates devices once at initialisation. The sidecar autostarts at login and
the glasses connect later, so their endpoints would stay invisible. `refresh_devices()`
re-initialises PortAudio, which is only safe while no stream is open; streams register
themselves with `stream_opened()` / `stream_closed()`.

Playback and capture always prefer WASAPI: with `auto_convert` Windows resamples in the
mixer, so a 44.1 kHz tone or a 24 kHz TTS stream plays cleanly on a 48 kHz endpoint.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

log = logging.getLogger(__name__)

_lock = threading.RLock()
_open_streams = 0
_last_refresh = 0.0


def stream_opened() -> None:
    global _open_streams
    with _lock:
        _open_streams += 1


def stream_closed() -> None:
    global _open_streams
    with _lock:
        _open_streams = max(0, _open_streams - 1)


def open_stream_count() -> int:
    with _lock:
        return _open_streams


def refresh_devices() -> bool:
    """Re-read PortAudio's device list. Returns False when a stream is open (not safe)."""
    import time

    global _last_refresh
    with _lock:
        if _open_streams > 0:
            log.debug("portaudio refresh skipped: %d stream(s) open", _open_streams)
            return False
        try:
            import sounddevice as sd

            sd._terminate()
            sd._initialize()
            _last_refresh = time.time()
            log.info("portaudio device list refreshed (%d devices)", len(sd.query_devices()))
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("portaudio refresh failed: %s", exc)
            return False


def wasapi_hostapi_index() -> int | None:
    import sounddevice as sd

    for idx, api in enumerate(sd.query_hostapis()):
        if "wasapi" in api["name"].lower():
            return idx
    return None


def is_wasapi_device(index: int | None) -> bool:
    if index is None or index < 0:
        return False
    import sounddevice as sd

    try:
        api = sd.query_hostapis(sd.query_devices(index)["hostapi"])
        return "wasapi" in api["name"].lower()
    except Exception:  # noqa: BLE001
        return False


def wasapi_default_device(kind: str) -> int | None:
    """PortAudio's WASAPI default input/output device (a snapshot from the last init)."""
    import sounddevice as sd

    api_idx = wasapi_hostapi_index()
    if api_idx is None:
        return None
    api = sd.query_hostapis(api_idx)
    idx = api["default_output_device"] if kind == "output" else api["default_input_device"]
    return idx if idx is not None and idx >= 0 else None


def wasapi_settings(device: int | None) -> Any:
    """extra_settings for a stream: shared-mode WASAPI with automatic sample-rate conversion."""
    if not is_wasapi_device(device):
        return None
    import sounddevice as sd

    try:
        return sd.WasapiSettings(auto_convert=True)
    except TypeError:  # very old sounddevice without auto_convert
        return None


def device_name(index: int | None) -> str:
    if index is None:
        return "default"
    import sounddevice as sd

    try:
        return str(sd.query_devices(index)["name"])
    except Exception:  # noqa: BLE001
        return str(index)


def find_device(name_substring: str | None, kind: str, retry: bool = True) -> int | None:
    """Index of the first (preferably WASAPI) device of `kind` ("input"|"output") whose name
    contains the substring. Refreshes the device list once when nothing matches."""
    if not name_substring:
        return None
    import sounddevice as sd

    needle = name_substring.lower()
    channel_key = "max_input_channels" if kind == "input" else "max_output_channels"
    hostapis = sd.query_hostapis()
    candidates: list[tuple[int, int]] = []
    for idx, dev in enumerate(sd.query_devices()):
        if dev[channel_key] <= 0 or needle not in dev["name"].lower():
            continue
        api_name = hostapis[dev["hostapi"]]["name"].lower()
        candidates.append((0 if "wasapi" in api_name else 1, idx))
    if candidates:
        candidates.sort()
        return candidates[0][1]
    if retry and refresh_devices():
        return find_device(name_substring, kind, retry=False)
    return None
