# Changelog

## 0.2.0 - 2026-10-20

- **`open_app`** (MCP tool, `layershot.open_app`, `layershot open`): open an exe, file, folder or URL
  in the background. New windows go behind the user's windows, and `LockSetForegroundWindow` stops the
  app from grabbing focus on startup (Paint: ~3.5 s of stolen focus became 0). `front=True` opens it
  normally in front, for when the user asked.
- **`bring_to_front`** (MCP tool, `layershot.bring_to_front`, `layershot front`): restore and focus a
  window, for user requests.
- **Agents set themselves up.** The agent rule (look in the background, open in the background, come to the front only
  when the user asks) now ships as MCP server instructions. **`layershot setup`** registers the server
  with Claude Code, Codex, Claude Desktop, Cursor and Hermes, and writes the rule into CLAUDE.md /
  AGENTS.md between markers. It's idempotent, and `--remove` undoes it.
- Verified with a fresh Claude Code session given no hints: asked to check Paint's version, it
  called `open_app` (background) + `screenshot_window` on its own.
- Title/process matching ignores spaces and punctuation, and a title also matches the process
  name, so "Bambu Studio" finds "plate - BambuStudio" (bambu-studio.exe). Found when a real agent's
  first title lookup failed.
- "No window matching" errors now list the open windows, so an agent can retry right away.

## 0.1.0 - 2026-10-20

First release.

- `list_windows()`: app windows in z-order (layer 0 = the one in front), with process name,
  minimized and foreground flags. Filters out cloaked, tool and untitled windows.
- `capture()`: screenshots a window without focusing it.
  - Covered windows: `PrintWindow(PW_RENDERFULLCONTENT)` reads the DWM surface directly.
  - Minimized windows: restored without activation at the bottom of the z-order, captured, then
    minimized again (`keep_open` leaves them restored).
  - Chromium/Electron: forced repaint plus retries until the capture isn't blank.
  - Crops the invisible Windows 10/11 resize border; per-monitor-v2 DPI aware.
- CLI: `layershot list`, `layershot shot`, `layershot serve`.
- MCP server `layershot-mcp` with `list_windows` and `screenshot_window`; works with the
  `mcp` Python SDK 1.x and 2.x.
