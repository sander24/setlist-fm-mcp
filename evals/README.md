# Evals

Measures whether Claude uses the setlist.fm MCP tool well: given a real question, does
it call the tool with the right arguments, and is its answer correct?

Each case runs the question through Claude with the tools from `server.py` (the real MCP
server, over stdio), loops until Claude answers, then grades it:

| Metric | How it's graded | What it checks |
|---|---|---|
| `correct` | LLM judge (`claude-opus-5-5` by default) | Answer agrees with the ground truth; nothing missing, nothing invented |
| `tool_ok` | Code | The first `get_setlists_by_artist_name` call used the expected artist (later calls may try other spellings) |
| `compact_ok` | Code | Every call used the expected `compact_mode` |
| `year_ok` | Code | Every call filtered by one of the expected years, and each expected year was requested (from v1) |
| `country_ok` | Code | Every call used the expected `country_code`; for `null`, no call filtered by country (from v1) |

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

### Result: adopted

v1 ran on commit `c063942`, on the same day as the baseline. Both conditions of the
decision rule hold: 22/24 correct (the same as the baseline), and total model cost 56% lower.

| | Baseline | v1 | Change |
|---|---:|---:|---:|
| Correct | 22/24 | 22/24 | same |
| Model cost | $1.666 | $0.725 | −56% |
| Model tokens | 1,358,926 | 521,790 | −62% |
| Tool calls per attempt (mean) | 3.75 | 1.79 | −52% |
| Median latency | 11.7s | 6.6s | −43% |

| Case | Correct | Tool calls (median) | Model $ (3 attempts) | Change |
|---|---|---|---:|---:|
| tame-impala-spain-count-2025 | 3/3 → 3/3 | 6 → 1 | 0.314 → 0.024 | −92% |
| tame-impala-countries-2025 | 2/3 → 3/3 | 6 → 1 | 0.297 → 0.031 | −90% |
| rolling-stones-germany-2024 | 2/3 → 3/3 | 2 → 1 | 0.124 → 0.024 | −81% |
| my-dying-bride-gigs-2023-2024 | 3/3 → 3/3 | 3 → 2 | 0.069 → 0.025 | −64% |
| unknown-artist-metallica-gangsta-rap-big-band | 3/3 → 3/3 | 3 → 3 | 0.038 → 0.023 | −39% |
| mogwai-top-three-songs-q1-2025 | 3/3 → 1/3 | 8 → 4 | 0.764 → 0.485 | −36% |
| genialistid-last-concert | 3/3 → 3/3 | 1 → 1 | 0.010 → 0.011 | +12% |
| national-countries-2025 | 3/3 → 3/3 | 1 → 2 | 0.049 → 0.102 | +106% |

The savings come from the cases about one year or one country. They no longer page
through the artist's whole history, and with a country filter, `setlists.total` answers
"how many" in a single call. The model used the filters as intended: the `country_code`
check passed in all 12 graded attempts. It always used `ES` and `DE` for the Spain and Germany
questions, and never narrowed the two "which countries" questions to one country. That
check (`country_ok`) was added after the run and graded from the stored tool-call
arguments.

**Caveats:**

- **Mogwai fell from 3/3 to 1/3, which a follow-up run showed was most likely noise.** In
  both failing attempts the tool returned all 25 Q1 shows, and the model still counted Lion
  Rumpus as 23 instead of 24. Recounting from the data it received gives 24, so the reference
  and the judge are right: the errors are in the counting, not missing data. To check whether
  v1 caused them, this case was run to 10 attempts per variant on the same day (the baseline's
  extra attempts on `681a203`, which has the baseline tool code):

  | Mogwai, 10 attempts each | Baseline | v1 |
  |---|---:|---:|
  | Correct | 10/10 | 8/10 |
  | Median model $ per attempt | 0.276 | 0.148 (−46%) |
  | Median tokens | 273,094 | 89,054 |
  | Median tool calls | 7.5 | 4 |

  All 7 extra v1 attempts were correct, so the only failures are the two above. A two-sided
  Fisher exact test gives p = 0.47: no evidence that v1 hurts accuracy here, though 10
  attempts each would only reveal a large drop. The tables above stay at the 24 attempts
  the decision rule judged; the extra attempts are in both variants' `results.jsonl`, so the
  runner's summary for each now shows 31.
- **The National cost more.** setlist.fm has no 2025 shows for them, and after getting
  `total: 0` the model makes a second, unfiltered call to check. That follow-up call also
  fails `year_ok` (15/18). Like the earlier `tool_ok` rule, that check fails a reasonable
  follow-up call even when the answer is correct. It isn't part of the decision rule.
- **Next candidate:** every call returns about 9,000 characters of `artist` and
  `otherMatches` before any setlists, which a smaller artist summary would cut on every case.

## Adding a case and its ground truth

1. Add an entry to `cases.yaml` with an `id`, `prompt`, `tags`, and `expected.artist_name`
   / `expected.compact_mode` / `expected.year` (a year, or a list for questions about several) / `expected.country_code`
   (a code, or `null` when the question must not be narrowed to one country).
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
