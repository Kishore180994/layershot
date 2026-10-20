"""The agent rule layershot exists to enforce, in one place.

It ships three ways: as the MCP server's `instructions` (clients like Claude Code show it to the
model automatically), in the tool descriptions, and as a marked block that `layershot setup`
writes into agents' instruction files (CLAUDE.md, AGENTS.md) for sessions without the MCP tools.
"""

RULES = """\
# App windows: work in the background, never take over the screen (layershot)

The user keeps working while you run. Use layershot to look at and open apps.

- Looking: to see any app window, capture it in place with `list_windows` + `screenshot_window`
  (by layer, title, process or hwnd). This works on covered and minimized windows. Never switch to,
  activate, restore or SetForegroundWindow a window, or grab the full screen, just to look at it.
- Opening: when YOU need an app, file or URL open for your own work, use `open_app(target)`. It opens
  behind the user's windows and focus never leaves them. Don't use Start-Process, start, ii or
  explorer for this.
- The user asked: only when the user asks to open, show or switch to something for themselves
  ("open Bambu", "show me the plate"), use `open_app(target, front=True)` or `bring_to_front(...)`.
- Without the MCP tools, use the CLI: `layershot list`, `layershot shot "<title or layer>" -o shot.png`
  (then read the PNG), `layershot open <app> [args]` (background), `layershot open --front <app>`,
  `layershot front "<title>"`.
- A full-screen screenshot is OK only when the user asks what is on their screen.
"""

BEGIN = "<!-- layershot:begin (managed by `layershot setup`; edit there or remove with `layershot setup --remove`) -->"
END = "<!-- layershot:end -->"


def block() -> str:
    return f"{BEGIN}\n{RULES}{END}\n"
