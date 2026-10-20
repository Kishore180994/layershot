# Changelog

## Unreleased

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
