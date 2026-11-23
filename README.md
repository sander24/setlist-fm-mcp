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
the live setlist.fm API. The cases ask about 2025 or earlier, so the ground truth stays
valid while new concerts are added.

| Case | What it tests | Baseline |
|---|---|---|
| The National, countries in 2025 | No 2025 shows exist: does the model say so or invent some? | Pass (1 tool call, 11 s) |
| Tame Impala, countries in 2025 | 2025 shows come after several pages of 2026 ones: does the model keep paging? | Pass (6 tool calls, 15 s) |
| Tame Impala, Spain shows in 2025 | Spain shows in 2026 come first: is the count 2, not 4? | Pass (4 tool calls, 11 s, ~$0.15) |
| The Rolling Stones, Germany shows in 2024 | A country they play often (3 shows in 2022) but not in 2024: is the count 0? | Pass (2 tool calls, 14 s, ~$0.09) |
| Genialistid, last concert | No year in the question, and only 2 setlists on setlist.fm: does it name the latest (Tartu, 5 Jul 2024) without inventing a later one? | Pass (1 tool call, 7 s, ~$0.02) |
| Unknown artist, "Metallica Gangsta Rap Big Band" | No such artist on setlist.fm: does it say so, without inventing shows or passing off Metallica's? | Pass (1 tool call, 8 s, ~$0.02) |
| My Dying Bride, gigs in each of 2023 and 2024 | Two years in one question, with a close year boundary and 17 gigs in 2025 coming first: is it 7 and 2? | Pass (3 tool calls, 13 s, ~$0.06) |
| Mogwai, top three songs in Q1 2025 | Songs need full mode, Q1 starts and ends mid-page, and two songs tie for second: are the counts exact? | Pass (6 tool calls, 26 s, ~$0.42) |

Baseline: `claude-opus-5-5` (judge: `claude-sonnet-5-5`), one attempt per case. The evals
now run on `claude-sonnet-5-5` by default, judged by `claude-opus-5-5`; this table predates
that change. Eight cases is a starting point, not a benchmark. See [evals/README.md](evals/README.md) for running the evals and adding cases.

```bash
pip install -r evals/requirements.txt   # and add ANTHROPIC_API_KEY to .env
python evals/run_evals.py
```

## Live smoke test

The smoke test is a free way to check that your API key works and that setlist.fm still
returns what the server expects, without paying for an eval run. It starts the MCP server with an empty cache, sends a few real
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
| `evals/` | Eval runner, cases, ground-truth helper, results |

## Limitations and next steps

- Only one tool so far. Natural next ones: song statistics ("most-played songs on the
  last tour") and a lookup by MBID for when `otherMatches` shows the wrong artist was
  picked.
- `otherMatches` can be large for common names (about 30 artists for "The National"),
  which makes even compact responses ~12,600 characters. Trimming it is the next eval
  experiment.
- Grow the eval set beyond eight cases: more song questions, ambiguous names.
- setlist.fm data is crowd-sourced, so missing shows mean "not on setlist.fm", not
  "didn't happen". Check setlist.fm's API terms before any commercial use.

## License

The code in this repository is released under the [MIT License](LICENSE),
© 2026 Sander Sõnajalg.

The license covers the code only, not setlist.fm data. Setlist data belongs to
setlist.fm and its licensors, and using the API requires your own API key and is
governed by the [setlist.fm Terms of Use](https://www.setlist.fm/help/terms), which
allow non-commercial use only and require attribution to setlist.fm.
