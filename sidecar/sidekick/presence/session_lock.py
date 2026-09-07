"""Workstation lock state via WTSRegisterSessionNotification on a hidden window."""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
from ctypes import wintypes

log = logging.getLogger(__name__)

WM_WTSSESSION_CHANGE = 0x02B1
WTS_SESSION_LOCK = 0x7
WTS_SESSION_UNLOCK = 0x8
NOTIFY_FOR_THIS_SESSION = 0
WM_DESTROY = 0x0002
WM_QUIT = 0x0012

if sys.platform == "win32":
    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [
            ("style", wintypes.UINT),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
        ]

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)
    _kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    _kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    _kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    _user32.DefWindowProcW.restype = LRESULT
    _user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _user32.RegisterClassW.restype = wintypes.ATOM
    _user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    _user32.CreateWindowExW.restype = wintypes.HWND
    _user32.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
    ]
    _user32.DestroyWindow.argtypes = [wintypes.HWND]
    _user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    _user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    _user32.DispatchMessageW.restype = LRESULT
    _user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    _user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _user32.PostQuitMessage.argtypes = [ctypes.c_int]
    _wtsapi32.WTSRegisterSessionNotification.restype = wintypes.BOOL
    _wtsapi32.WTSRegisterSessionNotification.argtypes = [wintypes.HWND, wintypes.DWORD]
    _wtsapi32.WTSUnRegisterSessionNotification.argtypes = [wintypes.HWND]


def logonui_running() -> bool:
    """Fallback heuristic: the lock screen process is visible while the session is locked."""
    try:
        import psutil

        return any((p.info.get("name") or "").lower() == "logonui.exe" for p in psutil.process_iter(["name"]))
    except Exception:  # noqa: BLE001
        return False


class WinSessionLockBackend:
    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("Windows only")
        self._unlocked = not logonui_running()
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._hwnd = None
        self._ready = threading.Event()
        self._wndproc = None

    def is_unlocked(self) -> bool:
        return self._unlocked

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="session-lock", daemon=True)
        self._thread.start()
        self._ready.wait(3)

    def stop(self) -> None:
        if self._thread_id is not None:
            _user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        self._thread = None

    def _run(self) -> None:
        self._thread_id = _kernel32.GetCurrentThreadId()

        def wndproc(hwnd, msg, wparam, lparam):
            if msg == WM_WTSSESSION_CHANGE:
                if wparam == WTS_SESSION_LOCK:
                    self._unlocked = False
                    log.info("session locked")
                elif wparam == WTS_SESSION_UNLOCK:
                    self._unlocked = True
                    log.info("session unlocked")
                return 0
            if msg == WM_DESTROY:
                _user32.PostQuitMessage(0)
                return 0
            return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wndproc = WNDPROC(wndproc)
        hinst = _kernel32.GetModuleHandleW(None)
        wc = WNDCLASSW()
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = hinst
        wc.lpszClassName = "SidekickSessionWatch"
        if not _user32.RegisterClassW(ctypes.byref(wc)):
            err = ctypes.get_last_error()
            if err not in (0, 1410):  # ERROR_CLASS_ALREADY_EXISTS
                log.warning("RegisterClassW failed: %s", err)
        self._hwnd = _user32.CreateWindowExW(0, wc.lpszClassName, "Sidekick", 0, 0, 0, 0, 0, None, None, hinst, None)
        if not self._hwnd:
            log.warning("could not create hidden window for session notifications: %s", ctypes.get_last_error())
            self._ready.set()
            return
        if not _wtsapi32.WTSRegisterSessionNotification(self._hwnd, NOTIFY_FOR_THIS_SESSION):
            log.warning("WTSRegisterSessionNotification failed: %s", ctypes.get_last_error())
        self._ready.set()
        msg = wintypes.MSG()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))
        _wtsapi32.WTSUnRegisterSessionNotification(self._hwnd)
        _user32.DestroyWindow(self._hwnd)
        self._hwnd = None
