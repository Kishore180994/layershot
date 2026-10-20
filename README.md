# layershot

**Screenshot any Windows app window without stealing focus, even when it's covered or minimized.**

AI agents (Claude Code, Codex, Hermes, computer-use tools…) usually look at an app by
switching to it and grabbing the screen. That yanks the window in front of you, and you
can't use your PC until the agent is done. layershot captures the window *where it is*,
in whatever layer of the stack, so you keep working.

```
> layershot list
  0 FG  WindowsTerminal.exe      my terminal              <- you, working
  1     electron.exe             HoloTrade                <- covered
  2 MIN Obsidian.exe             Graph view - vault       <- minimized
> layershot shot 2 -o obsidian.png
saved obsidian.png  1024x768  layer 2  Graph view - vault
```

Your terminal stays in front and keeps keyboard focus the whole time.

## How it works

| Window state | What layershot does |
|---|---|
| Covered by other windows | Reads the window's own DWM surface with `PrintWindow(PW_RENDERFULLCONTENT)`. Nothing moves. |
| Minimized | Restores it **without activating it** and **at the bottom of the z-order** (behind everything), captures it, then minimizes it again. Pass `keep_open` to leave it restored at the back. |
| Chromium / Electron apps (Chrome, VS Code, Obsidian, Discord…) | These stop painting while fully covered, so layershot forces a repaint and retries until the image isn't blank (up to 3 s). |

It's pure `ctypes` + Pillow: no native build and no admin rights.

## Install

```bash
pip install layershot          # or: uvx layershot ...
```

From source:

```bash
git clone <this repo> && cd layershot && pip install -e .
```

## Use it from an AI agent (MCP)

**Claude Code**

```bash
claude mcp add layershot -- layershot-mcp
# or without installing: claude mcp add layershot -- uvx --from layershot layershot-mcp
```

**Claude Desktop / Cursor / any MCP client** (`mcpServers` config):

```json
{
  "mcpServers": {
    "layershot": { "command": "layershot-mcp" }
  }
}
```

**Codex** (`~/.codex/config.toml`):

```toml
[mcp_servers.layershot]
command = "layershot-mcp"
```

Tools:

- `list_windows(include_minimized=True)` returns the windows front to back, each with `layer`, `hwnd`, `title`, `process`, `minimized` and `foreground`.
- `screenshot_window(layer | title | process | hwnd, keep_open=False, max_width=1600, format="png", save_to=None)` returns the image plus a one-line description.

## Use it from Python

```python
import layershot

for w in layershot.list_windows():
    print(w.layer, w.process, w.title)

img, win = layershot.capture(title="Obsidian")      # PIL.Image
img, win = layershot.capture(2)                     # by layer
img, win = layershot.capture(process="code.exe", keep_open=True)
```

## CLI

```
layershot list [--json] [--no-minimized]
layershot shot <layer|title> [--process exe] [--hwnd 0x...] [-o out.png] [--keep-open]
layershot serve            # MCP server on stdio (same as layershot-mcp)
```

## Limits

- **Windows 10 1809+ only.** `PW_RENDERFULLCONTENT` is needed for GPU-drawn apps.
- **Minimized windows:** while one is restored for the capture (about 0.3–1 s), it sits behind your other windows, so it can show through gaps on an uncovered part of the desktop. It never takes focus.
- **Restore size:** a window minimized from *maximized* comes back at its normal size for the capture, because Windows can't maximize a window without activating it.
- **Hardware-protected content** (DRM video, some games running fullscreen) captures black, the same as in any screenshot tool.
- **Other virtual desktops:** those windows are skipped by `list_windows`.
- layershot only *looks*. Clicking and typing into background windows is a separate problem (UI Automation / window messages), planned for a later version.

## License

MIT
