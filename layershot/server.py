"""MCP server: lets any agent screenshot background windows without stealing focus."""
from __future__ import annotations

import io

try:  # mcp >= 2
    from mcp.server.mcpserver import Image, MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server, Image

from . import core

from .rules import RULES

# Clients that support server instructions (Claude Code, Claude Desktop, ...) put these in the model's
# system prompt, so an agent follows the background-first rule with no setup on the user's side.
mcp = _Server("layershot", instructions=RULES + "\nLayers: list_windows shows windows front to back; layer 0 "
              "is the window the user is working in.")


def _encode(img, max_width: int, fmt: str) -> Image:
    if max_width and img.width > max_width:
        img = img.resize((max_width, round(img.height * max_width / img.width)))
    buf = io.BytesIO()
    if fmt == "jpeg":
        img.save(buf, "JPEG", quality=85)
    else:
        img.save(buf, "PNG", optimize=True)
    return Image(data=buf.getvalue(), format=fmt)


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
    """
    img, win = core.capture(layer=layer, title=title, process=process, hwnd=hwnd,
                            keep_open=keep_open)
    if save_to:
        img.save(save_to)
    note = (f"{win.title} ({win.process}), layer {win.layer}, {img.width}x{img.height}"
            + (", was minimized" if win.minimized else ""))
    return [note, _encode(img, max_width, "jpeg" if format.lower() in ("jpg", "jpeg") else "png")]


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
    return launch.open_app(target, args, cwd, front=front, wait=wait)


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
