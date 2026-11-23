#!/usr/bin/env python3
"""Live smoke test: does the MCP server still work against the real setlist.fm API?

A free check that the API key works and the responses still have the shape the
server relies on, without paying for an eval run. This script starts server.py over
stdio (as Claude Desktop does),
with an empty throwaway cache so every request goes to setlist.fm, and checks the shape
of what comes back. It does not call Claude and costs nothing but 7 setlist.fm requests.

    python smoke_test.py

Exits non-zero if any check fails.
"""

import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp import Client, StdioServerParameters

PROJECT_DIR = Path(__file__).resolve().parent
TOOL = "get_setlists_by_artist_name"

failures: list[str] = []


def check(ok: bool, what: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {what}")
    if not ok:
        failures.append(what)


async def call(mcp: Client, **arguments: Any) -> dict[str, Any] | None:
    """Call the tool; return its JSON result, or None (and record a failure) on error."""
    result = await mcp.call_tool(TOOL, arguments)
    text = "\n".join(c.text for c in result.content if getattr(c, "type", None) == "text")
    if result.is_error:
        check(False, f"{arguments} returned a tool error: {text[:300]}")
        return None
    return json.loads(text)


def is_date(value: Any) -> bool:
    try:
        datetime.strptime(value, "%d-%m-%Y")
        return True
    except (TypeError, ValueError):
        return False


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        server = StdioServerParameters(
            command=sys.executable,
            args=[str(PROJECT_DIR / "server.py")],
            env={
                **os.environ,
                "SETLISTFM_CACHE_PATH": str(Path(tmp) / "cache"),  # empty: everything is live
                "SETLISTFM_LOG_DIR": tmp,
            },
        )
        async with Client(server) as mcp:
            tools = [t.name for t in (await mcp.list_tools()).tools]
            print("server")
            check(TOOL in tools, f"server exposes {TOOL}")

            print("compact mode (Vennaskond)")
            r = await call(mcp, artist_name="Vennaskond", compact_mode=True)
            if r:
                check(r["artist"].get("name") == "Vennaskond", "exact name match picked")
                check(bool(r["artist"].get("mbid")), "artist has an mbid")
                s = r.get("setlists") or {}
                check(s.get("total", 0) > 0, "has setlists (total > 0)")
                check(s.get("itemsPerPage") == 20, "20 setlists per page")
                first = (s.get("setlist") or [{}])[0]
                check(set(first) == {"eventDate", "venue", "city", "country", "tour"},
                      "compact setlist has exactly eventDate, venue, city, country, tour")
                check(is_date(first.get("eventDate")), "eventDate is dd-MM-yyyy")
                check(bool(first.get("country")), "country is filled in")

            print("full mode and paging (Vennaskond, page 2)")
            r = await call(mcp, artist_name="Vennaskond", page=2)
            if r:
                s = r.get("setlists") or {}
                check(s.get("page") == 2, "page 2 returned")
                first = (s.get("setlist") or [{}])[0]
                # Fields ground_truth.py and compact mode depend on.
                check("sets" in first, "full setlist includes sets (songs)")
                check(bool((first.get("venue") or {}).get("city", {}).get("country", {}).get("name")),
                      "full setlist has venue.city.country.name")

            print("ambiguous name (The National)")
            r = await call(mcp, artist_name="The National", compact_mode=True)
            if r:
                check(r["artist"].get("name") == "The National", "exact name match picked")
                check(len(r.get("otherMatches", [])) > 0, "otherMatches lists other candidates")

            print("unknown artist")
            r = await call(mcp, artist_name="Zzqx Nonexistent Band 9137")
            if r:
                check("No artist found" in r.get("error", ""), "returns a 'No artist found' error")

    if failures:
        print(f"\n{len(failures)} check(s) failed.")
        sys.exit(1)
    print("\nAll checks passed.")


if __name__ == "__main__":
    asyncio.run(main())
