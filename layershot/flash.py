"""Flash: for apps that ignore background input (custom-drawn buttons, sliders, right-click menus).

The target window comes to the front for a moment, the steps run as REAL mouse and keyboard input,
then the user's window, focus and mouse position are put back. One flash usually takes well under
a second plus whatever waits the steps ask for. Popup menus close when focus goes back, so open a
menu and pick from it inside the same flash (a "shot" step shows where the menu items are).

Steps (a list of dicts, run in order):
  {"click": [x, y]}                     left click; x, y in pixels of your last screenshot of the window
  {"click": [x, y], "button": "right"}  right click ("double": true for a double click)
  {"key": "ctrl+r"}                     key or combo: ctrl/alt/shift/win + a key name or character
  {"key": "down", "repeat": 22}
  {"type": "0.2"}                       text, typed as real key presses
  {"wait": 0.5}                         seconds
  {"shot": "C:/path/out.png"}           capture the window's screen area now (menus and popups included)
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as W
import time

from . import activity, core
from .actions import KEYS, _move_cursor, _pid, _target, _to_screen, cursors
from .core import user32
from .launch import _force_foreground

MOD = {"ctrl": 0x11, "control": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B}
KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x2, 0x4
MOUSE = {"left": (0x2, 0x4), "right": (0x8, 0x10)}
user32.VkKeyScanW.restype = ctypes.c_short


def _vk(name: str) -> int:
    n = name.lower()
    if n in KEYS:
        return KEYS[n]
    if len(name) == 1:
        return user32.VkKeyScanW(ord(name)) & 0xFF
    raise ValueError(f"unknown key {name!r}; known: {', '.join(sorted(KEYS))}, a character, or ctrl/alt/shift/win + key")


def _tap(vk: int, up: bool = False):
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP if up else 0, 0)


def _combo(spec: str):
    *mods, key = [p.strip() for p in spec.split("+")] if spec != "+" else ["+"]
    mvk = [MOD[m.lower()] for m in mods]
    for m in mvk:
        _tap(m)
    vk = _vk(key)
    _tap(vk)
    _tap(vk, True)
    for m in reversed(mvk):
        _tap(m, True)


def _type(text: str):
    for ch in text:  # unicode key events: no keyboard-layout or shift guessing
        for flags in (KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP):
            _unicode(ch, flags)
        time.sleep(0.005)


class _KI(ctypes.Structure):
    _fields_ = [("wVk", W.WORD), ("wScan", W.WORD), ("dwFlags", W.DWORD), ("time", W.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", _KI), ("pad", ctypes.c_byte * 32)]
    _anonymous_ = ("u",)
    _fields_ = [("type", W.DWORD), ("u", _U)]


def _unicode(ch: str, flags: int):
    inp = _INPUT(type=1)  # INPUT_KEYBOARD
    inp.ki = _KI(0, ord(ch), flags, 0, 0)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))


def _mouse(sx: int, sy: int, button: str, double: bool):
    down, up = MOUSE[button]
    user32.SetCursorPos(sx, sy)
    time.sleep(0.05)
    for _ in range(2 if double else 1):
        user32.mouse_event(down, 0, 0, 0, 0)
        time.sleep(0.03)
        user32.mouse_event(up, 0, 0, 0, 0)
        time.sleep(0.06)


def _shot(hwnd: int, path: str):
    from PIL import ImageGrab
    _, vis = core._frame_rect(hwnd)
    ImageGrab.grab((vis.left, vis.top, vis.right, vis.bottom), all_screens=True).save(path)


def flash(target=None, steps: list[dict] | None = None, settle: float = 0.25, **find) -> dict:
    win = _target(target, **find)
    h = win.hwnd
    user_fg = user32.GetForegroundWindow()
    if _pid(user_fg) == _pid(h):
        user_fg = 0  # the target already is in front: nothing of the user's to give back
    pt = W.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    done, shots = [], []
    t0 = time.monotonic()
    try:
        if not _force_foreground(h):
            raise RuntimeError(f"could not bring {win.title!r} to the front")
        time.sleep(settle)  # let it repaint and take keyboard focus
        for st in steps or []:
            if "click" in st:
                x, y = st["click"]
                sx, sy = _to_screen(h, x, y)
                _mouse(sx, sy, st.get("button", "left"), bool(st.get("double")))
                _move_cursor(h, sx, sy)
                done.append(f"{st.get('button', 'left')}-click {x},{y}")
            elif "key" in st:
                for _ in range(int(st.get("repeat", 1))):
                    _combo(st["key"])
                    time.sleep(0.02)
                done.append(f"key {st['key']}" + (f" x{st['repeat']}" if st.get("repeat") else ""))
            elif "type" in st:
                _type(st["type"])
                done.append(f"type {st['type'][:40]!r}")
            elif "wait" in st:
                time.sleep(float(st["wait"]))
                done.append(f"wait {st['wait']}")
            elif "shot" in st:
                _shot(h, st["shot"])
                shots.append(st["shot"])
                done.append(f"shot {st['shot']}")
            else:
                raise ValueError(f"unknown step {st!r}")
            time.sleep(0.05)
    finally:
        for m in MOD.values():  # never leave a modifier held down on the user's keyboard
            if user32.GetAsyncKeyState(m) & 0x8000:
                _tap(m, True)
        user32.SetCursorPos(pt.x, pt.y)
        if user_fg and user32.IsWindow(user_fg):
            _force_foreground(user_fg)
    secs = round(time.monotonic() - t0, 2)
    activity.log(win, "flash", "; ".join(done)[:80], f"real input, {secs}s in front", cursor=cursors.get(h))
    return {"window": win.title, "steps": done, "shots": shots, "seconds_in_front": secs,
            "focus_returned_to_user": bool(user_fg)}
