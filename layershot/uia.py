"""UI Automation: find a window's controls and act on them without the mouse or focus."""
from __future__ import annotations

import threading

import comtypes
import comtypes.client as cc

cc.GetModule("UIAutomationCore.dll")
from comtypes.gen import UIAutomationClient as U  # noqa: E402

_local = threading.local()
_cache: dict[int, dict[str, object]] = {}  # hwnd -> element id -> IUIAutomationElement

# control types worth showing an agent (unnamed panes/groups are mostly layout noise)
ACTIONABLE = {
    50000: "button", 50002: "checkbox", 50003: "combobox", 50004: "edit", 50005: "hyperlink",
    50007: "listitem", 50011: "menuitem", 50013: "radiobutton", 50015: "slider", 50016: "spinner",
    50018: "tab", 50019: "tabitem", 50024: "treeitem", 50031: "splitbutton", 50010: "menubar",
}
NAMED_ONLY = {50020: "text", 50033: "pane", 50026: "group", 50025: "custom", 50006: "image",
              50008: "list", 50021: "toolbar", 50028: "datagrid", 50029: "dataitem", 50030: "document"}

P_INVOKE, P_VALUE, P_EXPAND, P_SELITEM, P_TOGGLE, P_LEGACY = 10000, 10002, 10005, 10010, 10015, 10018
_PATTERNS = {P_INVOKE: ("invoke", U.IUIAutomationInvokePattern),
             P_TOGGLE: ("toggle", U.IUIAutomationTogglePattern),
             P_SELITEM: ("select", U.IUIAutomationSelectionItemPattern),
             P_EXPAND: ("expand", U.IUIAutomationExpandCollapsePattern),
             P_VALUE: ("value", U.IUIAutomationValuePattern),
             P_LEGACY: ("default_action", U.IUIAutomationLegacyIAccessiblePattern)}


def _uia():
    a = getattr(_local, "uia", None)
    if a is None:
        try:  # MCP tools run on worker threads: each needs COM initialized
            comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        except OSError:
            pass
        a = _local.uia = cc.CreateObject(U.CUIAutomation, interface=U.IUIAutomation)
    return a


def _pattern(el, pid):
    try:
        unk = el.GetCurrentPattern(pid)
    except comtypes.COMError:
        return None
    if not unk:
        return None
    return unk.QueryInterface(_PATTERNS[pid][1])


def elements(hwnd: int, origin: tuple[int, int], query: str | None = None, limit: int = 150) -> list[dict]:
    """Controls in a window, front-loaded with the actionable ones. Rects are relative to `origin`
    (the window's visible top-left, i.e. screenshot pixel 0,0 at full size)."""
    a = _uia()
    root = a.ElementFromHandle(hwnd)
    found = root.FindAll(4, a.ControlViewCondition)  # TreeScope_Descendants
    q = (query or "").lower()
    rows, cache = [], {}
    for i in range(found.Length):
        el = found.GetElement(i)
        try:
            ct, name = el.CurrentControlType, (el.CurrentName or "").strip()
            if not el.CurrentIsEnabled or el.CurrentIsOffscreen:
                continue
        except comtypes.COMError:
            continue
        kind = ACTIONABLE.get(ct) or (NAMED_ONLY.get(ct) if name else None)
        if not kind:
            continue
        if q and q not in name.lower() and q not in kind:
            continue
        r = el.CurrentBoundingRectangle
        if r.right - r.left <= 0 or r.bottom - r.top <= 0:
            continue
        eid = f"e{len(cache)}"
        cache[eid] = el
        acts = [label for pid, (label, _) in _PATTERNS.items() if _has(el, pid)]
        rows.append({"id": eid, "type": kind, "name": name[:80],
                     "rect": [r.left - origin[0], r.top - origin[1], r.right - origin[0], r.bottom - origin[1]],
                     "actions": acts})
        if len(rows) >= limit:
            break
    _cache[hwnd] = cache
    return rows


def _has(el, pid) -> bool:
    prop = {P_INVOKE: 30031, P_VALUE: 30043, P_EXPAND: 30028, P_SELITEM: 30036,
            P_TOGGLE: 30041, P_LEGACY: 30090}[pid]  # Is<Pattern>PatternAvailable properties
    try:
        return bool(el.GetCurrentPropertyValue(prop))
    except comtypes.COMError:
        return False


def get(hwnd: int, eid: str):
    el = _cache.get(hwnd, {}).get(eid)
    if el is None:
        raise LookupError(f"unknown element {eid!r}: call find_elements for this window first")
    return el


def rect(el) -> tuple[int, int, int, int]:
    r = el.CurrentBoundingRectangle
    return r.left, r.top, r.right, r.bottom


def native_hwnd(el) -> int:
    try:
        return int(el.CurrentNativeWindowHandle or 0)
    except comtypes.COMError:
        return 0


def activate(el) -> str | None:
    """Press an element the accessible way. Returns the method used, or None if it has none."""
    for pid in (P_INVOKE, P_TOGGLE, P_SELITEM, P_EXPAND, P_LEGACY):
        p = _pattern(el, pid)
        if p is None:
            continue
        try:
            if pid == P_INVOKE:
                p.Invoke()
            elif pid == P_TOGGLE:
                p.Toggle()
            elif pid == P_SELITEM:
                p.Select()
            elif pid == P_EXPAND:
                (p.Collapse if p.CurrentExpandCollapseState == 1 else p.Expand)()
            else:
                p.DoDefaultAction()
            return _PATTERNS[pid][0]
        except comtypes.COMError:
            continue
    return None


def set_value(el, text: str, append: bool = False) -> bool:
    p = _pattern(el, P_VALUE)
    if p is None:
        return False
    try:
        if p.CurrentIsReadOnly:
            return False
        p.SetValue((p.CurrentValue or "") + text if append else text)
        return True
    except comtypes.COMError:
        return False
