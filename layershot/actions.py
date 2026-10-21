"""Click, type and press keys in a window that stays behind the user's app.

Each action prefers UI Automation (no mouse, no focus). Otherwise the click or keystroke is
posted straight to the right child window as window messages, at the AI's own virtual cursor
position. The real mouse never moves. While an action runs, the foreground lock stops the
app from activating itself, and any dialog or popup it opens is placed right behind the
user's current window.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as W
import time
from contextlib import contextmanager

from . import activity, core, uia
from .core import WindowInfo, user32
from .launch import QUIET, _force_foreground, _lock_foreground, LSFW_UNLOCK

WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_LBUTTONDBLCLK = 0x200, 0x201, 0x202, 0x203
WM_RBUTTONDOWN, WM_RBUTTONUP, WM_MOUSEWHEEL = 0x204, 0x205, 0x20A
WM_KEYDOWN, WM_KEYUP, WM_CHAR = 0x100, 0x101, 0x102
MK_LBUTTON, MK_RBUTTON = 1, 2
CWP_SKIPINVISIBLE, CWP_SKIPDISABLED, CWP_SKIPTRANSPARENT = 1, 2, 4

user32.PostMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
user32.ChildWindowFromPointEx.argtypes = [W.HWND, W.POINT, W.UINT]
user32.ChildWindowFromPointEx.restype = W.HWND
user32.ScreenToClient.argtypes = [W.HWND, ctypes.POINTER(W.POINT)]

# the AI's own cursor, per window, in full-size screenshot pixels (never shown on the user's screen)
cursors: dict[int, tuple[int, int]] = {}
# scale of the last screenshot sent for each window (image px / real px), so x,y from the AI map back
scales: dict[int, float] = {}

KEYS = {"enter": 0x0D, "return": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B, "backspace": 0x08,
        "delete": 0x2E, "del": 0x2E, "space": 0x20, "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
        "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22, "insert": 0x2D,
        **{f"f{i}": 0x6F + i for i in range(1, 13)}}


class _GTI(ctypes.Structure):
    _fields_ = [("cbSize", W.DWORD), ("flags", W.DWORD), ("hwndActive", W.HWND), ("hwndFocus", W.HWND),
                ("hwndCapture", W.HWND), ("hwndMenuOwner", W.HWND), ("hwndMoveSize", W.HWND),
                ("hwndCaret", W.HWND), ("rcCaret", W.RECT)]


def _lparam(x: int, y: int) -> int:
    return (y & 0xFFFF) << 16 | (x & 0xFFFF)


def _origin(hwnd) -> tuple[int, int]:
    _, vis = core._frame_rect(hwnd)
    return vis.left, vis.top


def _target(target=None, **find) -> WindowInfo:
    win = target if isinstance(target, WindowInfo) else core.find_window(target, **find)
    if user32.IsIconic(win.hwnd):  # minimized windows can't take input: restore it at the back
        user32.SetWindowPos(win.hwnd, core.HWND_BOTTOM, 0, 0, 0, 0, QUIET)
        user32.ShowWindow(win.hwnd, core.SW_SHOWNOACTIVATE)
        user32.SetWindowPos(win.hwnd, core.HWND_BOTTOM, 0, 0, 0, 0, QUIET)
        time.sleep(0.3)
    return win


@contextmanager
def _behind_user(target: int, settle: float = 0.6):
    """Hold the foreground lock during an action; afterwards tuck any new window behind the user's.

    `target` is the window the AI is acting on. If it (or its app) is somehow the foreground window
    already, it is not the user's window: fall back to the last window the user really had.
    """
    global _last_user_fg
    fg = user32.GetForegroundWindow()
    if fg and _pid(fg) != _pid(target):
        _last_user_fg = fg
    user_fg = _last_user_fg if _last_user_fg and user32.IsWindow(_last_user_fg) else fg
    before = {w.hwnd for w in core.list_windows()}
    locked = _lock_foreground(user_fg)
    try:
        yield
        _flush(target)  # let the app handle what we posted while we're still watching
        end = time.monotonic() + settle
        tick = 0
        while time.monotonic() < end:
            if tick % 5 == 0:  # the window scan is the heavy part: every 50 ms
                for w in core.list_windows():
                    if w.hwnd not in before:
                        before.add(w.hwnd)
                        if user_fg:  # directly behind the user's window, not activated
                            user32.SetWindowPos(w.hwnd, user_fg, 0, 0, 0, 0, QUIET)
            fg = user32.GetForegroundWindow()  # focus is checked every 10 ms: steals last <= ~10 ms
            if user_fg and fg != user_fg and user32.IsWindow(user_fg):
                user32.SetWindowPos(fg, user_fg, 0, 0, 0, 0, QUIET)
                _force_foreground(user_fg)
            tick += 1
            time.sleep(0.01)
    finally:
        if locked:
            user32.LockSetForegroundWindow(LSFW_UNLOCK)
        if user_fg and user32.IsWindow(user_fg) and user32.GetForegroundWindow() != user_fg \
                and _pid(user32.GetForegroundWindow()) == _pid(target):
            _force_foreground(user_fg)  # last check: the target never keeps the user's focus


_last_user_fg = 0


def _pid(h) -> int:
    pid = W.DWORD()
    if h:
        user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
    return pid.value


def _flush(h, timeout_ms: int = 1000):
    """Round-trip a no-op message: returns once the app's thread has processed everything before it."""
    res = W.DWORD()
    user32.SendMessageTimeoutW(W.HWND(h), 0, 0, 0, 0x2, timeout_ms, ctypes.byref(res))  # WM_NULL, ABORTIFHUNG


def _deepest_child(top: int, sx: int, sy: int) -> int:
    """The child window under a screen point, found inside `top` even when `top` is covered."""
    h = top
    while True:
        pt = W.POINT(sx, sy)
        user32.ScreenToClient(h, ctypes.byref(pt))
        child = user32.ChildWindowFromPointEx(h, pt, CWP_SKIPINVISIBLE | CWP_SKIPDISABLED | CWP_SKIPTRANSPARENT)
        if not child or child == h:
            return h
        h = child


def _post_click(top: int, sx: int, sy: int, button: str, double: bool) -> int:
    h = _deepest_child(top, sx, sy)
    pt = W.POINT(sx, sy)
    user32.ScreenToClient(h, ctypes.byref(pt))
    lp = _lparam(pt.x, pt.y)
    down, up, mk = ((WM_RBUTTONDOWN, WM_RBUTTONUP, MK_RBUTTON) if button == "right"
                    else (WM_LBUTTONDOWN, WM_LBUTTONUP, MK_LBUTTON))
    user32.PostMessageW(h, WM_MOUSEMOVE, 0, lp)
    user32.PostMessageW(h, down, mk, lp)
    user32.PostMessageW(h, up, 0, lp)
    if double:
        user32.PostMessageW(h, WM_LBUTTONDBLCLK if button == "left" else down, mk, lp)
        user32.PostMessageW(h, up, 0, lp)
    return h


def _to_screen(hwnd, x: float, y: float) -> tuple[int, int]:
    """Screenshot pixels (as the AI saw them, possibly downscaled) -> screen pixels."""
    s = scales.get(hwnd, 1.0) or 1.0
    ox, oy = _origin(hwnd)
    return ox + round(x / s), oy + round(y / s)


def find_elements(target=None, query: str | None = None, limit: int = 150, **find) -> dict:
    win = _target(target, **find)
    s = scales.get(win.hwnd, 1.0)
    rows = uia.elements(win.hwnd, _origin(win.hwnd), query, limit)
    if s != 1.0:  # report rects in the same pixels as the AI's last screenshot
        for r in rows:
            r["rect"] = [round(v * s) for v in r["rect"]]
    activity.log(win, "find_elements", query or f"{len(rows)} controls", cursor=cursors.get(win.hwnd))
    return {"window": win.title, "elements": rows}


def click(target=None, element: str | None = None, x: float | None = None, y: float | None = None,
          button: str = "left", double: bool = False, **find) -> dict:
    win = _target(target, **find)
    h = win.hwnd
    with _behind_user(win.hwnd):
        if element is not None:
            el = uia.get(h, element)
            name = (el.CurrentName or element)[:40]
            if button == "left" and not double and (how := uia.activate(el)):
                l, t, r, b = uia.rect(el)
                _move_cursor(h, (l + r) // 2, (t + b) // 2)
                activity.log(win, "click", f"'{name}'", how, cursor=cursors.get(win.hwnd))
                return {"clicked": name, "method": f"accessibility ({how})"}
            l, t, r, b = uia.rect(el)
            sx, sy = (l + r) // 2, (t + b) // 2
        elif x is not None and y is not None:
            sx, sy = _to_screen(h, x, y)
            name = f"({round(x)}, {round(y)})"
        else:
            raise ValueError("give an element id (from find_elements) or x and y (screenshot pixels)")
        _post_click(h, sx, sy, button, double)
        _move_cursor(h, sx, sy)
    activity.log(win, "double-click" if double else f"{button}-click", name, "window message", cursor=cursors.get(win.hwnd))
    return {"clicked": name, "method": "window message (no mouse move)",
            "note": "check with screenshot_window: some apps ignore background clicks"}


def type_text(target=None, text: str = "", element: str | None = None, append: bool = False,
              enter: bool = False, **find) -> dict:
    win = _target(target, **find)
    h = win.hwnd
    with _behind_user(win.hwnd):
        method = None
        if element is not None:
            el = uia.get(h, element)
            if uia.set_value(el, text, append):
                method = "accessibility (value)"
            dest = uia.native_hwnd(el) or _focus_of(h)
            l, t, r, b = uia.rect(el)
            _move_cursor(h, (l + r) // 2, (t + b) // 2)
        else:
            dest = _focus_of(h)
        if method is None:
            for ch in text:
                user32.PostMessageW(dest, WM_CHAR, ord(ch), 1)
            method = "window message (WM_CHAR)"
        if enter:
            _post_key(dest, KEYS["enter"])
    activity.log(win, "type", repr(text[:40]) + (" + Enter" if enter else ""), method, cursor=cursors.get(win.hwnd))
    return {"typed": len(text), "method": method}


def press_key(target=None, key: str = "enter", element: str | None = None, **find) -> dict:
    win = _target(target, **find)
    vk = KEYS.get(key.lower()) or (ord(key.upper()) if len(key) == 1 else None)
    if vk is None:
        raise ValueError(f"unknown key {key!r}; known: {', '.join(sorted(KEYS))} or a single character")
    dest = uia.native_hwnd(uia.get(win.hwnd, element)) if element else _focus_of(win.hwnd)
    with _behind_user(win.hwnd):
        _post_key(dest or win.hwnd, vk)
    activity.log(win, "key", key, "window message", cursor=cursors.get(win.hwnd))
    return {"pressed": key}


def scroll(target=None, x: float | None = None, y: float | None = None, amount: int = -3, **find) -> dict:
    """amount: notches, negative = down."""
    win = _target(target, **find)
    h = win.hwnd
    if x is None or y is None:
        _, vis = core._frame_rect(h)
        sx, sy = (vis.left + vis.right) // 2, (vis.top + vis.bottom) // 2
    else:
        sx, sy = _to_screen(h, x, y)
    with _behind_user(win.hwnd):
        dest = _deepest_child(h, sx, sy)
        user32.PostMessageW(dest, WM_MOUSEWHEEL, (amount * 120 & 0xFFFF) << 16, _lparam(sx, sy))
        _move_cursor(h, sx, sy)
    activity.log(win, "scroll", f"{amount:+d}", "window message", cursor=cursors.get(win.hwnd))
    return {"scrolled": amount}


def _post_key(h, vk: int):
    user32.PostMessageW(h, WM_KEYDOWN, vk, 1)
    if vk == 0x0D:
        user32.PostMessageW(h, WM_CHAR, 0x0D, 1)
    user32.PostMessageW(h, WM_KEYUP, vk, 0xC0000001)


def _focus_of(top: int) -> int:
    """The control that has keyboard focus inside that window's thread (even while in the background)."""
    tid = user32.GetWindowThreadProcessId(top, None)
    gti = _GTI(ctypes.sizeof(_GTI))
    if user32.GetGUIThreadInfo(tid, ctypes.byref(gti)) and gti.hwndFocus:
        return gti.hwndFocus
    return top


def _move_cursor(hwnd, sx: int, sy: int):
    ox, oy = _origin(hwnd)
    cursors[hwnd] = (sx - ox, sy - oy)


def cursor_in_image(hwnd) -> tuple[int, int] | None:
    c = cursors.get(hwnd)
    if c is None:
        return None
    s = scales.get(hwnd, 1.0)
    return round(c[0] * s), round(c[1] * s)
