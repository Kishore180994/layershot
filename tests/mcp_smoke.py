"""End-to-end check: start layershot-mcp over stdio, list windows, screenshot the back one."""
import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    params = StdioServerParameters(command=sys.executable, args=["-m", "layershot.server"])
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        print("tools:", [t.name for t in (await s.list_tools()).tools])
        res = await s.call_tool("list_windows", {})
        print("list_windows ->", res.content[0].text[:200].replace("\n", " "), "...")
        res = await s.call_tool("screenshot_window", {"title": "Obsidian", "max_width": 800})
        for c in res.content:
            print(" ", c.type, c.text if c.type == "text" else f"{getattr(c, 'mime_type', None) or c.mimeType} {len(c.data)} b64 chars")
        assert any(c.type == "image" for c in res.content), res


asyncio.run(main())
