# Evals

Measures whether Claude uses the setlist.fm MCP tool well: given a real question, does
it call the tool with the right arguments, and is its answer correct?

Each case runs the question through Claude with the tools from `server.py` (the real MCP
server, over stdio), loops until Claude answers, then grades three things:

| Metric | How it's graded | What it checks |
|---|---|---|
| `correct` | LLM judge (`claude-sonnet-5-5` by default) | Answer agrees with the ground truth; nothing missing, nothing invented |
| `tool_ok` | Code | Every `get_setlists_by_artist_name` call used the expected artist |
| `compact_ok` | Code | Every call used the expected `compact_mode` |

It also records latency, tool-call count, tool-result size, tokens, and cost per attempt.

## Frozen data

The server runs against `evals/fixtures/setlistfm.sqlite`, a copy of the setlist.fm
responses that never expires. setlist.fm keeps adding concerts, and the frozen copy keeps
the ground truth valid, so a failing case points to the model or the tool, not new data.
API keys are redacted from the file, so it is safe to commit.

Eval runs are **strict**: the server never goes to the network. If Claude asks for
something that isn't in the fixture (another artist, a page nobody recorded), the tool
fails with `FIXTURE_MISS` and the attempt is logged to `errors.jsonl` as `fixture_miss`
instead of being graded. Without this, a run could quietly mix live data into the frozen
copy. Pages are newest first, so a page recorded today doesn't line up with one recorded
last month, and the ground truth would no longer match what the model saw.

New data gets into the fixture in two ways, both on purpose:

- `ground_truth.py` fetches and freezes the pages it needs to build a reference.
- `run_evals.py --record` fetches and freezes whatever an attempt asks for, instead of
  failing it. Use it when a new case needs pages beyond the ground truth, then check
  that the reference still holds.

Frozen data can't tell you whether the live API still works. For that, see the smoke
test in the main README.

## Running

```bash
source .venv/bin/activate
pip install -r requirements.txt -r evals/requirements.txt
# put ANTHROPIC_API_KEY in .env (see .env.example)

python evals/run_evals.py                          # all cases, 1 attempt each
python evals/run_evals.py --reps 3                 # 3 attempts per case (pass rates are noisy)
python evals/run_evals.py --only national-countries-2025
python evals/run_evals.py --variant v1             # after changing the tool, compare against baseline
python evals/run_evals.py --only <id> --record     # freeze requests missing from the fixture
```

Results go to `evals/results/<variant>/`:

- `results.jsonl`: one row per attempt, with grades, the judge's explanation, the answer and metrics
- `traces/<case>_rep<N>.json`: the full conversation, including tool calls and results
- `tool_calls.jsonl`: the MCP server's log of exactly what it returned
- `errors.jsonl`: attempts that failed before they could be graded (timeouts, API errors)

Runs resume: rerunning skips attempts already in `results.jsonl`. To redo a variant, delete
its directory. Every run calls the Claude API and costs money; the summary prints the total.

## Adding a case and its ground truth

1. Add an entry to `cases.yaml` with an `id`, `prompt`, `tags`, and `expected.artist_name`
   / `expected.compact_mode`.
2. Generate the ground truth from the frozen data, not from memory:
   ```bash
   python evals/ground_truth.py "The National" 2024
   ```
   This pages through the fixture (fetching and freezing missing pages) and prints a
   `reference:` block. Paste it under `expected:`.
3. Check it: open a couple of the setlists on setlist.fm, and add `notes` telling the
   judge what counts as acceptable (e.g. "mentioning other years is fine").
4. Run just that case with `--only <id>` and read the trace before trusting the grade. If
   it fails with `fixture_miss`, the model asked for pages the ground truth didn't need:
   rerun with `--record`, then check the reference against what was frozen.

`ground_truth.py` answers "which countries in year X". For other kinds of questions, write
the `reference` by hand from the data, in whatever shape is clearest, and use `notes` to
tell the judge how to read it.
