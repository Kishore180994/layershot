"""layershot list | layershot shot <layer|title> [-o out.png] | layershot serve"""
from __future__ import annotations

import argparse
import json
import sys


def main(argv=None):
    p = argparse.ArgumentParser(prog="layershot",
                                description="Screenshot background windows without focusing them.")
    sub = p.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list", help="list windows front to back")
    ls.add_argument("--json", action="store_true")
    ls.add_argument("--no-minimized", action="store_true")
    sh = sub.add_parser("shot", help="capture one window")
    sh.add_argument("target", nargs="?", help="layer number or title substring")
    sh.add_argument("--process", help="match by process name, e.g. obsidian.exe")
    sh.add_argument("--hwnd", type=lambda s: int(s, 0))
    sh.add_argument("-o", "--out", default="layershot.png")
    sh.add_argument("--keep-open", action="store_true",
                    help="leave a minimized window restored (behind the others) afterwards")
    op = sub.add_parser("open", help="open an app/file/URL in the background (or --front)")
    op.add_argument("target")
    op.add_argument("args", nargs=argparse.REMAINDER, help="arguments passed to the app")
    op.add_argument("--front", action="store_true", help="open in front and focus it")
    fr = sub.add_parser("front", help="bring a window to the front (restores if minimized)")
    fr.add_argument("target", help="layer number or title substring")
    el = sub.add_parser("elements", help="list a window's controls (ids for click/type)")
    el.add_argument("target")
    el.add_argument("--query")
    ck = sub.add_parser("click", help="click in a background window: by element id or x y (full-size px)")
    ck.add_argument("target")
    ck.add_argument("where", nargs="+", help="element id like e12, or x y")
    ck.add_argument("--right", action="store_true")
    ck.add_argument("--double", action="store_true")
    ty = sub.add_parser("type", help="type text into a background window")
    ty.add_argument("target")
    ty.add_argument("text")
    ty.add_argument("--element")
    ty.add_argument("--enter", action="store_true")
    ky = sub.add_parser("key", help="press a key in a background window (enter, tab, esc, ...)")
    ky.add_argument("target")
    ky.add_argument("key")
    fl = sub.add_parser("flash", help="real input for apps that ignore background clicks: the window comes "
                                      "forward for a moment, runs the steps, focus goes back")
    fl.add_argument("target")
    fl.add_argument("steps", help='JSON list, e.g. \'[{"click":[1690,50]},{"key":"ctrl+r"},{"wait":1}]\'')
    vw = sub.add_parser("viewer", help="the floating AI-view window (runs it; agents start it automatically)")
    vw.add_argument("--off", action="store_true", help="never start it automatically")
    vw.add_argument("--on", action="store_true", help="start it automatically again (default)")
    vw.add_argument("--quit", action="store_true", help="close the running viewer")
    vw.add_argument("--hotkey", help='show/hide hotkey, e.g. "ctrl+alt+l" (takes effect on next start)')
    vw.add_argument("--theme", help="default | hud (cyan HUD look); takes effect on next start")
    st = sub.add_parser("setup", help="register the MCP server with your agents and add the agent rule")
    st.add_argument("--agents", help="comma list: claude-code,codex,claude-desktop,cursor,hermes "
                                     "(default: every one installed)")
    st.add_argument("--no-rules", action="store_true", help="don't touch CLAUDE.md / AGENTS.md")
    st.add_argument("--remove", action="store_true", help="undo: unregister and remove the rule block")
    st.add_argument("--dry-run", action="store_true", help="show what would change")
    sub.add_parser("serve", help="run the MCP server on stdio")
    a = p.parse_args(argv)

    if a.cmd == "serve":
        from .server import main as serve
        return serve()

    if a.cmd == "setup":
        from .installer import server_command, setup
        rows = setup(a.agents.split(",") if a.agents else None, rules=not a.no_rules,
                     remove=a.remove, dry_run=a.dry_run)
        print(("[dry run] " if a.dry_run else "") + "server command: " + " ".join(server_command()))
        for name, what in rows or [("-", "no supported agents found")]:
            print(f"  {name:<15} {what}")
        return 0

    if a.cmd == "viewer":
        from . import activity
        if a.hotkey:
            activity.save_prefs(hotkey=a.hotkey)
        if a.theme:
            activity.save_prefs(theme=a.theme)
        if a.off or a.on:
            activity.save_prefs(viewer="off" if a.off else "auto")
        if a.quit and activity.viewer_running():
            activity.save_prefs(quit=True)
        if not (a.off or a.on or a.quit or a.hotkey or a.theme):
            activity.save_prefs(viewer_hidden=False)
            from .viewer import main as run_viewer
            return run_viewer()
        print("viewer prefs:", activity.prefs())
        return 0

    if a.cmd == "flash":
        from .flash import flash
        t = int(a.target) if a.target.isdigit() else a.target
        print(flash(t, steps=json.loads(a.steps)))
        return 0

    if a.cmd in ("elements", "click", "type", "key"):
        from . import actions
        t = int(a.target) if a.target.isdigit() else a.target
        if a.cmd == "elements":
            r = actions.find_elements(t, query=a.query)
            for e in r["elements"]:
                print(f"{e['id']:>5} {e['type']:<10} {e['name'][:50]:<50} {e['rect']} {','.join(e['actions'])}")
        elif a.cmd == "click":
            kw = ({"element": a.where[0]} if len(a.where) == 1 else {"x": float(a.where[0]), "y": float(a.where[1])})
            print(actions.click(t, button="right" if a.right else "left", double=a.double, **kw))
        elif a.cmd == "type":
            print(actions.type_text(t, text=a.text, element=a.element, enter=a.enter))
        else:
            print(actions.press_key(t, key=a.key))
        return 0

    from . import core
    if a.cmd == "open":
        from .launch import open_app
        r = open_app(a.target, " ".join(a.args) or None, front=a.front)
        for w in r["windows"]:
            print(f"opened layer {w['layer']}: {w['title']} ({w['process']})")
        if r["note"]:
            print(r["note"])
        return 0
    if a.cmd == "front":
        from .launch import bring_to_front
        w = bring_to_front(a.target)
        print(f"front: {w.title}")
        return 0
    if a.cmd == "list":
        wins = core.list_windows(not a.no_minimized)
        if a.json:
            print(json.dumps([w.to_dict() for w in wins], indent=2))
        else:
            for w in wins:
                flag = "FG " if w.foreground else "MIN" if w.minimized else "   "
                print(f"{w.layer:>3} {flag} {w.process:<24.24} {w.title[:70]}")
        return 0

    if a.target is None and a.process is None and a.hwnd is None:
        p.error("give a layer, a title, --process or --hwnd")
    img, win = core.capture(a.target, process=a.process, hwnd=a.hwnd, keep_open=a.keep_open)
    img.save(a.out)
    print(f"saved {a.out}  {img.width}x{img.height}  layer {win.layer}  {win.title}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
