#!/usr/bin/env python3
"""MCP server exposing setlist.fm lookups as tools (stdio transport)."""

import functools
import json
import logging
import os
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Annotated, Any, Callable

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from setlist_fm_client import FixtureMissError
from setlist_fm_client import get_setlists_by_artist_name as _get_setlists_by_artist_name

# stdout carries the MCP protocol; logging goes to stderr.
logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

# Tool calls (arguments + exact JSON returned) go to a separate JSON Lines file:
#   tail -f logs/tool_calls.jsonl | jq .
# SETLISTFM_LOG_DIR redirects it (the eval runner uses this to keep one log per run).
LOG_DIR = Path(os.environ.get("SETLISTFM_LOG_DIR", Path(__file__).resolve().parent / "logs"))
LOG_DIR.mkdir(exist_ok=True)
tool_call_log = logging.getLogger("tool_calls")
tool_call_log.setLevel(logging.INFO)
tool_call_log.propagate = False  # keep these out of stderr
_handler = RotatingFileHandler(
    LOG_DIR / "tool_calls.jsonl", maxBytes=5_000_000, backupCount=2, encoding="utf-8"
)
_handler.setFormatter(logging.Formatter("%(message)s"))
tool_call_log.addHandler(_handler)


def _write_entry(entry: dict[str, Any]) -> None:
    """Write one call as a single JSON line."""
    tool_call_log.info(json.dumps(entry, ensure_ascii=False, default=str))


def log_tool_call(func: Callable[..., Any]) -> Callable[..., Any]:
    """Log each call's arguments, duration and exact JSON response (or error)."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        entry: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "tool": func.__name__,
            "args": kwargs,
        }
        start = time.perf_counter()
        try:
            result = func(*args, **kwargs)
        except Exception as e:
            entry["duration_ms"] = round((time.perf_counter() - start) * 1000)
            entry["error"] = f"{type(e).__name__}: {e}"
            _write_entry(entry)
            raise
        entry["duration_ms"] = round((time.perf_counter() - start) * 1000)
        response = json.dumps(result, ensure_ascii=False, default=str)
        entry["response_chars"] = len(response)
        entry["response"] = result
        _write_entry(entry)
        return result

    return wrapper


mcp = MCPServer(
    "setlist-fm",
    instructions="Look up concert setlists from setlist.fm.",
)


def _compact_setlist(setlist: dict[str, Any]) -> dict[str, Any]:
    """Reduce a setlist.fm setlist to when/where it happened, without songs."""
    venue = setlist.get("venue") or {}
    city = venue.get("city") or {}
    return {
        "eventDate": setlist.get("eventDate"),
        "venue": venue.get("name"),
        "city": city.get("name"),
        "country": (city.get("country") or {}).get("name"),
        "tour": (setlist.get("tour") or {}).get("name"),
    }


@mcp.tool()
@log_tool_call
def get_setlists_by_artist_name(
    artist_name: Annotated[str, Field(description='Artist or band name, e.g. "Radiohead".')],
    page: Annotated[
        int, Field(ge=1, description="Page of setlists to return, starting at 1 (20 per page).")
    ] = 1,
    compact_mode: Annotated[
        bool,
        Field(
            description=(
                "If true, each setlist contains only eventDate, venue, city, country and "
                "tour (null if not part of a tour), with no song lists. If false, each "
                "setlist is the full setlist.fm record including sets and songs."
            )
        ),
    ] = False,
) -> dict[str, Any]:
    """Get concert setlists for an artist by name, most recent first (20 per page).

    The name must be spelled correctly; setlist.fm search does not tolerate typos.
    The artist whose name matches exactly (case-insensitive) is used, otherwise the
    most relevant search result. Check `artist` in the result to confirm the right
    artist was picked; `otherMatches` lists other artists the name matched.

    Dates are in dd-MM-yyyy format. `setlists.total` is the number of setlists across
    all pages; request further pages with `page` to see older concerts.

    Use compact_mode=true when you only need to know when and where the artist played
    (tour history, recent or upcoming shows, cities or countries visited). It is much
    smaller and lets you scan many pages cheaply. Use the default (false) when you need
    the songs that were played.
    """
    try:
        result = _get_setlists_by_artist_name(artist_name, page)
    except FixtureMissError as e:
        # ToolError keeps the message in the tool result (other errors are hidden),
        # so the eval runner can tell a missing fixture from a real failure.
        raise ToolError(str(e)) from e
    if result is None:
        return {"error": f"No artist found on setlist.fm for '{artist_name}'."}

    if compact_mode and result["setlists"]:
        setlists = result["setlists"]
        result = {
            **result,
            "setlists": {
                **setlists,
                "setlist": [_compact_setlist(s) for s in setlists.get("setlist", [])],
            },
        }
    return result


if __name__ == "__main__":
    mcp.run()
