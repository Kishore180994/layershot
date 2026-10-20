# How layershot works (detailed notes)

These notes cover what layershot does, why each step is there, and what we measured
while building it. They're aimed at anyone who wants to extend it, port it, or debug a window
that won't capture.

## The problem

Most desktop-automation and "computer use" tools look at an app by:

1. bringing the app to the front (`SetForegroundWindow`, Alt+Tab, clicking the taskbar…),
2. grabbing the whole screen (`BitBlt` from the desktop DC, `ImageGrab`, `mss`…),
3. optionally switching back.

Step 1 is the problem. The agent takes over the screen and steals keyboard focus, so a key the
user is typing lands in the wrong app, and the user has to wait until the agent is done.
With several agents (or one agent taking many screenshots) the PC becomes unusable.

## The key fact: every window already has its own image

Since Windows Vista, the **Desktop Window Manager (DWM)** composes the screen. Each
top-level window draws into its own off-screen *redirection surface*, and DWM stacks those
surfaces to build what you see. A window that's covered by others still has a complete,
up-to-date surface. It just isn't shown.

So we don't need the window to be *visible*. We need to read its surface.

## Capturing a covered window

```c
PrintWindow(hwnd, memDC, PW_RENDERFULLCONTENT /* = 2 */);
```

- `PrintWindow` asks for the window's own content rather than the screen pixels in its rect.
- The `PW_RENDERFULLCONTENT` flag (Windows 8.1+, reliable on 10 1809+) makes it read the
  DWM surface. Without the flag, GPU-drawn apps (Chrome, Electron, UWP, DirectX/OpenGL
  viewports) come back **black**, because they never draw through GDI.
- No focus change, no z-order change, no flicker. On a 1920×1032 window it takes ~80 ms
  including the forced repaint and PNG-ready conversion.

The bitmap is read with `GetDIBits` as top-down 32-bit BGRX and turned into a Pillow image.

### Trimming the invisible border

On Windows 10/11, `GetWindowRect` includes an invisible ~7 px resize border on the left, right and
bottom, which captures as black or garbage. layershot asks DWM for the *visible* frame
(`DwmGetWindowAttribute(DWMWA_EXTENDED_FRAME_BOUNDS)`) and crops to it.

### DPI

The process opts into **per-monitor DPI awareness v2** at import
(`SetProcessDpiAwarenessContext(-4)`). Without it, on a scaled display (125%, 150%…) Windows
gives you scaled-down rects and you capture a cropped or blurry window.

## Minimized windows

A minimized window has **no surface**. DWM throws it away, and `PrintWindow` returns only a
tiny title-bar stub (we measured 160×28). There's no API that renders a minimized window
without un-minimizing it, so layershot un-minimizes it in a way that leaves the user alone:

```c
SetWindowPos(hwnd, HWND_BOTTOM, 0,0,0,0, SWP_NOMOVE|SWP_NOSIZE|SWP_NOACTIVATE); // 1
ShowWindow(hwnd, SW_SHOWNOACTIVATE);                                            // 2
SetWindowPos(hwnd, HWND_BOTTOM, 0,0,0,0, SWP_NOMOVE|SWP_NOSIZE|SWP_NOACTIVATE); // 3
// ... repaint + capture ...
ShowWindow(hwnd, SW_SHOWMINNOACTIVE);                                           // 4
```

1. Move it to the bottom of the z-order *while still minimized*, so it doesn't pop up on top when
   restored.
2. Restore it **without activating it**. Keyboard focus and the foreground window don't change.
3. Push it to the bottom again, because some apps raise themselves while restoring.
4. Minimize it again, also without activating anything (skipped when `keep_open=True`).

Measured on real apps: minimized Obsidian 0.27 s, minimized Chrome 0.29 s, both full-quality,
and the foreground window was unchanged in every run.

As a safety net, if the foreground window somehow changed during a capture, layershot gives
focus back to the window that had it before.

**What the user can notice:** while the window is restored (~0.3 s) it sits behind every other
window, so it shows through only on parts of the desktop that nothing else covers. The taskbar
button may briefly look "restored".

**Maximized windows:** a window that was maximized before it was minimized comes back at its
*normal* (restored) size, because `SW_SHOWNOACTIVATE` restores rather than maximizes, and
`SW_MAXIMIZE`/`SW_SHOWMAXIMIZED` always activate the window. In practice most apps remember
their restored size close to the screen size.

## Chromium / Electron blank captures

Chrome, Edge, VS Code, Obsidian, Discord, Slack and other Chromium-based apps have
**native window occlusion tracking**: when Chromium decides its window is fully covered, it
stops producing frames to save power. The DWM surface then holds a blank (or stale) frame.

When we restored a minimized Obsidian window at the very bottom of 18 windows and captured
after a fixed 0.5 s, we got a flat grey image.

The fix is in `capture()`:

1. Force a repaint before every attempt:
   `RedrawWindow(hwnd, NULL, NULL, RDW_INVALIDATE|RDW_ERASE|RDW_ALLCHILDREN|RDW_UPDATENOW|RDW_FRAME)`.
2. Capture.
3. If the image **looks blank** (downscaled to 48×48, every channel's min-max range < 6),
   wait 250 ms and repeat, up to `timeout` (default 3 s).

With the repaint, the same Obsidian window captured correctly on the first attempt, both from the bottom of
the stack and from just behind the active window. A truly uniform window (e.g. an empty
black canvas) just costs the full timeout and returns what it got.

## Listing windows ("layers")

`list_windows()` walks `EnumWindows`, which returns top-level windows **in z-order, front
to back**, and keeps only what a person would call an app window (roughly what Alt+Tab shows):

| Filter | Why |
|---|---|
| `IsWindowVisible` | hidden helper windows |
| not DWM-cloaked (`DWMWA_CLOAKED`) | windows on other virtual desktops, suspended UWP apps, background shell surfaces |
| not `WS_EX_TOOLWINDOW` | tooltips, floating palettes, overlays |
| has a title, not "Program Manager" | the desktop itself and untitled helpers |
| non-minimized windows must be > 1×1 px | zero-size message-only style windows |

`layer` is the index in that filtered list: **0 is the window the user is using**, 1 is the one
right behind it, and so on. Minimized windows keep their place in the z-order list.

The process name comes from `QueryFullProcessImageNameW` with
`PROCESS_QUERY_LIMITED_INFORMATION`, which works without admin for almost every process.
For elevated processes, it can come back empty when layershot itself isn't elevated.

## Concurrency

Captures are serialized with a process-wide lock, so two tool calls can't both
restore and re-minimize the same window at once. Separate processes (e.g. two different agents each
running their own layershot server) don't share the lock. In the worst case one of them captures
a window the other has just re-minimized, and the blank-retry loop handles that.

## Opening apps in the background

`open_app()` launches with `ShellExecuteExW` (so exe names on PATH / App Paths, full paths,
documents, folders and URLs all work) using `nShow = SW_SHOWNOACTIVATE`. That flag is
only a *request*: most apps call `SetForegroundWindow` during startup anyway. We measured
mspaint.exe on Windows 11 holding the foreground for ~3.5 s after a `SW_SHOWNOACTIVATE`
launch (344 of our 10 ms samples).

What actually stops it is **`LockSetForegroundWindow(LSFW_LOCK)`**. While the lock is held,
programs can't call `SetForegroundWindow` on themselves. *User* input (clicks, Alt+Tab) still works,
so the user is never locked out. Only the foreground thread may take the lock, so layershot briefly
attaches to the foreground window's input queue (`AttachThreadInput`), takes the lock, and
detaches. The same Paint launch with the lock held: **0 samples** with focus stolen.

The full sequence:

1. Record the user's foreground window and the current set of app windows.
2. Take the foreground lock (released in a `finally`, so it can't stay stuck).
3. `ShellExecuteExW(..., SW_SHOWNOACTIVATE)`.
4. For up to `wait` seconds (default 8), poll every 50 ms. Each new window goes to `HWND_BOTTOM`
   without activation. If the foreground changed anyway, push the thief to the back and give
   focus back to the user's window (`AttachThreadInput` + `SetForegroundWindow`). We stop once
   new windows have appeared and nothing new has shown up for 1 s.
5. Unlock, and return the new windows with their current layers.

`front=True` skips the lock, launches with `SW_SHOWNORMAL` and focuses the first new window, for when
the user asked to see the app.

`bring_to_front()` restores a minimized window and focuses it. A background process normally isn't
allowed to change the foreground, so it borrows the current foreground thread's input queue
(`AttachThreadInput`) for the `SetForegroundWindow` call.

**The policy has to reach the agent.** layershot can't know *why* an agent opens something, so the
rule ("background unless the user asked") has to reach the model. It's defined once in
`layershot/rules.py` and delivered three ways:

1. **MCP server instructions.** Clients that support them (Claude Code, Claude Desktop…) put them in the
   model's system prompt the moment the server connects. No user setup is needed.
2. **Tool descriptions.** `open_app` and `bring_to_front` say when `front` is allowed.
3. **`layershot setup`** writes the rule into the agent's own instruction file (`~/.claude/CLAUDE.md`,
   `~/.codex/AGENTS.md`) between `layershot:begin/end` markers. That also covers sessions that started
   before the MCP server existed, which then fall back to the `layershot` CLI.

We learned why layer 3 matters the hard way: a long-running Claude Code session had written its own "bring
the window to the front, then screenshot" helper weeks earlier, and it kept using it, because that
session had never loaded layershot.

## Things that will not work

| Case | Result |
|---|---|
| DRM-protected video (Netflix in Edge, some players) | black, same as any capture tool |
| Exclusive-fullscreen DirectX games | usually black or stale; borderless-windowed works |
| Windows on another virtual desktop | skipped by `list_windows` (cloaked); capturing by `hwnd` may return stale content |
| Elevated (admin) windows from a non-elevated layershot | `PrintWindow` can fail (UIPI); run layershot elevated if you need these |
| Remote Desktop session minimized on the client | the session has no desktop to draw on |

## Why not Windows.Graphics.Capture?

`Windows.Graphics.Capture` (WGC) is the modern API OBS and the Snipping Tool use. It also
captures covered windows, and it streams frames. We chose `PrintWindow` for v0.1 because:

- It's pure `ctypes`: no WinRT projection, no compiled extension, and no extra package for users to
  install.
- It's a single synchronous call per screenshot, which is what agents need.
- WGC draws a yellow capture border on Windows 10 (removable on Windows 11 only with an
  API-contract check), which would itself disturb the user.

WGC is a good backend to add later for streaming or video.

## Ideas / roadmap

- ~~Open apps in the background~~: done in 0.2.0 (`open_app`).
- **Background input:** click and type into a background window without focusing it, using
  UI Automation patterns (`InvokePattern`, `ValuePattern`) first and window messages
  (`PostMessage WM_LBUTTONDOWN/WM_CHAR`) as a fallback. That's the other half of "agents shouldn't take over
  the PC".
- **Region capture:** return only a sub-rectangle (e.g. one UI element from UI Automation).
- **Change detection:** "wait until this window looks different", for agents watching a long
  task.
- **WGC backend** for streaming.
