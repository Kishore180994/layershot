"""layershot setup on fake configs in a temp home: add, re-run (no change), remove (back to original)."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

home = Path(tempfile.mkdtemp())
(home / ".codex").mkdir()
(home / ".cursor").mkdir()
(home / "Local" / "hermes").mkdir(parents=True)
codex = home / ".codex" / "config.toml"
codex.write_text("[mcp_servers.brain]\ncommand = 'python'\nargs = ['brain.py']\n", encoding="utf-8")
agents_md = home / ".codex" / "AGENTS.md"
agents_md.write_text("# My rules\n\n- be nice\n", encoding="utf-8")
hermes = home / "Local" / "hermes" / "config.yaml"
hermes.write_text("model: x\nmcp_servers:\n  brain:\n    command: python\n    enabled: true\nplatforms:\n  cli: {}\n",
                  encoding="utf-8")
originals = {p: p.read_text(encoding="utf-8") for p in (codex, agents_md, hermes)}

env = dict(os.environ, USERPROFILE=str(home), HOME=str(home), LOCALAPPDATA=str(home / "Local"),
           APPDATA=str(home / "Roaming"))
run = lambda *a: subprocess.run([sys.executable, "-m", "layershot.cli", "setup",
                                 "--agents", "codex,cursor,hermes,claude-desktop", *a],
                                env=env, capture_output=True, text=True, check=True).stdout

print(run())
snap = {p: p.read_text(encoding="utf-8") for p in (codex, agents_md, hermes)}
assert "[mcp_servers.layershot]" in snap[codex] and "[mcp_servers.brain]" in snap[codex]
assert "layershot:begin" in snap[agents_md] and "be nice" in snap[agents_md]
assert "  layershot:\n" in snap[hermes] and "platforms:" in snap[hermes]
assert '"layershot"' in (home / ".cursor" / "mcp.json").read_text()
import tomllib, yaml
tomllib.loads(snap[codex]); yaml.safe_load(snap[hermes])  # still valid files
assert yaml.safe_load(snap[hermes])["mcp_servers"]["layershot"]["enabled"] is True

print(run())
assert snap == {p: p.read_text(encoding="utf-8") for p in snap}, "second run changed files"

print(run("--remove"))
for p, orig in originals.items():
    assert p.read_text(encoding="utf-8").strip() == orig.strip(), f"{p.name} not restored:\n{p.read_text()}"
print("OK: add, idempotent re-run, clean remove")
