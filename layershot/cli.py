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
    sub.add_parser("serve", help="run the MCP server on stdio")
    a = p.parse_args(argv)

    if a.cmd == "serve":
        from .server import main as serve
        return serve()

    from . import core
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
