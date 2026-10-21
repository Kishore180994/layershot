"""Floating "AI view": a live picture of the window the AI is working in, plus what it's doing.

- Never takes focus (WS_EX_NOACTIVATE), stays on top, hidden from Alt+Tab and layershot's own list.
- Live view: a DWM thumbnail of the target window (the same thing taskbar previews use). It's live
  even while the window is covered, and costs almost nothing.
- Drag the top bar to move it, drag the corner to resize, × to close (it stays closed, even across
  restarts, until the hotkey brings it back).
- "Bring forward" (or double-click the live view) puts the AI's window in front for the user.
- Hotkey (default Ctrl+Alt+L, set LAYERSHOT_HOTKEY or prefs "hotkey") shows/hides it.
Run: `layershot viewer` (agents start it automatically on their first action).
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as W
import json
import os
import sys
import threading
import time
import tkinter as tk

from . import activity, core  # core sets per-monitor DPI awareness before any window exists

user32, dwmapi, kernel32 = core.user32, ctypes.windll.dwmapi, ctypes.windll.kernel32
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowLongPtrW.argtypes = [W.HWND, ctypes.c_int]
user32.SetWindowLongPtrW.argtypes = [W.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.GetAncestor.restype = W.HWND
user32.GetAncestor.argtypes = [W.HWND, W.UINT]
dwmapi.DwmRegisterThumbnail.argtypes = [W.HWND, W.HWND, ctypes.POINTER(ctypes.c_void_p)]
dwmapi.DwmUnregisterThumbnail.argtypes = [ctypes.c_void_p]
dwmapi.DwmQueryThumbnailSourceSize.argtypes = [ctypes.c_void_p, ctypes.POINTER(W.SIZE)]
kernel32.CreateMutexW.restype = W.HANDLE

GWL_EXSTYLE, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW, WS_EX_TOPMOST = -20, 0x08000000, 0x80, 0x8
SW_HIDE, SW_SHOWNOACTIVATE = 0, 4
HWND_TOPMOST = W.HWND(-1)
SWP_NOMOVE, SWP_NOSIZE, SWP_NOACTIVATE = 0x2, 0x1, 0x10
WM_HOTKEY, MOD = 0x312, {"alt": 1, "ctrl": 2, "control": 2, "shift": 4, "win": 8}
MOD_NOREPEAT = 0x4000

# Pick with `layershot viewer --theme hud` (prefs "theme"), or LAYERSHOT_THEME. A dict in prefs "theme"
# overrides single keys, e.g. {"base": "hud", "accent": "#ff9900"}.
THEMES = {
    "default": dict(bg="#101418", bar="#1b2128", border="#30363d", fg="#e6edf3", dim="#8b949e",
                    accent="#58a6ff", danger="#ff7b72", cursor="#ff00c8", font="Segoe UI", mono="Consolas",
                    caps=False, brackets=False),
    # cyan HUD: navy glass panels, cyan hairline border, corner brackets, spaced caps headers
    "hud": dict(bg="#030e1a", bar="#082a3a", border="#10556a", fg="#d7f6ff", dim="#6fb4c9",
                accent="#2ad8ff", danger="#ff4d5e", cursor="#ffb547", font="Bahnschrift",
                mono="Cascadia Mono", caps=True, brackets=True),
}


def _theme() -> dict:
    p = os.environ.get("LAYERSHOT_THEME") or activity.prefs().get("theme") or "default"
    if isinstance(p, dict):
        return THEMES.get(p.get("base", "default"), THEMES["default"]) | {k: v for k, v in p.items() if k != "base"}
    return THEMES.get(p, THEMES["default"])


def _spaced(s: str) -> str:
    """Letter-spaced caps (Tk has no letter-spacing)."""
    return " ".join(s.upper())


class _ThumbProps(ctypes.Structure):
    _fields_ = [("dwFlags", W.DWORD), ("rcDestination", W.RECT), ("rcSource", W.RECT),
                ("opacity", ctypes.c_ubyte), ("fVisible", W.BOOL), ("fSourceClientAreaOnly", W.BOOL)]


def _parse_hotkey(spec: str) -> tuple[int, int]:
    *mods, key = [p.strip().lower() for p in spec.split("+")]
    m = 0
    for p in mods:
        m |= MOD[p]
    vk = ord(key.upper()) if len(key) == 1 else 0x6F + int(key[1:]) if key.startswith("f") else 0
    return m | MOD_NOREPEAT, vk


class Viewer:
    def __init__(self):
        self.user_fg = user32.GetForegroundWindow()  # the user's window, before we exist
        self.hotkey =os.environ.get("LAYERSHOT_HOTKEY") or activity.prefs().get("hotkey") or "ctrl+alt+l"
        self.toggle_requested = threading.Event()
        self.hotkey_ok = threading.Event()
        threading.Thread(target=self._hotkey_loop, daemon=True).start()

        self.root = root = tk.Tk()
        root.withdraw()  # never let Tk map (and activate) it; we show it ourselves without activation
        root.overrideredirect(True)
        dpi = user32.GetDpiForSystem() or 96
        root.tk.call("tk", "scaling", dpi / 72)
        self.px = lambda v: round(v * dpi / 96)
        self.T = T = _theme()
        cap = _spaced if T["caps"] else (lambda s: s)
        root.configure(bg=T["border"])  # 1 px hairline border around everything
        body = tk.Frame(root, bg=T["bg"])
        body.pack(fill="both", expand=True, padx=1, pady=1)

        bar = tk.Frame(body, bg=T["bar"], height=self.px(26))
        bar.pack(fill="x")
        bar.pack_propagate(False)
        dot = tk.Canvas(bar, width=self.px(18), height=self.px(26), bg=T["bar"], highlightthickness=0)
        dot.pack(side="left", padx=(self.px(6), 0))
        r, cy = self.px(3), self.px(13)
        dot.create_oval(self.px(9) - r - 2, cy - r - 2, self.px(9) + r + 2, cy + r + 2, fill=T["border"], outline="")
        dot.create_oval(self.px(9) - r, cy - r, self.px(9) + r, cy + r, fill=T["accent"], outline="")
        self.label = tk.Label(bar, text=cap("AI view"), bg=T["bar"], fg=T["accent"],
                              font=(T["font"], 8, "bold" if not T["caps"] else "normal"))
        self.label.pack(side="left")
        self.title = tk.Label(bar, text="", bg=T["bar"], fg=T["dim"], font=(T["mono"], 8), anchor="w")
        self.title.pack(side="left", fill="x", expand=True, padx=self.px(8))
        close = tk.Label(bar, text="✕", bg=T["bar"], fg=T["dim"], font=(T["font"], 10), cursor="hand2",
                         padx=self.px(8))
        close.pack(side="right")
        close.bind("<Button-1>", lambda e: self.hide(by_user=True))
        close.bind("<Enter>", lambda e: close.config(fg=T["danger"]))
        close.bind("<Leave>", lambda e: close.config(fg=T["dim"]))
        front = tk.Label(bar, text=cap("Bring forward"), bg=T["bar"], fg=T["accent"], font=(T["font"], 8),
                         cursor="hand2", padx=self.px(6))
        front.pack(side="right")
        front.bind("<Button-1>", lambda e: self.bring_forward())
        front.bind("<Enter>", lambda e: front.config(fg=T["fg"]))
        front.bind("<Leave>", lambda e: front.config(fg=T["accent"]))
        for w in (bar, self.label, self.title, dot):
            w.bind("<Button-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
        tk.Frame(body, bg=T["border"], height=1).pack(fill="x")

        self.view = tk.Frame(body, bg=T["bg"])
        self.view.pack(fill="both", expand=True)
        self.placeholder = tk.Label(self.view, text=cap("Waiting for the AI") + " …", bg=T["bg"], fg=T["dim"],
                                    font=(T["font"], 8))
        self.placeholder.place(relx=0.5, rely=0.5, anchor="center")
        self.view.bind("<Double-Button-1>", lambda e: self.bring_forward())

        tk.Frame(body, bg=T["border"], height=1).pack(fill="x")
        foot = tk.Frame(body, bg=T["bg"])
        foot.pack(fill="x")
        self.status = tk.Label(foot, text="", bg=T["bg"], fg=T["fg"], font=(T["mono"], 8), anchor="w",
                               justify="left")
        self.status.pack(side="left", fill="x", expand=True, padx=self.px(8), pady=self.px(5))
        grip = tk.Canvas(foot, width=self.px(14), height=self.px(14), bg=T["bg"], highlightthickness=0,
                         cursor="size_nw_se")
        grip.pack(side="right", anchor="se")
        g = self.px(14)
        if T["brackets"]:  # HUD corner bracket doubles as the resize grip
            grip.create_line(g - 1, 0, g - 1, g - 1, 0, g - 1, fill=T["accent"], width=2)
        else:
            for i in (4, 8, 12):
                grip.create_line(g, g - self.px(i), g - self.px(i), g, fill=T["dim"])
        grip.bind("<Button-1>", self._drag_start)
        grip.bind("<B1-Motion>", self._resize_move)
        if T["brackets"]:  # top-left corner bracket, like the Jarvis HUD panels
            tl = tk.Canvas(root, width=g, height=g, bg=T["bar"], highlightthickness=0)
            tl.place(x=0, y=0)
            tl.create_line(1, g - 1, 1, 1, g - 1, 1, fill=T["accent"], width=2)
            for ev, fn in (("<Button-1>", self._drag_start), ("<B1-Motion>", self._drag_move)):
                tl.bind(ev, fn)

        # The DWM live view paints above everything inside our window, so the AI's cursor gets its own
        # tiny click-through window on top of the viewer.
        d = self.px(26)
        self.cur = tk.Toplevel(root, bg="#010101")
        self.cur.withdraw()
        self.cur.overrideredirect(True)
        self.cur.attributes("-transparentcolor", "#010101")
        cv = tk.Canvas(self.cur, width=d, height=d, bg="#010101", highlightthickness=0)
        cv.pack()
        c, r1, r2 = d / 2, d / 2 - 2, d / 2 - 5
        cv.create_oval(c - r1, c - r1, c + r1, c + r1, outline="#000000", width=self.px(4))
        cv.create_oval(c - r1, c - r1, c + r1, c + r1, outline=T["cursor"], width=self.px(2))
        cv.create_oval(c - 2, c - 2, c + 2, c + 2, fill=T["cursor"], outline="")
        self.cur_size, self.cursor = d, None

        g = activity.prefs().get("geometry")
        if not g:
            w, h = self.px(460), self.px(330)
            g = f"{w}x{h}+{root.winfo_screenwidth() - w - self.px(24)}+{root.winfo_screenheight() - h - self.px(72)}"
        root.geometry(g)
        root.update_idletasks()
        self.hwnd = user32.GetAncestor(root.winfo_id(), 2) or root.winfo_id()  # GA_ROOT
        ex = user32.GetWindowLongPtrW(self.hwnd, GWL_EXSTYLE)
        user32.SetWindowLongPtrW(self.hwnd, GWL_EXSTYLE, ex | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST)
        (activity.DIR / "viewer.hwnd").write_text(str(self.hwnd))
        self.cur.update_idletasks()
        self.cur_hwnd = user32.GetAncestor(self.cur.winfo_id(), 2) or self.cur.winfo_id()
        ex = user32.GetWindowLongPtrW(self.cur_hwnd, GWL_EXSTYLE)  # + WS_EX_TRANSPARENT: clicks pass through
        user32.SetWindowLongPtrW(self.cur_hwnd, GWL_EXSTYLE,
                                 ex | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST | 0x20)
        self.thumb_rect = None

        self.thumb = ctypes.c_void_p()
        self.src = 0
        self.visible = False
        self.mtime = 0.0
        self.last_seen = 0.0
        self.base_status = ""
        if not activity.prefs().get("viewer_hidden"):
            self.show()
        root.after(150, self._tick)

    # ---------- show / hide ----------
    def show(self):
        user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
        user32.SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        self.visible = True
        self._place_thumb()
        self._keep_user_focus()

    def _keep_user_focus(self):
        """The viewer must never hold focus: Windows hands a new process's first window the foreground
        regardless of WS_EX_NOACTIVATE, so give it straight back to the window the user was in."""
        fg = user32.GetForegroundWindow()
        if fg and fg != self.hwnd:
            self.user_fg = fg
        elif fg == self.hwnd and self.user_fg and user32.IsWindow(self.user_fg):
            from .launch import _force_foreground
            _force_foreground(self.user_fg)

    def hide(self, by_user: bool = False):
        user32.ShowWindow(self.hwnd, SW_HIDE)
        user32.ShowWindow(self.cur_hwnd, SW_HIDE)
        self.visible = False
        if by_user:
            activity.save_prefs(viewer_hidden=True)

    def bring_forward(self):
        """The user clicked "Bring forward" (or double-clicked the view): put the AI's window in front."""
        if self.src and user32.IsWindow(self.src):
            from .launch import _force_foreground
            _force_foreground(self.src)
            self.user_fg = self.src  # the user chose it: don't hand focus back to the old window
            self.status.config(text="brought forward at your request")

    # ---------- move / resize ----------
    def _drag_start(self, e):
        self._dx, self._dy = e.x_root, e.y_root
        self._geo = (self.root.winfo_x(), self.root.winfo_y(), self.root.winfo_width(), self.root.winfo_height())

    def _drag_move(self, e):
        x, y, w, h = self._geo
        self.root.geometry(f"+{x + e.x_root - self._dx}+{y + e.y_root - self._dy}")
        self.root.update_idletasks()
        self._place_cursor()
        self._save_geometry()

    def _resize_move(self, e):
        x, y, w, h = self._geo
        w = max(self.px(240), w + e.x_root - self._dx)
        h = max(self.px(160), h + e.y_root - self._dy)
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.update_idletasks()
        self._place_thumb()
        self._save_geometry()

    def _save_geometry(self):
        self._pending_geo = self.root.geometry()

    # ---------- live thumbnail ----------
    def _set_source(self, hwnd: int):
        if self.thumb:
            dwmapi.DwmUnregisterThumbnail(self.thumb)
            self.thumb = ctypes.c_void_p()
        self.src = hwnd
        if hwnd and user32.IsWindow(hwnd):
            if dwmapi.DwmRegisterThumbnail(self.hwnd, hwnd, ctypes.byref(self.thumb)) != 0:
                self.thumb = ctypes.c_void_p()
        self._place_thumb()

    def _place_thumb(self):
        if not self.thumb:
            self.placeholder.place(relx=0.5, rely=0.5, anchor="center")
            self.thumb_rect = None
            self._place_cursor()  # no live picture -> no cursor anywhere
            return
        self.root.update_idletasks()
        # thumbnail coordinates are relative to the top-level window, not the view's parent frame
        vx, vy = self.view.winfo_rootx() - self.root.winfo_rootx(), self.view.winfo_rooty() - self.root.winfo_rooty()
        vw, vh = self.view.winfo_width(), self.view.winfo_height()
        size = W.SIZE()
        dwmapi.DwmQueryThumbnailSourceSize(self.thumb, ctypes.byref(size))
        if size.cx <= 0 or size.cy <= 0 or vw <= 1 or vh <= 1:
            return
        s = min(vw / size.cx, vh / size.cy)
        w, h = int(size.cx * s), int(size.cy * s)
        x, y = vx + (vw - w) // 2, vy + (vh - h) // 2
        p = _ThumbProps(0x1 | 0x4 | 0x8 | 0x10, W.RECT(x, y, x + w, y + h), W.RECT(), 255, True, False)
        dwmapi.DwmUpdateThumbnailProperties(self.thumb, ctypes.byref(p))
        self.placeholder.place_forget()
        self.thumb_rect = (x, y, w, h, s, size.cx, size.cy)
        self._place_cursor()

    def _place_cursor(self):
        """Put the AI-cursor marker over the live view, where the AI's cursor is in the real window.

        The marker is its own little window, so it must NEVER be left anywhere else on the user's
        screen: it is hidden unless every check passes and the point lands inside the live picture.
        """
        pos = self._cursor_pos()
        if pos is None:
            if user32.IsWindowVisible(self.cur_hwnd):
                user32.ShowWindow(self.cur_hwnd, SW_HIDE)
            return
        user32.SetWindowPos(self.cur_hwnd, HWND_TOPMOST, pos[0], pos[1], 0, 0,
                            SWP_NOSIZE | SWP_NOACTIVATE | 0x40)  # SWP_SHOWWINDOW

    def _cursor_pos(self):
        if not (self.visible and self.cursor and self.thumb_rect and self.src):
            return None
        if not user32.IsWindow(self.src) or user32.IsIconic(self.src):
            return None
        x, y, w, h, s, src_w, src_h = self.thumb_rect
        size = W.SIZE()
        if dwmapi.DwmQueryThumbnailSourceSize(self.thumb, ctypes.byref(size)) != 0:
            return None
        if (size.cx, size.cy) != (src_w, src_h):  # the window was resized: re-fit first
            self._place_thumb()
            return None
        outer, vis = core._frame_rect(self.src)  # the thumbnail includes the invisible resize border
        cx = x + (self.cursor[0] + vis.left - outer.left) * s
        cy = y + (self.cursor[1] + vis.top - outer.top) * s
        if not (x <= cx <= x + w and y <= cy <= y + h):
            return None  # outside the live picture
        return (self.root.winfo_rootx() + round(cx) - self.cur_size // 2,
                self.root.winfo_rooty() + round(cy) - self.cur_size // 2)

    # ---------- polling ----------
    def _tick(self):
        try:
            self._keep_user_focus()
            self._poll()
            self._place_cursor()  # every tick: follows the window, and hides the moment it's invalid
        except Exception:
            pass
        self.root.after(200, self._tick)

    def _poll(self):
        if self.toggle_requested.is_set():
            self.toggle_requested.clear()
            if self.visible:
                self.hide(by_user=True)
            else:
                activity.save_prefs(viewer_hidden=False)
                self.show()
        if getattr(self, "_pending_geo", None):
            activity.save_prefs(geometry=self._pending_geo)
            self._pending_geo = None
        if activity.prefs().get("quit"):
            activity.save_prefs(quit=False)
            self.root.destroy()
            return
        try:
            m = activity.STATE.stat().st_mtime
        except OSError:
            return
        if self.src and not user32.IsWindow(self.src):
            self._set_source(0)
            self.cursor = None
            self.status.config(text="the window was closed")
        if m == self.mtime:
            idle = time.time() - self.last_seen
            if self.last_seen and idle > 30:
                self.label.config(fg=self.T["dim"])  # idle: the accent fades
            if self.visible and self.thumb:
                note = "   · minimized, showing its last frame" if user32.IsIconic(self.src) else ""
                self.status.config(text=self.base_status + note)
            return
        self.mtime = m
        data = json.loads(activity.STATE.read_text(encoding="utf-8"))
        cur = data.get("current") or {}
        self.last_seen = cur.get("t", time.time())
        self.cursor = cur.get("cursor")
        if cur.get("hwnd") != self.src:
            self._set_source(cur.get("hwnd") or 0)
        else:
            self._place_cursor()
        title = cur.get("title", "")
        self.title.config(text=title[:44])
        self.label.config(fg=self.T["accent"])
        lines = [f"▸ {r['action']} {r.get('detail', '')}".strip() for r in data.get("recent", [])[-2:]]
        how = f"   ({cur['method']})" if cur.get("method") else ""
        self.base_status = "\n".join(lines) + how
        self.status.config(text=self.base_status)
        if not self.visible and not activity.prefs().get("viewer_hidden"):
            self.show()

    def _hotkey_loop(self):
        mods, vk = _parse_hotkey(self.hotkey)
        if not vk or not user32.RegisterHotKey(None, 1, mods, vk):
            return  # taken by another app: the viewer still works, just without the hotkey
        self.hotkey_ok.set()
        msg = W.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                self.toggle_requested.set()

    def run(self):
        self.root.mainloop()


def main(argv=None):
    mutex = kernel32.CreateMutexW(None, True, activity.MUTEX)
    if ctypes.GetLastError() == 183:  # ERROR_ALREADY_EXISTS: one viewer serves every agent
        return 0
    Viewer().run()
    kernel32.CloseHandle(mutex)
    return 0


if __name__ == "__main__":
    sys.exit(main())
