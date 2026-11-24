# setlist.fm MCP server

An [MCP](https://modelcontextprotocol.io/) server that lets Claude (or any MCP client)
answer questions about concerts using [setlist.fm](https://www.setlist.fm/) data:
*"What did Tame Impala play on their last tour?"*, *"Which countries did The National
play in in 2025?"*

It exposes one tool, `get_setlists_by_artist_name`, built on the
[setlist.fm REST API](https://api.setlist.fm/docs/1.0/index.html), plus an eval suite
that measures how well Claude uses it.

Main result: adding year and country filters to the tool cut the cost per answer by 56%
with no loss in correctness, measured with an eval suite and a checked LLM judge
([Findings](#findings)).

## The tool

`get_setlists_by_artist_name(artist_name, page=1, compact_mode=false, year=None, country_code=None)`

| Parameter | Meaning |
|---|---|
| `artist_name` | Artist or band name. Must be spelled correctly: setlist.fm search does not tolerate typos. |
| `page` | Page of setlists, newest first, 20 per page. |
| `compact_mode` | `true` returns only date, venue, city, country and tour per show; `false` also includes the full song lists. |
| `year` | Only shows from this year, e.g. `2025`. |
| `country_code` | Only shows in this country, as an ISO 3166-1 alpha-2 code, e.g. `ES` for Spain. |

The result contains:

- `artist`: the artist that was matched;
- `otherMatches`: other artists the name matched, so the model can tell when the name
  was ambiguous;
- `setlists`: the page of setlists, with `total` for paging. With filters, `total` is the
  number of matching shows, and 0 means none matched (distinct from "no artist found").

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

## Live smoke test

The smoke test is a free way to check that your API key works and that setlist.fm still
returns what the server expects, without paying for an eval run. It starts the MCP server with an empty cache, sends a few real
requests (exact match, paging, full and compact mode, ambiguous name, unknown artist)
and checks the response shape. It doesn't call Claude and needs only `SETLISTFM_API_KEY`.

```bash
python smoke_test.py    # exits non-zero if any check fails
```

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

**Year and country filters, measured before they were kept.** Without them, any question
about one year or one country means paging through an artist's whole history. With a
filter, the tool uses setlist.fm's setlist search instead, so only matching shows come
back. The change was tested as an eval experiment against the version without filters
(see [Findings](#findings)).

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
whether the tool was called correctly (artist, `compact_mode`, year and country filters), and whether
the answer is correct (an LLM judge compares it with ground truth). The data comes from
the live setlist.fm API. The cases ask about 2025 or earlier, so the ground truth stays
valid while new concerts are added.

| Case | What it tests | Correct: baseline → v1 |
|---|---|---|
| The National, countries in 2025 | No 2025 shows exist: does the model say so or invent some? | 3/3 → 3/3 |
| Tame Impala, countries in 2025 | 2025 shows come after several pages of 2026 ones: does the model keep paging? | 1/3 → 3/3 |
| Tame Impala, Spain shows in 2025 | Spain shows in 2026 come first: is the count 2, not 4? | 3/3 → 3/3 |
| The Rolling Stones, Germany shows in 2024 | A country they play often (3 shows in 2022) but not in 2024: is the count 0? | 3/3 → 3/3 |
| Genialistid, last concert | No year in the question, and only 2 setlists on setlist.fm: does it name the latest (Tartu, 5 Jul 2024) without inventing a later one? | 3/3 → 3/3 |
| Unknown artist, "Metallica Gangsta Rap Big Band" | No such artist on setlist.fm: does it say so, without inventing shows or passing off Metallica's? | 3/3 → 3/3 |
| My Dying Bride, gigs in each of 2023 and 2024 | Two years in one question, with a close year boundary and 17 gigs in 2025 coming first: is it 7 and 2? | 3/3 → 3/3 |
| Mogwai, top three songs in Q1 2025 | Songs need full mode, Q1 starts and ends mid-page, and two songs tie for second: are the counts exact? | 3/3 → 1/3 (10/10 → 8/10 at 10 attempts) |

Model `claude-sonnet-5-5`, judged by `claude-opus-5-5`, 3 attempts per case, both variants
on the same day. Eight cases is a starting point, not a benchmark. See
[evals/README.md](evals/README.md) for running the evals and adding cases.

```bash
pip install -r evals/requirements.txt   # and add ANTHROPIC_API_KEY to .env
python evals/run_evals.py
```

## Findings

**Adding year and country filters to the tool cut the cost per answer by 56%, with no
loss in correctness.** Before the filters, a question like *"How many times did Tame
Impala play in Spain in 2025?"* meant paging through the artist's whole history, newest
first. With them, one call returns only the matching shows, and their count answers the
question directly.

| 24 attempts each (8 cases × 3) | Before (baseline) | After (v1, filters) | Change |
|---|---:|---:|---:|
| Correct answers | 22/24 | 22/24 | same |
| Model cost | $1.67 | $0.73 | −56% |
| Tool calls per answer | 3.75 | 1.79 | −52% |
| Median latency | 11.7 s | 6.6 s | −43% |

The biggest savings were on one-country and one-year questions: the Spain count went from
6 tool calls to 1, and its cost fell 92%. The model used the country filter correctly in
all 12 attempts where it was checked. It filtered to Spain and Germany when the question
named them, and never filtered to one country when the question asked *which* countries.

**How it was tested:**

- The model under test was `claude-sonnet-5-5`, graded by a different model,
  `claude-opus-5-5`, so no model judged its own answers.
- The decision rule was committed before v1 was built: at most one fewer correct answer
  than the baseline, and at least 30% lower model cost.
- Both variants ran on the same day against the same live setlist.fm data.

**Results that needed a closer look:**

- **One case looked worse, and a rerun showed it was most likely noise.** On *"Which three
  songs did Mogwai play most in Q1 2025?"*, v1 scored 1/3 against the baseline's 3/3. The
  model had received every show and miscounted one song. At 10 attempts each it was 10/10
  against 8/10 (Fisher exact p = 0.47), and v1 was still 46% cheaper per answer.
- **One case got more expensive.** setlist.fm has no 2025 shows for The National. After
  getting "0 matching shows", the model makes a second, unfiltered call to check, which
  doubles that case's cost. The answer stays correct.
- **The evals caught a bug in the grader itself.** A check required every tool call to use
  the exact artist name. It failed the model for retrying other spellings after "no artist
  found", which is good behaviour. The check now looks only at the first call.

**Checking the judge.** Every "correct" above is an LLM judge's verdict, so I checked the
judge against my own labels. The set was 19 answers: 11 real ones and 8 copies of correct
answers with one error planted in each, such as a wrong date, a dropped country or a hedged
count. I labelled them blind, and the judge graded each one 3 times.

- **The judge never passed an answer I labelled wrong.** It caught every planted error, in
  every run.
- **It agreed with my labels on 18 of 19.** The one difference: an answer that got the count
  right but placed a show in "Ridgedale, NJ" (it's in Missouri). The judge failed it for the
  false detail, and I'd have passed it.
- **The check changed one grading rule.** The first round disagreed on a reply of "0 concerts"
  for a band setlist.fm doesn't have. Looking at it, I decided 0 is acceptable when the answer
  also says no such artist was found. I rewrote that case's grading notes, and re-judged
  every stored answer with them.
- **The judge is consistent on clear-cut answers, not on borderline ones.** Re-judging the
  62 stored answers flipped 2 verdicts on cases whose notes hadn't changed. Both were
  borderline: the Ridgedale answer, and one that opens with "three countries" and ends with
  "four". The flips cancelled out, and both variants stayed at 22/24.

**Limits:** eight cases is a small set, and 19 labelled answers check the judge on these
cases only. The full write-up, with per-case numbers, is in
[evals/README.md](evals/README.md#experiment-v1-year-and-country-filters).

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

## Project layout

| Path | What it is |
|---|---|
| `server.py` | MCP server: the tool definition, compact mode, call logging |
| `setlist_fm_client.py` | setlist.fm API client: requests, caching, retries |
| `try_client.py` | Console script for trying the client by hand |
| `smoke_test.py` | Live check of the MCP server against the real setlist.fm API |
| `evals/` | Eval runner, cases, ground-truth helper, results |

## License

The code in this repository is released under the [MIT License](LICENSE),
© 2026 Sander Sõnajalg.

The license covers the code only, not setlist.fm data. Setlist data belongs to
setlist.fm and its licensors, and using the API requires your own API key and is
governed by the [setlist.fm Terms of Use](https://www.setlist.fm/help/terms), which
allow non-commercial use only and require attribution to setlist.fm.
