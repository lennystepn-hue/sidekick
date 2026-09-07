"""Classic Bluetooth (A2DP/HFP) device status through the Win32 Bluetooth API (bthprops.cpl).

`BluetoothFindFirstDevice` lists paired devices with a live `fConnected` flag, which is all
presence detection needs. `BluetoothSetServiceState` toggling the audio profiles is the
usual trick to make Windows re-establish the connection from the PC side.
"""

from __future__ import annotations

import asyncio
import ctypes
import logging
import subprocess
import sys
import time
from ctypes import wintypes
from dataclasses import dataclass

log = logging.getLogger(__name__)

AUDIO_SINK_GUID = "{0000110B-0000-1000-8000-00805F9B34FB}"
HANDSFREE_GUID = "{0000111E-0000-1000-8000-00805F9B34FB}"
BATTERY_PROPERTY_KEY = "{104EA319-6EE2-4701-BD47-8DDBF425BBE5} 2"


@dataclass(slots=True)
class BtDevice:
    name: str
    address: int
    connected: bool
    remembered: bool
    authenticated: bool

    @property
    def address_str(self) -> str:
        b = self.address.to_bytes(6, "big")
        return ":".join(f"{x:02X}" for x in b)


if sys.platform == "win32":

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", ctypes.c_ubyte * 8),
        ]

        @classmethod
        def from_string(cls, text: str) -> GUID:
            import uuid

            u = uuid.UUID(text.strip("{}"))
            g = cls()
            g.Data1, g.Data2, g.Data3 = u.fields[0], u.fields[1], u.fields[2]
            rest = u.bytes[8:]
            for i in range(8):
                g.Data4[i] = rest[i]
            return g

    class BLUETOOTH_DEVICE_SEARCH_PARAMS(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("fReturnAuthenticated", wintypes.BOOL),
            ("fReturnRemembered", wintypes.BOOL),
            ("fReturnUnknown", wintypes.BOOL),
            ("fReturnConnected", wintypes.BOOL),
            ("fIssueInquiry", wintypes.BOOL),
            ("cTimeoutMultiplier", ctypes.c_ubyte),
            ("hRadio", wintypes.HANDLE),
        ]

    class SYSTEMTIME(ctypes.Structure):
        _fields_ = [(n, wintypes.WORD) for n in ("wYear", "wMonth", "wDayOfWeek", "wDay", "wHour", "wMinute", "wSecond", "wMilliseconds")]

    class BLUETOOTH_DEVICE_INFO(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("Address", ctypes.c_ulonglong),
            ("ulClassofDevice", wintypes.ULONG),
            ("fConnected", wintypes.BOOL),
            ("fRemembered", wintypes.BOOL),
            ("fAuthenticated", wintypes.BOOL),
            ("stLastSeen", SYSTEMTIME),
            ("stLastUsed", SYSTEMTIME),
            ("szName", wintypes.WCHAR * 248),
        ]

    class BLUETOOTH_FIND_RADIO_PARAMS(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD)]

    _bt = ctypes.WinDLL("bthprops.cpl")
    _bt.BluetoothFindFirstDevice.restype = wintypes.HANDLE
    _bt.BluetoothFindFirstDevice.argtypes = [ctypes.POINTER(BLUETOOTH_DEVICE_SEARCH_PARAMS), ctypes.POINTER(BLUETOOTH_DEVICE_INFO)]
    _bt.BluetoothFindNextDevice.restype = wintypes.BOOL
    _bt.BluetoothFindNextDevice.argtypes = [wintypes.HANDLE, ctypes.POINTER(BLUETOOTH_DEVICE_INFO)]
    _bt.BluetoothFindDeviceClose.restype = wintypes.BOOL
    _bt.BluetoothFindDeviceClose.argtypes = [wintypes.HANDLE]
    _bt.BluetoothFindFirstRadio.restype = wintypes.HANDLE
    _bt.BluetoothFindFirstRadio.argtypes = [ctypes.POINTER(BLUETOOTH_FIND_RADIO_PARAMS), ctypes.POINTER(wintypes.HANDLE)]
    _bt.BluetoothFindRadioClose.restype = wintypes.BOOL
    _bt.BluetoothFindRadioClose.argtypes = [wintypes.HANDLE]
    _bt.BluetoothSetServiceState.restype = wintypes.DWORD
    _bt.BluetoothSetServiceState.argtypes = [wintypes.HANDLE, ctypes.POINTER(BLUETOOTH_DEVICE_INFO), ctypes.POINTER(GUID), wintypes.DWORD]


def _no_window_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


class WinBluetoothBackend:
    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("Windows only")
        self._battery_cache: tuple[float, int | None] = (0.0, None)

    def list_devices(self) -> list[BtDevice]:
        params = BLUETOOTH_DEVICE_SEARCH_PARAMS()
        params.dwSize = ctypes.sizeof(params)
        params.fReturnAuthenticated = True
        params.fReturnRemembered = True
        params.fReturnUnknown = False
        params.fReturnConnected = True
        params.fIssueInquiry = False
        params.cTimeoutMultiplier = 0
        params.hRadio = None
        info = BLUETOOTH_DEVICE_INFO()
        info.dwSize = ctypes.sizeof(info)
        out: list[BtDevice] = []
        handle = _bt.BluetoothFindFirstDevice(ctypes.byref(params), ctypes.byref(info))
        if not handle:
            return out
        try:
            while True:
                out.append(
                    BtDevice(
                        name=info.szName,
                        address=int(info.Address),
                        connected=bool(info.fConnected),
                        remembered=bool(info.fRemembered),
                        authenticated=bool(info.fAuthenticated),
                    )
                )
                info = BLUETOOTH_DEVICE_INFO()
                info.dwSize = ctypes.sizeof(info)
                if not _bt.BluetoothFindNextDevice(handle, ctypes.byref(info)):
                    break
        finally:
            _bt.BluetoothFindDeviceClose(handle)
        return out

    def find(self, name_substring: str) -> BtDevice | None:
        needle = name_substring.lower()
        for dev in self.list_devices():
            if needle in dev.name.lower():
                return dev
        return None

    def is_connected(self, name_substring: str) -> bool | None:
        try:
            dev = self.find(name_substring)
        except Exception as exc:  # noqa: BLE001
            log.debug("bluetooth query failed: %s", exc)
            return None
        return None if dev is None else dev.connected

    def set_service_state(self, device: BtDevice, service_guid: str, enable: bool) -> int:
        radio_params = BLUETOOTH_FIND_RADIO_PARAMS()
        radio_params.dwSize = ctypes.sizeof(radio_params)
        hradio = wintypes.HANDLE()
        find = _bt.BluetoothFindFirstRadio(ctypes.byref(radio_params), ctypes.byref(hradio))
        if not find:
            raise OSError("Kein Bluetooth-Adapter gefunden (Radio nicht verfügbar)")
        try:
            info = BLUETOOTH_DEVICE_INFO()
            info.dwSize = ctypes.sizeof(info)
            info.Address = device.address
            guid = GUID.from_string(service_guid)
            return int(_bt.BluetoothSetServiceState(hradio, ctypes.byref(info), ctypes.byref(guid), 1 if enable else 0))
        finally:
            _bt.BluetoothFindRadioClose(find)
            ctypes.windll.kernel32.CloseHandle(hradio)

    def connect(self, name_substring: str) -> str:
        dev = self.find(name_substring)
        if dev is None:
            raise LookupError(f"Kein gepaartes Bluetooth-Gerät mit Namen '{name_substring}'")
        if dev.connected:
            return f"{dev.name} ist bereits verbunden"
        results = []
        for guid in (AUDIO_SINK_GUID, HANDSFREE_GUID):
            self.set_service_state(dev, guid, False)
            time.sleep(0.3)
            results.append(self.set_service_state(dev, guid, True))
        time.sleep(1.5)
        after = self.find(name_substring)
        if after and after.connected:
            return f"{dev.name} verbunden"
        return f"Verbindungsversuch an {dev.name} gesendet (Status {results}); die Brille muss eingeschaltet und in Reichweite sein"

    def disconnect(self, name_substring: str) -> str:
        dev = self.find(name_substring)
        if dev is None:
            raise LookupError(f"Kein gepaartes Bluetooth-Gerät mit Namen '{name_substring}'")
        for guid in (AUDIO_SINK_GUID, HANDSFREE_GUID):
            self.set_service_state(dev, guid, False)
        time.sleep(0.5)
        for guid in (AUDIO_SINK_GUID, HANDSFREE_GUID):
            self.set_service_state(dev, guid, True)
        return f"Audio-Profile von {dev.name} getrennt und wieder freigegeben"

    def battery(self, name_substring: str, max_age_s: float = 60) -> int | None:
        ts, value = self._battery_cache
        if time.time() - ts < max_age_s:
            return value
        value = read_battery_sync(name_substring)
        self._battery_cache = (time.time(), value)
        return value


def read_battery_sync(name_substring: str) -> int | None:
    """Battery level Windows shows for Bluetooth headsets (HFP battery indicator)."""
    if sys.platform != "win32":
        return None
    script = (
        "Get-PnpDevice -Class Bluetooth -PresentOnly -ErrorAction SilentlyContinue | "
        f"Where-Object {{ $_.FriendlyName -like '*{name_substring.replace(chr(39), '')}*' }} | ForEach-Object {{ "
        f"(Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName '{BATTERY_PROPERTY_KEY}' -ErrorAction SilentlyContinue).Data }} | "
        "Where-Object { $_ -ne $null } | Select-Object -First 1"
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=15, creationflags=_no_window_flags(),
        ).stdout.strip()
    except Exception as exc:  # noqa: BLE001
        log.debug("battery query failed: %s", exc)
        return None
    try:
        return int(out.splitlines()[0]) if out else None
    except ValueError:
        return None


async def read_battery(name_substring: str) -> int | None:
    return await asyncio.to_thread(read_battery_sync, name_substring)


if __name__ == "__main__":
    b = WinBluetoothBackend()
    for d in b.list_devices():
        print(d)
    print("battery:", b.battery(sys.argv[1] if len(sys.argv) > 1 else "Ray-Ban"))
