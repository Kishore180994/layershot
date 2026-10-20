"""MCP server: lets any agent screenshot background windows without stealing focus."""
from __future__ import annotations

import io

try:  # mcp >= 2
    from mcp.server.mcpserver import Image, MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server, Image

from . import core

mcp = _Server(
    "layershot",
    instructions=(
        "Screenshot any app window without switching to it, so the user can keep working. "
        "Call list_windows to see windows by layer (0 = front), then screenshot_window. "
        "Minimized windows are restored behind everything, captured and minimized again. "
        "Never focus or activate a window just to look at it."
    ),
)


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


def main():
    mcp.run()


if __name__ == "__main__":
    main()
