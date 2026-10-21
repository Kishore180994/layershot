"""`layershot setup`: register the MCP server with the agents on this PC and add the agent rule.

Idempotent: re-running updates the rule block in place and skips agents that already have
the server. `--remove` takes everything back out.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .rules import BEGIN, END, block

HOME = Path.home()
APPDATA = Path(os.environ.get("APPDATA", HOME / "AppData/Roaming"))
LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA", HOME / "AppData/Local"))
REPO = "layershot"  # the PyPI package, for agents started through uvx


def server_command() -> list[str]:
    """How an agent should start the MCP server from this install."""
    exe = shutil.which("layershot-mcp")
    prefix = Path(sys.prefix).as_posix().lower()
    if "/uv/" in prefix and ("/archive" in prefix or "/cache" in prefix):
        # running from a throwaway `uvx` env: point agents at uvx so the path stays valid
        return ["uvx", "--from", REPO, "layershot-mcp"]
    if exe:
        return [exe]
    return [sys.executable, "-m", "layershot.server"]


# ---------- rule block in instruction files ----------

_BLOCK_RE = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", re.S)


def _write_rules(path: Path, remove: bool, dry: bool) -> str:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    has = bool(_BLOCK_RE.search(text))
    if remove:
        if not has:
            return "no rule block"
        new = _BLOCK_RE.sub("", text).rstrip() + "\n"
        action = "rule removed"
    elif has:
        new = _BLOCK_RE.sub(lambda _: block(), text)
        action = "rule updated" if new != text else "rule up to date"
    else:
        new = (text.rstrip() + "\n\n" if text.strip() else "") + block()
        action = "rule added"
    if new != text and not dry:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new, encoding="utf-8")
    return action


# ---------- per-agent MCP registration ----------

def _claude_code(cmd, remove, dry):
    claude = shutil.which("claude")
    if not claude:
        return None
    have = subprocess.run([claude, "mcp", "get", "layershot"], capture_output=True, text=True).returncode == 0
    if remove:
        if have and not dry:
            subprocess.run([claude, "mcp", "remove", "--scope", "user", "layershot"], capture_output=True)
        return "mcp removed" if have else "mcp not registered"
    if have:
        return "mcp already registered"
    if not dry:
        r = subprocess.run([claude, "mcp", "add", "--scope", "user", "layershot", "--", *cmd],
                           capture_output=True, text=True)
        if r.returncode:
            return "mcp add FAILED: " + (r.stderr or r.stdout).strip()[:200]
    return "mcp registered"


def _toml_str(s: str) -> str:
    return "'" + s + "'" if "'" not in s else json.dumps(s)


def _codex(cmd, remove, dry):
    cfg = HOME / ".codex" / "config.toml"
    if not cfg.parent.exists():
        return None
    text = cfg.read_text(encoding="utf-8") if cfg.exists() else ""
    sec = re.compile(r"\n?\[mcp_servers\.layershot\]\n(?:(?!\[).*\n?)*")
    have = bool(sec.search(text))
    if remove:
        if have and not dry:
            cfg.write_text(sec.sub("\n", text).rstrip() + "\n", encoding="utf-8")
        return "mcp removed" if have else "mcp not registered"
    if have:
        return "mcp already registered"
    entry = (f"\n[mcp_servers.layershot]\ncommand = {_toml_str(cmd[0])}\n"
             f"args = [{', '.join(_toml_str(a) for a in cmd[1:])}]\n")
    if not dry:
        cfg.write_text(text.rstrip() + "\n" + entry, encoding="utf-8")
    return "mcp registered"


def _json_mcp(cfg: Path, cmd, remove, dry):
    if not cfg.parent.exists():
        return None
    data = json.loads(cfg.read_text(encoding="utf-8") or "{}") if cfg.exists() else {}
    servers = data.setdefault("mcpServers", {})
    have = "layershot" in servers
    if remove:
        if have and not dry:
            del servers["layershot"]
            cfg.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return "mcp removed" if have else "mcp not registered"
    if have:
        return "mcp already registered"
    servers["layershot"] = {"command": cmd[0], "args": cmd[1:]}
    if not dry:
        cfg.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return "mcp registered"


def _hermes(cmd, remove, dry):
    cfg = LOCALAPPDATA / "hermes" / "config.yaml"
    if not cfg.exists():
        return None
    text = cfg.read_text(encoding="utf-8")
    sec = re.compile(r"^  layershot:\n(?:^    .*\n|^\s*\n)*", re.M)
    have = bool(sec.search(text))
    if remove:
        if have and not dry:
            cfg.write_text(sec.sub("", text), encoding="utf-8")
        return "mcp removed (restart Hermes)" if have else "mcp not registered"
    if have:
        return "mcp already registered"
    q = lambda s: json.dumps(s.replace("\\", "/"))  # JSON strings are valid YAML scalars
    entry = f"  layershot:\n    command: {q(cmd[0])}\n"
    if cmd[1:]:
        entry += "    args:\n" + "".join(f"      - {q(a)}\n" for a in cmd[1:])
    entry += "    enabled: true\n"
    if re.search(r"^mcp_servers:\s*$", text, re.M):
        new = re.sub(r"^mcp_servers:\s*\n", lambda m: m.group(0) + entry, text, count=1, flags=re.M)
    else:
        new = text.rstrip() + "\nmcp_servers:\n" + entry
    if not dry:
        cfg.write_text(new, encoding="utf-8")
    return "mcp registered (restart Hermes to load it)"


AGENTS = {
    # name: (register fn, instruction file that gets the rule block or None)
    "claude-code": (_claude_code, HOME / ".claude" / "CLAUDE.md"),
    "codex": (_codex, HOME / ".codex" / "AGENTS.md"),
    "claude-desktop": (lambda c, r, d: _json_mcp(APPDATA / "Claude" / "claude_desktop_config.json", c, r, d), None),
    "cursor": (lambda c, r, d: _json_mcp(HOME / ".cursor" / "mcp.json", c, r, d), None),
    "hermes": (_hermes, None),
}


def setup(agents: list[str] | None = None, *, rules: bool = True, remove: bool = False,
          dry_run: bool = False) -> list[tuple[str, str]]:
    """Register/unregister layershot with every detected agent. Returns (agent, what happened) rows."""
    cmd = server_command()
    out = []
    for name, (register, rules_file) in AGENTS.items():
        if agents and name not in agents:
            continue
        try:
            result = register(cmd, remove, dry_run)
        except Exception as e:  # one broken config must not stop the others
            result = f"FAILED: {e}"
        if result is None:
            continue  # agent not installed
        if rules and rules_file is not None:
            result += "; " + _write_rules(rules_file, remove, dry_run) + f" in {rules_file}"
        out.append((name, result))
    return out
