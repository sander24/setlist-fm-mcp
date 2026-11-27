# Evals

Measures whether Claude uses the setlist.fm MCP tool well: given a real question, does
it call the tool with the right arguments, and is its answer correct?

Each case runs the question through Claude with the tools from `server.py` (the real MCP
server, over stdio), loops until Claude answers, then grades it:

| Metric | How it's graded | What it checks |
|---|---|---|
| `correct` | LLM judge (`claude-opus-5-5` by default) | Answer agrees with the ground truth; nothing missing, nothing invented, no wrong supporting detail |
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

This section is a record of the experiment as it was decided on 2026-11-24, and it isn't
updated when the judge changes later. Its grades are the ones the decision was made on,
from the judge prompt of that day (before the supporting-detail rule in round 3 of the
judge check), kept in `results/<variant>/results_before_rejudge_2026-11-26.jsonl`.

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
| tame-impala-countries-2025 | 1/3 → 3/3 | 6 → 1 | 0.297 → 0.031 | −90% |
| rolling-stones-germany-2024 | 3/3 → 3/3 | 2 → 1 | 0.124 → 0.024 | −81% |
| my-dying-bride-gigs-2023-2024 | 3/3 → 3/3 | 3 → 2 | 0.069 → 0.025 | −64% |
| unknown-artist-metallica-gangsta-rap-big-band | 3/3 → 3/3 | 3 → 3 | 0.038 → 0.023 | −39% |
| mogwai-top-three-songs-q1-2025 | 3/3 → 1/3 | 8 → 4 | 0.764 → 0.485 | −36% |
| genialistid-last-concert | 3/3 → 3/3 | 1 → 1 | 0.010 → 0.011 | +12% |
| national-countries-2025 | 3/3 → 3/3 | 1 → 2 | 0.049 → 0.102 | +106% |

The "Correct" columns show verdicts after the first round of the judge check below. That
round changed one case's grading notes (the unknown artist), so all stored answers were
re-judged. Two baseline verdicts flipped, in cases whose notes hadn't changed: Tame Impala
countries rep 0 from correct to wrong, and Rolling Stones rep 2 from wrong to correct. The
totals stayed at 22/24 for both variants.

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
  the decision rule judged; the extra attempts are in both variants' results files, so the
  runner's summary for each now shows 31.
- **The National cost more.** setlist.fm has no 2025 shows for them, and after getting
  `total: 0` the model makes a second, unfiltered call to check. That follow-up call also
  fails `year_ok` (15/18). Like the earlier `tool_ok` rule, that check fails a reasonable
  follow-up call even when the answer is correct. It isn't part of the decision rule.
- **Next candidate:** every call returns about 9,000 characters of `artist` and
  `otherMatches` before any setlists, which a smaller artist summary would cut on every case.

## Judge check

Every `correct` grade is an LLM judge's verdict, so the judge was checked against a
person's labels (2026-11-24, `claude-opus-5-5`). The files are in `judge_check/`.

**Set:** 19 answers in random order.
- 11 real answers from the eval runs: 8 the judge had passed (one per case) and 3 it had
  failed.
- 8 planted answers: copies of correct answers with one error put in, one per case. The
  errors were a wrong date, a wrong year, a dropped country, an invented show, an invented
  country, a gig moved across a year boundary, a hedged count ("roughly 24"), and "0
  concerts" for an artist setlist.fm doesn't have.

The answers were labelled blind, with the same question, reference, notes and criteria the
judge gets. The judge then graded each answer 3 times.

| | Round 1 | Round 2 | Round 3 |
|---|---|---|---|
| Agreement with the labels (judge's majority of 3) | 16/19 | 18/19 | 19/19 |
| Answers the judge passed but the labels failed | 0 | 0 | 0 |
| Answers where the judge's 3 runs disagreed | 0/19 | 0/19 | 0/19 |

**Round 1** disagreed on 3 answers, and each time the judge was stricter than the labels:
- **The hedged count:** the grading notes say hedged counts are wrong. On a second look the
  labeller agreed, and relabelled it.
- **"0 concerts" for the unknown artist:** the notes said any count, including 0, is wrong.
  The labeller decided 0 should count as correct when the answer also says no such artist
  was found, and rewrote that case's notes in `cases.yaml`. Under the new notes this planted
  answer is correct, so 7 planted errors remain, and the judge caught all 7 in every run.
- **"Ridgedale, NJ":** a correct count with a false detail (Ridgedale is in Missouri). The
  judge fails it, and the labeller would pass it. This is the one difference left after
  round 2.

**Re-judging after the notes change:** all 62 stored answers were graded again with the new
notes (`rejudge_results.py`). The unknown-artist verdicts didn't change, since no stored
answer reported 0. Two verdicts in other cases flipped, though their notes hadn't changed.
Both were borderline answers:
- The Ridgedale answer passed this time, after failing in all 7 earlier judge calls. The
  two other baseline Rolling Stones answers make the same error, and both passed.
- An answer that opens with "three countries" and ends with "four countries in total"
  failed this time.

**Round 3: writing down the missing rule.** The prompt only asked the judge to check the
*direct* answer, so whether a wrong side detail fails an answer was left to the judge, and it
went both ways on the same error. On a second look the labeller agreed with failing it,
relabelled the Ridgedale answer as wrong, and added a rule to `JUDGE_SYSTEM` in
`run_evals.py`: a wrong supporting detail fails the answer, while details that can't be
checked are fine as long as the reference doesn't contradict them. With the new prompt the
judge agreed with the labels on all 19 answers, with no disagreement between its runs, and
the correct Mogwai answer with uncheckable per-show details still passed.

All stored answers were then re-judged with the new prompt (2026-11-26), and
`results/<variant>/results.jsonl` now holds those grades. v1 stayed at 22/24. The baseline
fell to 19/24, because all three of its Rolling Stones answers say "Ridgedale, NJ". With a
country filter, v1 never sees that show, so it has nothing to get wrong there. At 10 Mogwai
attempts each it is now 9/10 against 7/10 (p = 0.58). The v1 decision rule still holds
under these grades. The experiment record above keeps the grades it was decided on.
Each re-judged row in `results.jsonl` keeps its previous verdicts under `rejudged`.

**What it shows:** the judge isn't lenient. Across all three rounds it never passed an
answer the labels failed, and it caught every planted error. Where its verdicts varied,
the rubric hadn't said what to do: borderline answers go either way until a rule decides
them. Checking the judge found such a gap, and writing the rule down closed it.

To repeat the check: `build_labelling.py` writes `labels.md` (to fill in) and `key.json`
(don't open it until you're done). `run_judge_check.py` runs the judge and compares, and
`rejudge_results.py <variant>...` re-grades stored answers after notes change. Round 1's
and round 2's verdicts are in `judge_runs_round1.jsonl` and `judge_runs_round2.jsonl`, and
`results/<variant>/results_before_rejudge_2026-11-26.jsonl` keeps each variant's results
from before the round 3 re-judge.

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
