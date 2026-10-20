"""Capture any top-level window without bringing it to the front.

Covered windows are read straight from their DWM redirection surface with
PrintWindow(PW_RENDERFULLCONTENT). Minimized windows have no surface, so they are
restored *without activation* at the bottom of the z-order, captured, and minimized
again. Chromium/Electron apps stop painting while fully covered, so every capture
forces a repaint and retries until the image is no longer blank.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as W
import sys
import threading
import time
from dataclasses import asdict, dataclass

from PIL import Image

if sys.platform != "win32":
    raise ImportError("layershot only works on Windows")

user32, gdi32, dwmapi, kernel32 = (ctypes.windll.user32, ctypes.windll.gdi32,
                                  ctypes.windll.dwmapi, ctypes.windll.kernel32)
user32.GetForegroundWindow.restype = W.HWND
gdi32.CreateCompatibleDC.restype = W.HDC
gdi32.CreateCompatibleBitmap.restype = W.HBITMAP
user32.GetWindowDC.restype = W.HDC
gdi32.SelectObject.restype = W.HGDIOBJ
kernel32.OpenProcess.restype = W.HANDLE
# 64-bit handles overflow ctypes' default int conversion, so spell out the GDI signatures
user32.GetWindowDC.argtypes = [W.HWND]
user32.ReleaseDC.argtypes = [W.HWND, W.HDC]
user32.PrintWindow.argtypes = [W.HWND, W.HDC, W.UINT]
gdi32.CreateCompatibleDC.argtypes = [W.HDC]
gdi32.CreateCompatibleBitmap.argtypes = [W.HDC, ctypes.c_int, ctypes.c_int]
gdi32.SelectObject.argtypes = [W.HDC, W.HGDIOBJ]
gdi32.DeleteObject.argtypes = [W.HGDIOBJ]
gdi32.DeleteDC.argtypes = [W.HDC]
gdi32.GetDIBits.argtypes = [W.HDC, W.HBITMAP, W.UINT, W.UINT, ctypes.c_void_p,
                            ctypes.c_void_p, W.UINT]
kernel32.CloseHandle.argtypes = [W.HANDLE]

try:  # per-monitor v2, so rects and pixels are physical (fails harmlessly if already set)
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except Exception:
    pass

PW_RENDERFULLCONTENT = 2
SW_SHOWNOACTIVATE, SW_SHOWMINNOACTIVE = 4, 7
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x1, 0x2, 0x10
HWND_BOTTOM = W.HWND(1)
RDW_INVALIDATE, RDW_ERASE, RDW_ALLCHILDREN, RDW_UPDATENOW, RDW_FRAME = 0x1, 0x4, 0x80, 0x100, 0x400
GWL_EXSTYLE, WS_EX_TOOLWINDOW = -20, 0x80
DWMWA_EXTENDED_FRAME_BOUNDS, DWMWA_CLOAKED = 9, 14

_lock = threading.Lock()


@dataclass
class WindowInfo:
    layer: int          # 0 = frontmost app window
    hwnd: int
    title: str
    process: str
    minimized: bool
    foreground: bool

    def to_dict(self):
        return asdict(self)


def _title(h) -> str:
    n = user32.GetWindowTextLengthW(h)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(h, buf, n + 1)
    return buf.value


def _process_name(h) -> str:
    pid = W.DWORD()
    user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
    hp = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not hp:
        return ""
    try:
        buf, size = ctypes.create_unicode_buffer(1024), W.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(hp, 0, buf, ctypes.byref(size)):
            return buf.value.rsplit("\\", 1)[-1]
        return ""
    finally:
        kernel32.CloseHandle(hp)


def _cloaked(h) -> bool:
    v = ctypes.c_int(0)
    dwmapi.DwmGetWindowAttribute(W.HWND(h), DWMWA_CLOAKED, ctypes.byref(v), ctypes.sizeof(v))
    return bool(v.value)


def list_windows(include_minimized: bool = True) -> list[WindowInfo]:
    """App windows in z-order, front to back (what you'd see in Alt+Tab)."""
    handles: list[int] = []

    @ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
    def cb(h, _):
        handles.append(h)
        return True

    user32.EnumWindows(cb, 0)
    fg = user32.GetForegroundWindow()
    out: list[WindowInfo] = []
    for h in handles:
        if not user32.IsWindowVisible(h) or _cloaked(h):
            continue
        if user32.GetWindowLongW(W.HWND(h), GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
            continue
        title = _title(h)
        if not title or title == "Program Manager":
            continue
        minimized = bool(user32.IsIconic(h))
        if not minimized:
            r = W.RECT()
            user32.GetWindowRect(W.HWND(h), ctypes.byref(r))
            if r.right - r.left <= 1 or r.bottom - r.top <= 1:
                continue
        elif not include_minimized:
            continue
        out.append(WindowInfo(len(out), int(h), title, _process_name(h), minimized, h == fg))
    return out


def find_window(target: int | str | None = None, *, layer: int | None = None,
                title: str | None = None, process: str | None = None,
                hwnd: int | None = None) -> WindowInfo:
    """Pick a window by layer number, title substring, process name or raw handle.

    A bare `target` is treated as a layer if it's an int (or digit string), else a title.
    """
    if target is not None:
        if isinstance(target, int) or str(target).isdigit():
            layer = int(target)
        else:
            title = str(target)
    wins = list_windows()
    if hwnd is not None:
        for w in wins:
            if w.hwnd == hwnd:
                return w
        if user32.IsWindow(W.HWND(hwnd)):
            return WindowInfo(-1, hwnd, _title(hwnd), _process_name(hwnd),
                              bool(user32.IsIconic(hwnd)), False)
        raise LookupError(f"no window with hwnd {hwnd}")
    if layer is not None:
        if not 0 <= layer < len(wins):
            raise LookupError(f"layer {layer} out of range (0..{len(wins) - 1})")
        return wins[layer]
    # "Bambu Studio" should find "plate - BambuStudio" and bambu-studio.exe: compare without spaces/punctuation
    t, p = _norm(title), _norm(process).removesuffix("exe")
    for w in wins:
        if t and t not in _norm(w.title) and t not in _norm(w.process):
            continue
        if p and p not in _norm(w.process):
            continue
        if t or p:
            return w
    open_list = "; ".join(f"{w.layer}: {w.title} ({w.process})" for w in wins[:20])
    raise LookupError(f"no window matching title={title!r} process={process!r}. Open windows: {open_list}")


def _norm(s: str | None) -> str:
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def _frame_rect(h) -> tuple[W.RECT, W.RECT]:
    outer, vis = W.RECT(), W.RECT()
    user32.GetWindowRect(W.HWND(h), ctypes.byref(outer))
    if dwmapi.DwmGetWindowAttribute(W.HWND(h), DWMWA_EXTENDED_FRAME_BOUNDS,
                                    ctypes.byref(vis), ctypes.sizeof(vis)) != 0:
        vis = outer
    return outer, vis


class _BIH(ctypes.Structure):
    _fields_ = [("biSize", W.DWORD), ("biWidth", W.LONG), ("biHeight", W.LONG),
                ("biPlanes", W.WORD), ("biBitCount", W.WORD), ("biCompression", W.DWORD),
                ("biSizeImage", W.DWORD), ("biXPelsPerMeter", W.LONG),
                ("biYPelsPerMeter", W.LONG), ("biClrUsed", W.DWORD), ("biClrImportant", W.DWORD)]


def _print_window(h) -> Image.Image:
    outer, vis = _frame_rect(h)
    w, ht = outer.right - outer.left, outer.bottom - outer.top
    if w <= 0 or ht <= 0:
        raise RuntimeError("window has no size")
    hdc = user32.GetWindowDC(W.HWND(h))
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, ht)
    old = gdi32.SelectObject(mdc, bmp)
    try:
        if not user32.PrintWindow(W.HWND(h), mdc, PW_RENDERFULLCONTENT):
            raise RuntimeError("PrintWindow failed")
        bi = _BIH(ctypes.sizeof(_BIH), w, -ht, 1, 32, 0, 0, 0, 0, 0, 0)
        buf = ctypes.create_string_buffer(w * ht * 4)
        gdi32.GetDIBits(mdc, bmp, 0, ht, buf, ctypes.byref(bi), 0)
    finally:
        gdi32.SelectObject(mdc, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mdc)
        user32.ReleaseDC(W.HWND(h), hdc)
    img = Image.frombuffer("RGB", (w, ht), buf, "raw", "BGRX", 0, 1)
    # drop the invisible resize border Windows 10/11 adds around every window
    box = (vis.left - outer.left, vis.top - outer.top, vis.right - outer.left, vis.bottom - outer.top)
    if box != (0, 0, w, ht) and box[2] > box[0] and box[3] > box[1]:
        img = img.crop(box)
    return img


def _looks_blank(img: Image.Image) -> bool:
    lo_hi = img.resize((48, 48)).getextrema()
    return all(hi - lo < 6 for lo, hi in lo_hi)


def _repaint(h):
    user32.RedrawWindow(W.HWND(h), None, None,
                        RDW_INVALIDATE | RDW_ERASE | RDW_ALLCHILDREN | RDW_UPDATENOW | RDW_FRAME)


def capture(target: int | str | WindowInfo | None = None, *, keep_open: bool = False,
            timeout: float = 3.0, **find) -> tuple[Image.Image, WindowInfo]:
    """Screenshot a window without focusing it.

    keep_open: leave a previously minimized window restored (at the back) afterwards.
    timeout:   how long to keep forcing repaints while the capture comes back blank.
    """
    win = target if isinstance(target, WindowInfo) else find_window(target, **find)
    h = win.hwnd
    with _lock:
        fg = user32.GetForegroundWindow()
        was_min = bool(user32.IsIconic(h))
        if was_min:
            quiet = SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
            user32.SetWindowPos(W.HWND(h), HWND_BOTTOM, 0, 0, 0, 0, quiet)
            user32.ShowWindow(W.HWND(h), SW_SHOWNOACTIVATE)
            user32.SetWindowPos(W.HWND(h), HWND_BOTTOM, 0, 0, 0, 0, quiet)
        try:
            deadline = time.monotonic() + timeout
            delay = 0.25 if was_min else 0.05
            while True:
                _repaint(h)
                time.sleep(delay)
                img = _print_window(h)
                if not _looks_blank(img) or time.monotonic() >= deadline:
                    break
                delay = 0.25
        finally:
            if was_min and not keep_open:
                user32.ShowWindow(W.HWND(h), SW_SHOWMINNOACTIVE)
            if fg and user32.GetForegroundWindow() != fg:  # never expected, but never leave the user stranded
                user32.SetForegroundWindow(W.HWND(fg))
    return img, win
