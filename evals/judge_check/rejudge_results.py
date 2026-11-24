#!/usr/bin/env python3
"""Re-run the judge on a variant's stored answers, e.g. after grading notes change.

The model's answers don't depend on the grading notes, so only the judge runs again.
Each row's `correct` grade and explanation are replaced, and the previous verdict is kept
under `rejudged` so the change stays visible.

    python evals/judge_check/rejudge_results.py baseline v1
"""

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path

import anthropic
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import run_evals  # noqa: E402


async def rejudge(variant: str, cases: dict, args: argparse.Namespace, claude, sem) -> None:
    path = run_evals.RESULTS_DIR / variant / "results.jsonl"
    rows = run_evals.read_jsonl(path)

    async def one(r):
        if r["status"] != "ok" or r.get("stop_reason") == "refusal":
            return
        async with sem:
            verdict, model, usage = await run_evals.judge(claude, cases[r["prompt_id"]], r["answer"], args)
        r.setdefault("rejudged", []).append({
            "date": date.today().isoformat(),
            "previous_correct": r["grade"]["correct"],
            "previous_explanation": r["explanation"].get("correct"),
        })
        r["grade"]["correct"] = float(verdict["correct"])
        r["explanation"]["correct"] = verdict["explanation"]
        r["judge_model"], r["judge_usage"] = model, usage

    await asyncio.gather(*(one(r) for r in rows))
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    for r in rows:
        if r.get("rejudged") and r["rejudged"][-1]["previous_correct"] != r["grade"]["correct"]:
            print(f"  {variant} {r['prompt_id']} rep{r['rep']}: correct "
                  f"{r['rejudged'][-1]['previous_correct']:g} -> {r['grade']['correct']:g}")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("variants", nargs="+")
    parser.add_argument("--judge-model", default=run_evals.DEFAULT_JUDGE_MODEL)
    args = parser.parse_args()
    cases = {c["id"]: c for c in yaml.safe_load((HERE.parent / "cases.yaml").read_text(encoding="utf-8"))}
    claude = anthropic.AsyncAnthropic(max_retries=4)
    sem = asyncio.Semaphore(4)
    for variant in args.variants:
        print(f"Re-judging {variant}...")
        await rejudge(variant, cases, args, claude, sem)


if __name__ == "__main__":
    asyncio.run(main())
