"""Open apps, files and URLs in the background (or in front, when the user asked for it).

Launching with SW_SHOWNOACTIVATE is only a request: most apps call SetForegroundWindow on
startup anyway (measured: Paint held focus for ~3.5 s). So in background mode we
1. take LockSetForegroundWindow for the launch, which stops apps from activating themselves
   (the user's own clicks and Alt+Tab still work), measured 0 steals;
2. watch the desktop for a few seconds, pushing every new window to the bottom of the
   z-order and, as a fallback, handing focus back if anything still grabbed it.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as W
import time

from . import core
from .core import HWND_BOTTOM, SWP_NOACTIVATE, SWP_NOMOVE, SWP_NOSIZE, WindowInfo, user32

kernel32 = ctypes.windll.kernel32
shell32 = ctypes.windll.shell32
SW_SHOWNORMAL, SW_SHOWNOACTIVATE, SW_RESTORE = 1, 4, 9
SEE_MASK_NOCLOSEPROCESS, SEE_MASK_FLAG_NO_UI = 0x40, 0x400
QUIET = SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
LSFW_LOCK, LSFW_UNLOCK = 1, 2

user32.GetWindowThreadProcessId.restype = W.DWORD
user32.AttachThreadInput.argtypes = [W.DWORD, W.DWORD, W.BOOL]
user32.SetForegroundWindow.argtypes = [W.HWND]
user32.BringWindowToTop.argtypes = [W.HWND]
user32.SetWindowPos.argtypes = [W.HWND, W.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, W.UINT]


class _SEI(ctypes.Structure):
    _fields_ = [("cbSize", W.DWORD), ("fMask", W.ULONG), ("hwnd", W.HWND), ("lpVerb", W.LPCWSTR),
                ("lpFile", W.LPCWSTR), ("lpParameters", W.LPCWSTR), ("lpDirectory", W.LPCWSTR),
                ("nShow", ctypes.c_int), ("hInstApp", W.HINSTANCE), ("lpIDList", ctypes.c_void_p),
                ("lpClass", W.LPCWSTR), ("hkeyClass", W.HKEY), ("dwHotKey", W.DWORD),
                ("hIcon", W.HANDLE), ("hProcess", W.HANDLE)]


def _shell_open(target: str, args: str | None, cwd: str | None, show: int) -> int | None:
    """ShellExecuteEx: works for exe paths, names on PATH / App Paths, files, folders and URLs."""
    sei = _SEI(ctypes.sizeof(_SEI), SEE_MASK_NOCLOSEPROCESS | SEE_MASK_FLAG_NO_UI, None, "open",
               target, args, cwd, show)
    if not shell32.ShellExecuteExW(ctypes.byref(sei)):
        raise OSError(f"could not open {target!r} (error {ctypes.GetLastError()})")
    if sei.hProcess:
        pid = kernel32.GetProcessId(sei.hProcess)
        kernel32.CloseHandle(sei.hProcess)
        return pid
    return None  # handed to an existing process (URL, file association, single-instance app)


def _force_foreground(hwnd) -> bool:
    """SetForegroundWindow from a background process, borrowing the current foreground thread's input."""
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    fg = user32.GetForegroundWindow()
    me = kernel32.GetCurrentThreadId()
    them = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    attached = bool(them and them != me and user32.AttachThreadInput(me, them, True))
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(me, them, False)
    return user32.GetForegroundWindow() == hwnd


def bring_to_front(target=None, **find) -> WindowInfo:
    """Restore (if minimized) and focus a window. Only for when the user asked to see it."""
    win = target if isinstance(target, WindowInfo) else core.find_window(target, **find)
    _force_foreground(win.hwnd)
    return core.find_window(hwnd=win.hwnd)


def open_app(target: str, args: str | None = None, cwd: str | None = None, *, front: bool = False,
             wait: float = 8.0) -> dict:
    """Open an app/file/URL. Background by default: new windows go behind everything, focus stays put.

    front=True opens it normally and focuses its window (use when the user asked to open it).
    wait: how long to watch for the new window(s) to appear and settle.
    """
    before = {w.hwnd for w in core.list_windows()}
    user_fg = user32.GetForegroundWindow()
    locked = False
    if not front:
        locked = _lock_foreground(user_fg)
    try:
        pid = _shell_open(target, args, cwd, SW_SHOWNORMAL if front else SW_SHOWNOACTIVATE)
        new, stole = _watch(before, user_fg, front, wait)
    finally:
        if locked:
            user32.LockSetForegroundWindow(LSFW_UNLOCK)

    wins = list(new.values())
    if front and wins:
        _force_foreground(wins[0].hwnd)
    layers = {w.hwnd: w for w in core.list_windows()}
    return {
        "opened": target,
        "pid": pid,
        "front": front,
        "windows": [(layers.get(w.hwnd) or w).to_dict() for w in wins],
        "focus_returned_to_user": stole,
        "note": "" if wins else "no new window appeared (it may have reused an existing window, "
                                "or the app is still starting; check list_windows)",
    }


def _lock_foreground(user_fg) -> bool:
    """LockSetForegroundWindow: apps can't SetForegroundWindow themselves (user input still can).

    Only the foreground thread may take the lock, so borrow its input queue for the call.
    """
    if not user_fg:
        return False
    me = kernel32.GetCurrentThreadId()
    them = user32.GetWindowThreadProcessId(user_fg, None)
    attached = bool(them and them != me and user32.AttachThreadInput(me, them, True))
    try:
        return bool(user32.LockSetForegroundWindow(LSFW_LOCK))
    finally:
        if attached:
            user32.AttachThreadInput(me, them, False)


def _watch(before: set, user_fg, front: bool, wait: float) -> tuple[dict[int, WindowInfo], int]:
    """Collect the new windows; in background mode keep them at the back and keep focus with the user."""
    deadline = time.monotonic() + wait
    new: dict[int, WindowInfo] = {}
    stole = 0
    last_new = time.monotonic()
    tick = 0
    while time.monotonic() < deadline:
        if tick % 5 == 0:  # window scan every 50 ms, focus check every 10 ms
            for w in core.list_windows():
                if w.hwnd not in before and w.hwnd not in new:
                    new[w.hwnd] = w
                    last_new = time.monotonic()
                    if not front:
                        user32.SetWindowPos(w.hwnd, HWND_BOTTOM, 0, 0, 0, 0, QUIET)
        tick += 1
        fg = user32.GetForegroundWindow()
        if not front and user_fg and fg != user_fg and user32.IsWindow(user_fg):
            # something grabbed focus during our launch: our new window, or an existing
            # window of a single-instance app we just poked. Give it back.
            if fg in new or fg not in before:
                user32.SetWindowPos(fg, HWND_BOTTOM, 0, 0, 0, 0, QUIET)
            stole += 1
            _force_foreground(user_fg)
        if new and time.monotonic() - last_new > 1.0:
            break  # windows appeared and nothing new for a second: settled
        time.sleep(0.01)
    return new, stole
