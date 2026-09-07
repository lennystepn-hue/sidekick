"""Low-level keyboard hook that intercepts media keys (VK_MEDIA_*).

Bluetooth AVRCP commands from the glasses reach Windows as media key presses. A
WH_KEYBOARD_LL hook sees them first and may swallow them (return 1) so that Spotify or
the browser do not react. The hook needs a thread with a message pump.
"""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
from collections.abc import Callable
from ctypes import wintypes
from typing import Protocol

from .engine import MEDIA_KEYS

log = logging.getLogger(__name__)

WH_KEYBOARD_LL = 13
HC_ACTION = 0
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_QUIT = 0x0012
LLKHF_INJECTED = 0x10

# on_key(key_name, swallowed, injected)
KeyHandler = Callable[[str, bool, bool], None]


class MediaKeyHook(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...


if sys.platform == "win32":
    ULONG_PTR = ctypes.c_size_t
    LRESULT = ctypes.c_ssize_t
    HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

    class KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("vkCode", wintypes.DWORD),
            ("scanCode", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    _kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    _kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    _user32.SetWindowsHookExW.restype = wintypes.HHOOK
    _user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
    _user32.CallNextHookEx.restype = LRESULT
    _user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
    _user32.UnhookWindowsHookEx.restype = wintypes.BOOL
    _user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
    _user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    _user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    _user32.DispatchMessageW.restype = LRESULT
    _user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    _user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]


class WinMediaKeyHook:
    def __init__(self, on_key: KeyHandler, swallow: Callable[[], bool]) -> None:
        if sys.platform != "win32":
            raise RuntimeError("Windows only")
        self._on_key = on_key
        self._swallow = swallow
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._hook = None
        self._proc = None
        self._pending_up: set[int] = set()
        self._ready = threading.Event()

    @property
    def installed(self) -> bool:
        return bool(self._hook)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="media-key-hook", daemon=True)
        self._thread.start()
        self._ready.wait(3)

    def stop(self) -> None:
        if self._thread_id is not None:
            _user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        self._thread = None

    def _callback(self, n_code: int, w_param: int, l_param: int) -> int:
        if n_code == HC_ACTION:
            kb = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            vk = int(kb.vkCode)
            if vk in MEDIA_KEYS:
                if w_param in (WM_KEYDOWN, WM_SYSKEYDOWN):
                    swallow = False
                    try:
                        swallow = bool(self._swallow())
                        self._on_key(MEDIA_KEYS[vk], swallow, bool(kb.flags & LLKHF_INJECTED))
                    except Exception:  # noqa: BLE001
                        log.exception("media key handler failed")
                    if swallow:
                        self._pending_up.add(vk)
                        return 1
                elif w_param in (WM_KEYUP, WM_SYSKEYUP) and vk in self._pending_up:
                    self._pending_up.discard(vk)
                    return 1
        return _user32.CallNextHookEx(None, n_code, w_param, l_param)

    def _run(self) -> None:
        self._thread_id = _kernel32.GetCurrentThreadId()
        self._proc = HOOKPROC(self._callback)
        self._hook = _user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, _kernel32.GetModuleHandleW(None), 0)
        if not self._hook:
            log.error("SetWindowsHookEx failed: %s", ctypes.get_last_error())
            self._ready.set()
            return
        log.info("media key hook installed")
        self._ready.set()
        msg = wintypes.MSG()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))
        _user32.UnhookWindowsHookEx(self._hook)
        self._hook = None
        log.info("media key hook removed")


class FakeMediaKeyHook:
    def __init__(self, on_key: KeyHandler, swallow: Callable[[], bool]) -> None:
        self.on_key = on_key
        self.swallow = swallow
        self.started = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def press(self, key: str, injected: bool = False) -> bool:
        swallowed = self.swallow()
        self.on_key(key, swallowed, injected)
        return swallowed
