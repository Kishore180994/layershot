# Changelog

## 0.3.3 - 2026-10-21

- **Fix:** the live view could overlap the footer. The footer is laid out first at a fixed two-line height,
  and the live picture re-fits whenever the view area changes size.

## 0.3.2 - 2026-10-21

- **AI cursor redesign:** a normal arrow with a blue highlight (`hud` theme: cyan), drawn with real
  per-pixel alpha (UpdateLayeredWindow) in the AI view and on the agent's screenshots. Themes can
  use any PNG (`cursor_image`, `cursor_hotspot`, `cursor_height`).
- Themes moved to `layershot/theme.py` (shared by the viewer and the server).
- **Fix:** a `--quit` aimed at a viewer that wasn't running stayed in prefs and closed the next
  viewer at startup. The viewer now clears it on start, and the CLI only sets it when a viewer is running.

## 0.3.1 - 2026-10-21

- **Fix:** the AI-cursor marker could be left on the user's desktop after the AI's window closed. It's
  now re-checked every tick and hidden unless it falls inside the live view.
- **Fix:** guards check focus every 10 ms (was 50 ms). In an end-to-end run with a fresh agent (3 min, 2
  apps, about 60 actions), focus was away from the user in 21 of 17,620 samples, in bursts of at most
  ~70 ms. Faster checks cut that further: the follow-up run had 0.
- **Viewer themes:** `default` and `hud` (cyan HUD look), plus per-key overrides in prefs.

## 0.3.0 - 2026-10-21

- **Background input:** `find_elements`, `click` (by element or x,y), `type_text`, `press_key`, `scroll`
  (MCP tools and CLI). UI Automation first, posted window messages second. The real mouse and keyboard
  are never used.
- **Dialogs and popups stay behind the user's app.** Each action holds the foreground lock, flushes the
  app's message queue while watching, and puts new windows directly behind the user's window.
- **AI cursor:** a per-window virtual cursor, drawn on the agent's screenshots and in the AI view only.
- **AI view:** a floating, movable, closable live view of the agent's current window (DWM thumbnail),
  with the AI cursor and recent actions. Ctrl+Alt+L shows/hides it, and **Bring forward** / double-click puts
  the AI's window in front. It never takes focus.
- New dependency: `comtypes` (UI Automation).
- Measured: Notepad typing, Enter and accessibility presses in the background; 3 x,y clicks in Character
  Map with 0 focus samples lost. Known limit: WinUI apps ignore posted mouse clicks and inactive-window
  flyout menus.

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
