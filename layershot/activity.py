"""What the AI is doing, for the floating viewer.

Every layershot action writes the current target window and a one-line description to
%LOCALAPPDATA%\\layershot\\activity.json. The viewer (a separate, single-instance process,
so several agents share one) polls it. The first action starts the viewer if it isn't
running, unless the user turned it off (LAYERSHOT_VIEWER=0 or `layershot viewer --off`).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "layershot"
STATE = DIR / "activity.json"
PREFS = DIR / "prefs.json"
MUTEX = "Local\\layershot-viewer"

_recent: list[dict] = []
_checked_viewer = 0.0


def prefs() -> dict:
    try:
        return json.loads(PREFS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_prefs(**kw):
    p = prefs() | kw
    DIR.mkdir(parents=True, exist_ok=True)
    PREFS.write_text(json.dumps(p, indent=2), encoding="utf-8")


def log(win, action: str, detail: str = "", method: str = "", cursor: tuple[int, int] | None = None):
    """Record one action; never raises (the viewer is a nice-to-have).

    cursor: the AI's cursor in the window, full-size pixels from its visible top-left.
    """
    try:
        entry = {"t": time.time(), "hwnd": win.hwnd, "title": win.title, "process": win.process,
                 "action": action, "detail": detail, "method": method, "agent_pid": os.getppid(),
                 "cursor": list(cursor) if cursor else None}
        _recent.append(entry)
        del _recent[:-6]
        DIR.mkdir(parents=True, exist_ok=True)
        tmp = STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"current": entry, "recent": _recent}), encoding="utf-8")
        os.replace(tmp, STATE)
        ensure_viewer()
    except Exception:
        pass


def viewer_running() -> bool:
    import ctypes
    k = ctypes.windll.kernel32
    k.OpenMutexW.restype = ctypes.c_void_p
    h = k.OpenMutexW(0x00100000, False, MUTEX)  # SYNCHRONIZE
    if h:
        k.CloseHandle(ctypes.c_void_p(h))
        return True
    return False


def ensure_viewer():
    global _checked_viewer
    if os.environ.get("LAYERSHOT_VIEWER", "1") == "0" or prefs().get("viewer") == "off":
        return
    if time.monotonic() - _checked_viewer < 5:
        return
    _checked_viewer = time.monotonic()
    if not viewer_running():
        start_viewer()


def start_viewer():
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    cmd = [str(pyw if pyw.exists() else exe), "-m", "layershot.viewer"]
    DETACHED, NEW_GROUP, BREAKAWAY, NO_WINDOW = 0x8, 0x200, 0x01000000, 0x08000000
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 4  # SW_SHOWNOACTIVATE for the first window the viewer shows
    for flags in (DETACHED | NEW_GROUP | BREAKAWAY, DETACHED | NEW_GROUP):  # outlive the agent if allowed
        try:
            subprocess.Popen(cmd, creationflags=flags | NO_WINDOW, close_fds=True, startupinfo=si,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError:
            continue
