# layershot

**Screenshot any Windows app window without stealing focus, even when it's covered or minimized.
Open apps in the background too.**

AI agents (Claude Code, Codex, Hermes, computer-use tools…) usually look at an app by
switching to it and grabbing the screen. That yanks the window in front of you, and you
can't use your PC until the agent is done. layershot captures the window *where it is*,
in whatever layer of the stack, so you keep working.

```
> layershot list
  0 FG  WindowsTerminal.exe      my terminal              <- you, working
  1     Spotify.exe              Spotify Premium          <- covered
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

**Opening apps works the same way.** When an agent needs an app for its own work, `open_app`
launches it *behind* your windows. Most apps grab focus on startup no matter how they're
launched, so layershot holds Windows' foreground lock (`LockSetForegroundWindow`) for the
launch. Apps can't activate themselves during that time, but your own clicks and Alt+Tab still work. In our tests Paint
went from holding focus for about 3.5 s to never getting it. When *you* ask the agent to open
something, it passes `front=True` and the app opens normally in front.

It's pure `ctypes` + Pillow: no native build and no admin rights.
The full technical notes (the exact Win32 calls, measurements, the Chromium blank-frame
issue, and what can't be captured) are in **[docs/HOW-IT-WORKS.md](docs/HOW-IT-WORKS.md)**.

## Install

Requires Windows 10 1809+ and Python 3.10+.

**The easy way: ask your agent.** Paste this into Claude Code, Codex or any agent with a shell:

> Install layershot from https://github.com/Kishore180994/layershot and run `layershot setup`.

**Or do it yourself. It takes two commands:**

```bash
pip install git+https://github.com/Kishore180994/layershot
layershot setup
```

`layershot setup` finds the agents on your PC and configures each one:

| Agent | What setup does |
|---|---|
| Claude Code | `claude mcp add --scope user layershot`, plus the agent rule in `~/.claude/CLAUDE.md` |
| Codex | `[mcp_servers.layershot]` in `~/.codex/config.toml`, plus the rule in `~/.codex/AGENTS.md` |
| Claude Desktop | `mcpServers.layershot` in `claude_desktop_config.json` |
| Cursor | `mcpServers.layershot` in `~/.cursor/mcp.json` |
| Hermes Agent | `mcp_servers.layershot` in `config.yaml` (restart Hermes) |

It's safe to re-run: it skips what's already there and updates the rule in place. The rule lives
between `<!-- layershot:begin -->` / `<!-- layershot:end -->` markers. `layershot setup --remove` takes
everything back out, and `--dry-run` shows what would change. `--agents codex,cursor` limits it to those agents.

Even without `setup`, the MCP server sends the same rule as its *server instructions*, which clients
like Claude Code put into the model's prompt automatically.

Manual install:

```bash
pip install git+https://github.com/Kishore180994/layershot
```

Or run it without installing, using [uv](https://docs.astral.sh/uv/):

```bash
uvx --from git+https://github.com/Kishore180994/layershot layershot list
```

From a clone:

```bash
git clone https://github.com/Kishore180994/layershot && cd layershot && pip install -e .
```

## Use it from an AI agent (MCP)

**Claude Code**

```bash
claude mcp add --scope user layershot -- layershot-mcp
# or without installing anything:
claude mcp add --scope user layershot -- uvx --from git+https://github.com/Kishore180994/layershot layershot-mcp
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

**Hermes Agent** (`config.yaml`):

```yaml
mcp_servers:
  layershot:
    command: layershot-mcp
```

Tip: tell your agent in its system prompt or instructions to *use layershot instead of
focusing a window to look at it*. Agents otherwise tend to reach for the full-screen screenshot
tool they already know.

Tools:

- `list_windows(include_minimized=True)` returns the windows front to back, each with `layer`, `hwnd`, `title`, `process`, `minimized` and `foreground`.
- `screenshot_window(layer | title | process | hwnd, keep_open=False, max_width=1600, format="png", save_to=None)` returns the image plus a one-line description.
- `open_app(target, args=None, cwd=None, front=False, wait=8)` opens an exe, file, folder or URL.
  It opens in the background by default; `front=True` is for when the user asked to see it. It returns the new
  window(s) with their layers.
- `bring_to_front(layer | title | process | hwnd)` restores and focuses a window, for user requests
  only.

Titles match loosely: "Bambu Studio" finds `plate - BambuStudio` (`bambu-studio.exe`).

**The agent rule** (in [`layershot/rules.py`](layershot/rules.py)) is sent as MCP server
instructions, and `layershot setup` writes it into CLAUDE.md / AGENTS.md. In short: look with
`screenshot_window` and never switch to the window; when the agent needs an app for its own work,
`open_app` opens it in the background; only when the user asks to open or show something does the agent
use `open_app(front=True)` or `bring_to_front`. For another agent, paste the rule into its
system prompt.

## Use it from Python

```python
import layershot

for w in layershot.list_windows():
    print(w.layer, w.process, w.title)

img, win = layershot.capture(title="Obsidian")      # PIL.Image
img, win = layershot.capture(2)                     # by layer
img, win = layershot.capture(process="code.exe", keep_open=True)

layershot.open_app("mspaint.exe")                   # background, focus stays with the user
layershot.open_app(r"C:\models\part.3mf")           # default app, background
layershot.open_app("notepad.exe", front=True)       # the user asked to see it
layershot.bring_to_front(title="Bambu Studio")
```

## CLI

```
layershot list [--json] [--no-minimized]
layershot shot <layer|title> [--process exe] [--hwnd 0x...] [-o out.png] [--keep-open]
layershot open [--front] <app|file|url> [args...]
layershot front <layer|title>
layershot setup [--agents a,b] [--no-rules] [--remove] [--dry-run]
layershot serve            # MCP server on stdio (same as layershot-mcp)
```

## Limits

- **Windows 10 1809+ only.** `PW_RENDERFULLCONTENT` is needed for GPU-drawn apps.
- **Minimized windows:** while one is restored for the capture (about 0.3–1 s), it sits behind your other windows, so it can show through gaps on an uncovered part of the desktop. It never takes focus.
- **Restore size:** a window minimized from *maximized* comes back at its normal size for the capture, because Windows can't maximize a window without activating it.
- **Hardware-protected content** (DRM video, some games running fullscreen) captures black, the same as in any screenshot tool.
- **Other virtual desktops:** those windows are skipped by `list_windows`.
- **Background opening:** an app that's *already open* and gets reused (a URL opening as a new
  tab in your existing browser, for example) stays where it is. If it still manages to activate
  itself, layershot hands focus back to you right away.
- layershot looks and opens, but it doesn't click or type yet. Input into background windows (UI Automation / window messages) is planned for a later version.

## Development

```bash
pip install -e .
python tests/mcp_smoke.py      # starts the MCP server, lists windows, captures one titled "Obsidian"
python tests/test_installer.py # setup add / re-run / --remove against fake configs in a temp home
```

Edit the title in `tests/mcp_smoke.py` to match a window you have open. Issues and PRs are
welcome, especially for background *input* (see the roadmap in
[docs/HOW-IT-WORKS.md](docs/HOW-IT-WORKS.md#ideas--roadmap)).

## License

MIT. See [LICENSE](LICENSE).
