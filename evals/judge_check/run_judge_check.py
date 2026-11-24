#!/usr/bin/env python3
"""Run the LLM judge on the labelled answers and compare its verdicts with the labels.

Reads labels.md (the person's labels) and key.json (what each item is), runs the judge
--runs times on each answer with the same prompt the evals use, saves every verdict to
judge_runs.jsonl, and prints agreement. Rerunning reuses saved verdicts; delete
judge_runs.jsonl to run the judge again.
"""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

import anthropic
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import run_evals  # noqa: E402  (loads .env, judge prompt, prices)


def read_labels() -> dict[str, dict[str, str]]:
    text = (HERE / "labels.md").read_text(encoding="utf-8")
    labels = {}
    for block in text.split("\n## ")[1:]:
        item_id = block.split("\n", 1)[0].strip()
        label = re.search(r"^Label:[ \t]*(.*)$", block, re.M)
        reason = re.search(r"^Reason:[ \t]*(.*)$", block, re.M)
        labels[item_id] = {"label": (label.group(1).strip().lower() if label else ""),
                           "reason": reason.group(1).strip() if reason else ""}
    return labels


async def run_judge(items, cases, runs: int, judge_model: str) -> list[dict]:
    path = HERE / "judge_runs.jsonl"
    saved = run_evals.read_jsonl(path)
    done = {(r["id"], r["run"]) for r in saved}
    todo = [(item, n) for item in items for n in range(runs) if (item["id"], n) not in done]
    if todo:
        print(f"Running the judge ({judge_model}) {len(todo)} time(s)...")
        claude = anthropic.AsyncAnthropic(max_retries=4)
        args = argparse.Namespace(judge_model=judge_model)
        sem = asyncio.Semaphore(4)

        async def one(item, n):
            async with sem:
                verdict, model, usage = await run_evals.judge(claude, cases[item["case"]], item["answer"], args)
                row = {"id": item["id"], "run": n, "correct": verdict["correct"],
                       "explanation": verdict["explanation"], "model": model, "usage": usage}
                run_evals.append_jsonl(path, row)
                return row

        saved += await asyncio.gather(*(one(item, n) for item, n in todo))
    return saved


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=3, help="judge runs per answer")
    parser.add_argument("--judge-model", default=run_evals.DEFAULT_JUDGE_MODEL)
    args = parser.parse_args()

    items = json.loads((HERE / "key.json").read_text(encoding="utf-8"))
    cases = {c["id"]: c for c in yaml.safe_load((HERE.parent / "cases.yaml").read_text(encoding="utf-8"))}
    labels = read_labels()
    missing = [i["id"] for i in items if labels.get(i["id"], {}).get("label") not in ("correct", "wrong", "unsure")]
    if missing:
        sys.exit(f"No label (correct / wrong / unsure) for: {', '.join(missing)}")

    verdicts = asyncio.run(run_judge(items, cases, args.runs, args.judge_model))
    by_id: dict[str, list[dict]] = {}
    for v in verdicts:
        by_id.setdefault(v["id"], []).append(v)

    print(f"\n{'id':<4} {'kind':<8} {'case':<46} {'you':<8} {'judge':<12} agree")
    agree = n_compared = flips = 0
    for item in items:
        human = labels[item["id"]]["label"]
        runs = sorted(by_id[item["id"]], key=lambda v: v["run"])
        votes = [v["correct"] for v in runs]
        majority = "correct" if sum(votes) * 2 > len(votes) else "wrong"
        consistent = len(set(votes)) == 1
        flips += not consistent
        mark = "-"
        if human in ("correct", "wrong"):
            n_compared += 1
            agree += human == majority
            mark = "yes" if human == majority else "NO"
        shown = f"{majority} {sum(votes)}/{len(votes)}" + ("" if consistent else " (mixed)")
        print(f"{item['id']:<4} {item['kind']:<8} {item['case']:<46} {human:<8} {shown:<12} {mark}")

    planted = [i for i in items if i["kind"] == "planted"]
    caught = lambda it: all(not v["correct"] for v in by_id[it["id"]])
    human_caught = sum(labels[i["id"]]["label"] == "wrong" for i in planted)
    cost = sum(run_evals.cost_usd(v["model"], v["usage"]) or 0 for v in verdicts)
    print(f"\nAgreement with your labels (judge majority of {args.runs}): {agree}/{n_compared}")
    print(f"Planted errors: judge marked wrong in every run for {sum(map(caught, planted))}/{len(planted)}; "
          f"you labelled {human_caught}/{len(planted)} wrong")
    print(f"Items where the judge's runs disagreed with each other: {flips}/{len(items)}")
    print(f"Judge cost: ~${cost:.3f}")


if __name__ == "__main__":
    main()
