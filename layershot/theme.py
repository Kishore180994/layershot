"""Viewer themes and the AI cursor's look (shared by the viewer and the screenshot marker).

Pick a theme with `layershot viewer --theme hud` (prefs "theme") or LAYERSHOT_THEME. A dict in
prefs "theme" overrides single keys, e.g.
    {"base": "hud", "accent": "#ff9900",
     "cursor_image": "C:/path/my_cursor.png", "cursor_hotspot": [6, 4], "cursor_height": 32}
`cursor_image` is any RGBA PNG; `cursor_hotspot` is the pixel in that PNG that marks the point.
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFilter

from . import activity

THEMES = {
    "default": dict(bg="#101418", bar="#1b2128", border="#30363d", fg="#e6edf3", dim="#8b949e",
                    accent="#58a6ff", danger="#ff7b72", cursor="#3b82f6", font="Segoe UI", mono="Consolas",
                    caps=False, brackets=False),
    # cyan HUD: navy glass panels, cyan hairline border, corner brackets, spaced caps headers
    "hud": dict(bg="#030e1a", bar="#082a3a", border="#10556a", fg="#d7f6ff", dim="#6fb4c9",
                accent="#2ad8ff", danger="#ff4d5e", cursor="#2ad8ff", font="Bahnschrift",
                mono="Cascadia Mono", caps=True, brackets=True),
}


def current() -> dict:
    p = os.environ.get("LAYERSHOT_THEME") or activity.prefs().get("theme") or "default"
    if isinstance(p, dict):
        return THEMES.get(p.get("base", "default"), THEMES["default"]) | {k: v for k, v in p.items() if k != "base"}
    return THEMES.get(p, THEMES["default"])


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _arrow_with_glow(glow_hex: str) -> tuple[Image.Image, tuple[int, int]]:
    """A normal Windows-style arrow (white, black outline) with a coloured highlight around it.
    Drawn at 64 px; the caller scales it."""
    size, pad = 64, 10
    shape = [(0, 0), (0, 34), (8, 27), (14, 41), (20, 38.5), (14.5, 25), (25, 25)]
    pts = [(x + pad, y + pad) for x, y in shape]
    arrow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(arrow)
    d.polygon(pts, fill=(255, 255, 255, 255), outline=(0, 0, 0, 255), width=2)
    alpha = arrow.split()[3]
    glow = Image.new("RGBA", (size, size), _rgb(glow_hex) + (0,))
    halo = alpha.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(4))
    glow.putalpha(halo.point(lambda v: min(255, int(v * 0.95))))
    glow.alpha_composite(arrow)
    return glow, (pad, pad)


def cursor(theme: dict | None = None, height: int = 32) -> tuple[Image.Image, tuple[int, int]]:
    """The AI cursor for a theme as (RGBA image, hotspot), scaled so the image is `height` px tall."""
    t = theme or current()
    img, hot = None, (0, 0)
    path = t.get("cursor_image")
    if path:
        try:
            img = Image.open(path).convert("RGBA")
            hot = tuple(t.get("cursor_hotspot", (0, 0)))
        except OSError:
            img = None
    if img is None:
        img, hot = _arrow_with_glow(t.get("cursor", "#3b82f6"))
    h = int(t.get("cursor_height", height)) if path else height
    s = h / img.height
    if s != 1:
        img = img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))), Image.LANCZOS)
        hot = (round(hot[0] * s), round(hot[1] * s))
    return img, hot
