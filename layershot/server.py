"""MCP server: lets any agent screenshot background windows without stealing focus."""
from __future__ import annotations

import io

try:  # mcp >= 2
    from mcp.server.mcpserver import Image, MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server, Image

from . import activity, actions, core, theme
from .rules import RULES

# Clients that support server instructions (Claude Code, Claude Desktop, ...) put these in the model's
# system prompt, so an agent follows the background-first rule with no setup on the user's side.
mcp = _Server("layershot", instructions=RULES + "\nLayers: list_windows shows windows front to back; layer 0 "
              "is the window the user is working in.")


def _encode(img, max_width: int, fmt: str, hwnd: int | None = None) -> Image:
    full_w = img.width
    if max_width and img.width > max_width:
        img = img.resize((max_width, round(img.height * max_width / img.width)))
    if hwnd is not None:
        actions.scales[hwnd] = img.width / full_w  # so click(x, y) can use this image's pixels
        if (c := actions.cursor_in_image(hwnd)) is not None:
            img = img.convert("RGB")
            _draw_cursor(img, *c)
    buf = io.BytesIO()
    if fmt == "jpeg":
        img.save(buf, "JPEG", quality=85)
    else:
        img.save(buf, "PNG", optimize=True)
    return Image(data=buf.getvalue(), format=fmt)


def _draw_cursor(img, x: int, y: int):
    """The AI's own cursor (the theme's cursor image), drawn only on the AI's copy of the screenshot."""
    cur, (hx, hy) = theme.cursor(height=32)
    img.paste(cur, (x - hx, y - hy), cur)


def _win(layer, title, process, hwnd) -> dict:
    return {"layer": layer, "title": title, "process": process, "hwnd": hwnd}


@mcp.tool()
def list_windows(include_minimized: bool = True) -> list[dict]:
    """List app windows front to back. `layer` 0 is the window the user is using now."""
    return [w.to_dict() for w in core.list_windows(include_minimized)]


@mcp.tool()
def screenshot_window(
    layer: int | None = None,
    title: str | None = None,
    process: str | None = None,
    hwnd: int | None = None,
    keep_open: bool = False,
    max_width: int = 1600,
    format: str = "png",
    save_to: str | None = None,
) -> list:
    """Screenshot one window without focusing it or disturbing the user.

    Pick the window by `layer` (from list_windows), a `title` substring, a `process`
    name (e.g. "obsidian.exe") or a raw `hwnd`. Minimized windows are restored at the
    back of the stack and minimized again afterwards unless keep_open is true.
    max_width downsizes large windows (0 = full size); format is "png" or "jpeg".
    save_to also writes the full-size image to that path.
    If you've clicked in this window, YOUR cursor is drawn on it (an arrow with a coloured glow; its tip is the point). The real
    mouse never appears in these captures.
    x/y you pass to click/scroll are pixels of the image this returns.
    """
    img, win = core.capture(layer=layer, title=title, process=process, hwnd=hwnd,
                            keep_open=keep_open)
    if save_to:
        img.save(save_to)
    out = _encode(img, max_width, "jpeg" if format.lower() in ("jpg", "jpeg") else "png", win.hwnd)
    activity.log(win, "look", cursor=actions.cursors.get(win.hwnd))
    s = actions.scales.get(win.hwnd, 1.0)
    note = (f"{win.title} ({win.process}), layer {win.layer}, image {round(img.width * s)}x{round(img.height * s)}"
            + (", was minimized" if win.minimized else ""))
    if (c := actions.cursor_in_image(win.hwnd)) is not None:
        note += f", your cursor at {c[0]},{c[1]}"
    return [note, out]


@mcp.tool()
def find_elements(layer: int | None = None, title: str | None = None, process: str | None = None,
                  hwnd: int | None = None, query: str | None = None, limit: int = 150) -> dict:
    """List a window's buttons, fields, tabs, menu items, etc. (UI Automation) without touching it.
    Each has an `id` to pass to click/type_text, a `rect` in the same pixels as your last
    screenshot of the window, and the `actions` it supports. query filters by name or type."""
    return actions.find_elements(**_win(layer, title, process, hwnd), query=query, limit=limit)


@mcp.tool()
def click(layer: int | None = None, title: str | None = None, process: str | None = None,
          hwnd: int | None = None, element: str | None = None, x: float | None = None,
          y: float | None = None, button: str = "left", double: bool = False) -> dict:
    """Click in a window WITHOUT bringing it forward or moving the user's mouse.
    Prefer `element` (an id from find_elements): it's pressed through accessibility. Otherwise
    give x, y in pixels of your last screenshot_window image; the click goes to that spot as
    window messages, from your own invisible cursor. Any dialog or popup it opens is kept behind
    the user's app. Take a screenshot afterwards to check: some apps ignore background clicks."""
    return actions.click(**_win(layer, title, process, hwnd), element=element, x=x, y=y,
                         button=button, double=double)


@mcp.tool()
def type_text(text: str, layer: int | None = None, title: str | None = None, process: str | None = None,
              hwnd: int | None = None, element: str | None = None, append: bool = False,
              enter: bool = False) -> dict:
    """Type into a window in the background. With `element` (from find_elements) the field's value is
    set directly (append=True keeps the existing text); without it the characters go to whatever
    control has focus inside that window. enter=True presses Enter afterwards."""
    return actions.type_text(**_win(layer, title, process, hwnd), text=text, element=element,
                             append=append, enter=enter)


@mcp.tool()
def press_key(key: str, layer: int | None = None, title: str | None = None, process: str | None = None,
              hwnd: int | None = None, element: str | None = None) -> dict:
    """Press one key in a background window: enter, tab, esc, backspace, delete, space, arrows,
    home/end, pageup/pagedown, f1-f12, or a single character. Shortcuts with Ctrl/Alt don't
    work in the background (Windows reads modifier state from the real keyboard): use flash."""
    return actions.press_key(**_win(layer, title, process, hwnd), key=key, element=element)


@mcp.tool()
def scroll(layer: int | None = None, title: str | None = None, process: str | None = None,
           hwnd: int | None = None, x: float | None = None, y: float | None = None, amount: int = -3) -> dict:
    """Scroll a background window at x, y (screenshot pixels; default = centre). amount in notches,
    negative = down."""
    return actions.scroll(**_win(layer, title, process, hwnd), x=x, y=y, amount=amount)


@mcp.tool()
def flash(steps: list[dict], layer: int | None = None, title: str | None = None, process: str | None = None,
          hwnd: int | None = None) -> dict:
    """For apps that IGNORE background input (custom-drawn buttons, sliders, right-click menus, Ctrl
    shortcuts): brings the window to the front for a moment, runs the steps as real mouse/keyboard
    input, then gives focus and the mouse back to the user. Try click/press_key first; use this when
    a screenshot shows the background action did nothing. Keep each flash short.
    steps, in order: {"click": [x, y]} (screenshot px; "button": "right", "double": true),
    {"key": "ctrl+r"} or {"key": "down", "repeat": 22}, {"type": "text"}, {"wait": 0.5},
    {"shot": "C:/path.png"} (captures the window's screen area incl. open menus).
    Menus close when focus returns, so open and pick from a menu in the same flash."""
    from .flash import flash as run
    return run(**_win(layer, title, process, hwnd), steps=steps)


@mcp.tool()
def open_app(target: str, args: str | None = None, cwd: str | None = None, front: bool = False,
             wait: float = 8.0) -> dict:
    """Open an app, file, folder or URL. By default it opens IN THE BACKGROUND: the new window goes
    behind the user's windows and focus never leaves what the user is doing.

    Set front=True ONLY when the user explicitly asked to open/show it for themselves. When you
    (the agent) just need the app for your own work, leave front=False and use
    screenshot_window to look at it.
    target: exe name or path ("notepad.exe", "C:/Program Files/.../app.exe"), a file or folder
    path (opens with its default app), or a URL. args: command-line arguments.
    """
    from . import launch
    r = launch.open_app(target, args, cwd, front=front, wait=wait)
    if r["windows"]:
        activity.log(core.find_window(hwnd=r["windows"][0]["hwnd"]), "open", target,
                     "front" if front else "background")
    return r


@mcp.tool()
def bring_to_front(layer: int | None = None, title: str | None = None, process: str | None = None,
                   hwnd: int | None = None) -> dict:
    """Restore and focus a window. ONLY use this when the user asked to see or switch to the window;
    to look at a window yourself, use screenshot_window instead."""
    from . import launch
    return launch.bring_to_front(layer=layer, title=title, process=process, hwnd=hwnd).to_dict()


def main():
    mcp.run()


if __name__ == "__main__":
    main()
