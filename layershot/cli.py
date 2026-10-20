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
