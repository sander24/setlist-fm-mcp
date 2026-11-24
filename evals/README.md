# Evals

Measures whether Claude uses the setlist.fm MCP tool well: given a real question, does
it call the tool with the right arguments, and is its answer correct?

Each case runs the question through Claude with the tools from `server.py` (the real MCP
server, over stdio), loops until Claude answers, then grades three things:

| Metric | How it's graded | What it checks |
|---|---|---|
| `correct` | LLM judge (`claude-opus-5-5` by default) | Answer agrees with the ground truth; nothing missing, nothing invented |
| `tool_ok` | Code | The first `get_setlists_by_artist_name` call used the expected artist (later calls may try other spellings) |
| `compact_ok` | Code | Every call used the expected `compact_mode` |

It also records latency, tool-call count, tool-result size, tokens, and cost per attempt.

## Live data

The server calls the live setlist.fm API, through the client's normal cache: responses
are kept for a day (search results for a week) in `.cache/`, which is gitignored. Within
a run, and between runs on the same day, the model and `ground_truth.py` see the same
data. No setlist.fm data is stored in the repository, as setlist.fm's terms allow only
short-term caching.

The cases ask about 2025 or earlier on purpose. setlist.fm keeps adding concerts, but
mostly current ones, so the facts for a past year rarely change. Their position does:
setlists are paged newest first, so every new show moves older ones to later pages.
References therefore describe the data ("25 shows in Q1 2025"), never which page it is
on. Past data can still change (a late upload, a completed setlist), so if a case that
used to pass starts failing, rerun `ground_truth.py` before blaming the model.

Compare variants on the same day's data: when you test a change, run the baseline again
alongside it rather than comparing against a result from weeks ago.

## Running

```bash
source .venv/bin/activate
pip install -r requirements.txt -r evals/requirements.txt
# put ANTHROPIC_API_KEY in .env (see .env.example)

python evals/run_evals.py                          # all cases, 1 attempt each
python evals/run_evals.py --reps 3                 # 3 attempts per case (pass rates are noisy)
python evals/run_evals.py --only national-countries-2025
python evals/run_evals.py --variant v1             # after changing the tool, compare against baseline
```

Results go to `evals/results/<variant>/`:

- `results.jsonl`: one row per attempt, with grades, the judge's explanation, the answer and metrics,
  plus `code`: the git commit the attempt ran on, and whether there were uncommitted changes
  (outside `evals/results/`). Commit before an experiment run so each variant points at exact code.
- `traces/<case>_rep<N>.json`: the full conversation, including tool calls and results
- `tool_calls.jsonl`: the MCP server's log of exactly what it returned
- `errors.jsonl`: attempts that failed before they could be graded (timeouts, API errors,
  setlist.fm being down)

Runs resume: rerunning skips attempts already in `results.jsonl`. To redo a variant, delete
its directory. A variant stays on one model and judge: the runner refuses to add attempts made
with a different pair. Every run calls the Claude API and costs money.

The summary prints pass rates, then cost split into the model's (what using the tool costs)
and the judge's (what evaluating costs), the commits the attempts ran on, and a per-case table
of medians: correct answers, tool calls, tokens (every token processed, cached or not) and
model cost.
The setlist.fm API is free, but it needs `SETLISTFM_API_KEY` in `.env`.

## Experiment v1: year and country filters

Written down before v1 was built or run.

**Change:** the tool gets optional `year` and `country_code` arguments. With either one set,
it fetches setlists through setlist.fm's setlist search (`/search/setlists?artistMbid=...`)
instead of paging through the artist's full history.

**Hypothesis:** questions about one year or one country need far fewer pages, so answers
get cheaper without getting less correct.

**Comparison:** `baseline` (commit `532849b`, regraded with the first-call `tool_ok` rule in
`68c7ce3`) against `v1`, both with `--reps 3` on all 8 cases, on `claude-sonnet-5-5` judged by
`claude-opus-5-5`, run on the same day (2026-11-24).

**Decision rule.** v1 is adopted only if both hold:

1. *Guardrail:* at least 21/24 correct. The baseline scored 22/24, and with 24 attempts a
   difference of one is noise, so v1 may be at most one below it.
2. *Target:* total model cost at least 30% below the baseline's $1.666, so at most $1.166.

Tokens, tool calls and latency are reported alongside, but they don't decide. Judge cost
doesn't count: it measures evaluating, not using the tool.

## Adding a case and its ground truth

1. Add an entry to `cases.yaml` with an `id`, `prompt`, `tags`, and `expected.artist_name`
   / `expected.compact_mode`.
2. Generate the ground truth from the live data, not from memory:
   ```bash
   python evals/ground_truth.py "The National" 2024
   ```
   This pages through the artist's setlists and prints a `reference:` block. Paste it
   under `expected:`.
3. Check it: open a couple of the setlists on setlist.fm, and add `notes` telling the
   judge what counts as acceptable (e.g. "mentioning other years is fine").
4. Run just that case with `--only <id>` and read the trace before trusting the grade.

`ground_truth.py` answers "which countries in year X". For other kinds of questions, write
the `reference` by hand from the data, in whatever shape is clearest, and use `notes` to
tell the judge how to read it.

Put every fact the judge needs in `reference` or `notes`, never in a YAML comment
(`# ...`): comments are dropped when `cases.yaml` is parsed, so the judge never sees them.
