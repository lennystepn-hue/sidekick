"""Seconds since the last keyboard/mouse input (GetLastInputInfo)."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


class WinIdleBackend:
    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("Windows only")
        self._user32 = ctypes.windll.user32
        self._kernel32 = ctypes.windll.kernel32

    def idle_seconds(self) -> float:
        info = _LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(_LASTINPUTINFO)
        if not self._user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        now = self._kernel32.GetTickCount() & 0xFFFFFFFF
        elapsed = (now - info.dwTime) & 0xFFFFFFFF
        return elapsed / 1000.0
