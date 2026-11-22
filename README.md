# setlist.fm MCP server

An [MCP](https://modelcontextprotocol.io/) server that lets Claude (or any MCP client)
answer questions about concerts using [setlist.fm](https://www.setlist.fm/) data:
*"What did Tame Impala play on their last tour?"*, *"Which countries did The National
play in in 2025?"*

It exposes one tool, `get_setlists_by_artist_name`, built on the
[setlist.fm REST API](https://api.setlist.fm/docs/1.0/index.html), plus an eval suite
that measures how well Claude uses it.

## Quick start

Requires Python 3.10+ and a setlist.fm API key (request one in your setlist.fm account
settings).

```bash
git clone https://github.com/sander24/setlist-fm-mcp.git
cd setlist-fm-mcp
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env    # then put your key in SETLISTFM_API_KEY
```

Check that the client works without involving MCP:

```bash
python try_client.py "Tame Impala"
```

### Use it in Claude Desktop

Add the server to `~/Library/Application Support/Claude/claude_desktop_config.json`
(**Settings → Developer → Edit Config**), using absolute paths:

```json
{
  "mcpServers": {
    "setlist-fm": {
      "command": "/path/to/setlist-fm-mcp/.venv/bin/python",
      "args": ["/path/to/setlist-fm-mcp/server.py"]
    }
  }
}
```

Quit Claude Desktop completely (Cmd+Q), reopen it, and ask something like *"Where did
Vennaskond play their last three concerts?"*

### Use it in Claude Code

```bash
claude mcp add setlist-fm -- /path/to/setlist-fm-mcp/.venv/bin/python /path/to/setlist-fm-mcp/server.py
```

## The tool

`get_setlists_by_artist_name(artist_name, page=1, compact_mode=false)`

| Parameter | Meaning |
|---|---|
| `artist_name` | Artist or band name. Must be spelled correctly: setlist.fm search does not tolerate typos. |
| `page` | Page of setlists, newest first, 20 per page. |
| `compact_mode` | `true` returns only date, venue, city, country and tour per show; `false` also includes the full song lists. |

The result contains:

- `artist`: the artist that was matched;
- `otherMatches`: other artists the name matched, so the model can tell when the name
  was ambiguous;
- `setlists`: the page of setlists, with `total` for paging.

## Design decisions

**One tool that takes a name, not "search" plus "get by ID".** setlist.fm needs an artist
ID (MBID) to list setlists, which normally means two calls. Folding the search into the
tool gives the model one call to get right and no IDs to carry between calls. The tool
picks the exact (case-insensitive) name match, or else the most relevant result. It
returns the other candidates as `otherMatches`, so an ambiguous name is visible instead
of silently wrong.

**`compact_mode`, because responses were mostly noise.** One page of full setlists for a
single artist measured ~26,000 characters, mostly song metadata, IDs and venue
coordinates the model never uses. Many questions are only about *when and where* an
artist played. Compact mode cuts that page to ~3,000 characters (about 9× smaller), so
the model can scan many pages cheaply. The tool description tells the model when to use
which mode.

**Caching and retries, because API quota is the real constraint.** setlist.fm keys are
rate-limited per second and per day. Responses are cached on disk (SQLite via
`requests-cache`), with longer lifetimes for data that rarely changes. Not-found
responses are cached too. Rate-limit and server errors are retried with exponential
backoff and never cached.

**A log of exactly what the model received.** Every tool call's arguments and full JSON
response are written to `logs/tool_calls.jsonl`. Debugging tool use starts with what
the model actually saw, not what you think the tool returns:

```bash
tail -f logs/tool_calls.jsonl | jq .
```

**The official MCP Python SDK.** The server uses the `mcp` package's `MCPServer` (the
class that was called `FastMCP` in v1), not the separate `fastmcp` package. A small
local stdio server doesn't need the extra features, and the official SDK tracks the
protocol spec directly.

## Evals

`evals/` runs realistic questions through Claude with the real MCP server and grades
two things: whether the tool was called correctly (artist, `compact_mode`), and whether
the answer is correct (an LLM judge compares it with ground truth). The data comes from
a frozen copy of setlist.fm responses, so the ground truth doesn't drift as new concerts
are added. Eval runs never touch the network: a request missing from the frozen copy
fails the attempt instead of fetching live data.

| Case | What it tests | Baseline |
|---|---|---|
| The National, countries in 2025 | No 2025 shows exist: does the model say so or invent some? | Pass (1 tool call, 11 s) |
| Tame Impala, countries in 2025 | 2025 shows are on pages 4–5: does the model keep paging? | Pass (6 tool calls, 15 s) |
| Mogwai, two most-played songs in 2025 | Songs need full mode across 5 pages (80 shows): are the counts exact? | Pass (9 tool calls, 36 s, ~$1.31) |

Baseline: `claude-opus-5-5`, one attempt per case. Three cases is a starting point, not a
benchmark. See [evals/README.md](evals/README.md) for running the evals and adding cases.

```bash
pip install -r evals/requirements.txt   # and add ANTHROPIC_API_KEY to .env
python evals/run_evals.py
```

## Live smoke test

The evals can't notice setlist.fm changing, because they run on frozen data. The smoke
test covers that gap. It starts the MCP server with an empty cache, sends a few real
requests (exact match, paging, full and compact mode, ambiguous name, unknown artist)
and checks the response shape. It doesn't call Claude and needs only `SETLISTFM_API_KEY`.

```bash
python smoke_test.py    # exits non-zero if any check fails
```

## Project layout

| Path | What it is |
|---|---|
| `server.py` | MCP server: the tool definition, compact mode, call logging |
| `setlist_fm_client.py` | setlist.fm API client: requests, caching, retries |
| `try_client.py` | Console script for trying the client by hand |
| `smoke_test.py` | Live check of the MCP server against the real setlist.fm API |
| `evals/` | Eval runner, cases, ground-truth helper, frozen data, results |

## Limitations and next steps

- Only one tool so far. Natural next ones: song statistics ("most-played songs on the
  last tour") and a lookup by MBID for when `otherMatches` shows the wrong artist was
  picked.
- `otherMatches` can be large for common names (about 30 artists for "The National"),
  which makes even compact responses ~12,600 characters. Trimming it is the next eval
  experiment.
- Grow the eval set beyond three cases: more song questions, ambiguous names, unknown artists.
- setlist.fm data is crowd-sourced, so missing shows mean "not on setlist.fm", not
  "didn't happen". Check setlist.fm's API terms before any commercial use.
