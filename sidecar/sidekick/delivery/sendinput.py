"""Experimental: paste the clipboard into the foreground window and press Enter (SendInput)."""

from __future__ import annotations

import ctypes
import logging
import sys
import time
from ctypes import wintypes

log = logging.getLogger(__name__)

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
VK_CONTROL = 0x11
VK_RETURN = 0x0D
VK_V = 0x56

if sys.platform == "win32":
    ULONG_PTR = ctypes.c_size_t

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class _INPUT_UNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("padding", ctypes.c_byte * 32)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUT_UNION)]

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    _user32.SendInput.restype = wintypes.UINT
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]


def _key(vk: int, up: bool = False) -> INPUT:
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.u.ki = KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP if up else 0, 0, 0)
    return inp


def foreground_window_title() -> str:
    if sys.platform != "win32":
        return ""
    hwnd = _user32.GetForegroundWindow()
    buf = ctypes.create_unicode_buffer(512)
    _user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def paste_and_enter(press_enter: bool = True, delay_s: float = 0.08) -> str:
    """Ctrl+V (+ Enter) into whatever window has focus. Returns that window's title."""
    if sys.platform != "win32":
        raise RuntimeError("Windows only")
    title = foreground_window_title()
    seq = [_key(VK_CONTROL), _key(VK_V), _key(VK_V, up=True), _key(VK_CONTROL, up=True)]
    arr = (INPUT * len(seq))(*seq)
    sent = _user32.SendInput(len(seq), arr, ctypes.sizeof(INPUT))
    if sent != len(seq):
        raise OSError(f"SendInput sent {sent}/{len(seq)} events")
    if press_enter:
        time.sleep(delay_s)
        seq = [_key(VK_RETURN), _key(VK_RETURN, up=True)]
        arr = (INPUT * len(seq))(*seq)
        _user32.SendInput(len(seq), arr, ctypes.sizeof(INPUT))
    log.info("pasted into foreground window %r", title)
    return title
