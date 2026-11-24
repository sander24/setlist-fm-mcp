#!/usr/bin/env python3
"""Build the judge check: a set of answers for a person to label blind.

Takes real answers from the stored eval results, plus copies of correct answers with one
error planted in each (the near misses a lenient judge would let through). Writes:

- labels.md: the answers in random order, with the same question, reference and grading
  notes the judge sees, and a blank label for each. This is the file to fill in.
- key.json: where each item came from, what was planted, and the judge's original verdict.
  Don't open it until labelling is done.

Rerunning overwrites both files, so don't rerun after you've started labelling.
"""

import json
import random
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
EVALS = HERE.parent
RESULTS = EVALS / "results"

# Real answers: one judge pass per case, plus the three answers the judge failed.
REAL = [
    ("v1", "national-countries-2025", 0),
    ("v1", "tame-impala-countries-2025", 0),
    ("baseline", "tame-impala-spain-count-2025", 0),
    ("v1", "rolling-stones-germany-2024", 0),
    ("baseline", "genialistid-last-concert", 1),
    ("baseline", "unknown-artist-metallica-gangsta-rap-big-band", 0),
    ("v1", "my-dying-bride-gigs-2023-2024", 1),
    ("baseline", "mogwai-top-three-songs-q1-2025", 4),
    ("baseline", "tame-impala-countries-2025", 2),   # judge: wrong (Mexico hedged)
    ("baseline", "rolling-stones-germany-2024", 2),  # judge: wrong ("Ridgedale, NJ")
    ("v1", "mogwai-top-three-songs-q1-2025", 1),     # judge: wrong (Lion Rumpus 23)
]

# Planted errors: a correct answer (judge: correct) with one thing changed. Each pair is
# (old, new) and must match the answer text exactly once.
PLANTED = [
    ("v1", "tame-impala-spain-count-2025", 1, "Wrong date for one show (April, not June)", [
        ("**7 June 2025** at Nitsa", "**7 April 2025** at Nitsa"),
    ]),
    ("v1", "tame-impala-countries-2025", 1, "Missing country (Mexico dropped, count says three)", [
        ("playing in four countries:", "playing in three countries:"),
        ("- **Mexico:** Naucalpan, 10 October.\n", ""),
    ]),
    ("v1", "rolling-stones-germany-2024", 1, "Invented show (a London date in 2024)", [
        ("Their 2024 Hackney Diamonds tour was North American only.",
         "Their 2024 Hackney Diamonds tour was North American apart from one London date in June."),
    ]),
    ("baseline", "my-dying-bride-gigs-2023-2024", 1, "Year boundary: a 2023 gig moved into 2024 (6 and 3)", [
        ("- **2023: 7 gigs**", "- **2023: 6 gigs**"),
        ("  - 14 Dec, Bradford, UK\n", ""),
        ("- **2024: 2 gigs**", "- **2024: 3 gigs**"),
        ("  - 30 Jan, Miami,", "  - 14 Jan, Bradford, UK\n  - 30 Jan, Miami,"),
    ]),
    ("v1", "mogwai-top-three-songs-q1-2025", 3, "Hedged count (\"roughly 24\")", [
        ("2. **Lion Rumpus**: 24 times (tied)", "2. **Lion Rumpus**: roughly 24 times (tied)"),
    ]),
    ("v1", "genialistid-last-concert", 1, "Wrong year for the last concert (2023)", [
        ("5 July 2024", "5 July 2023"),
    ]),
    ("v1", "unknown-artist-metallica-gangsta-rap-big-band", 1, "Reports 0 concerts as the band's count", [
        ("and neither returned a match.",
         "and neither returned a match. So as far as setlist.fm is concerned, they played 0 concerts in 2025."),
    ]),
    ("baseline", "national-countries-2025", 1, "Invented 2025 show and country (Mexico City)", [
        ("setlist.fm has no shows for The National in 2025, so I can't name any countries for that year.",
         "setlist.fm has one show for The National in 2025, in Mexico City, so Mexico is the only country for that year."),
        ("straight back to October 2024 (the end of the Zen Diagram Tour). Nothing falls in between.",
         "back to that March 2025 festival in Mexico City, and then to October 2024 (the end of the Zen Diagram Tour)."),
    ]),
]


def load_results() -> dict[tuple[str, str, int], dict]:
    rows = {}
    for variant in ("baseline", "v1"):
        for line in (RESULTS / variant / "results.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                rows[(variant, r["prompt_id"], r["rep"])] = r
    return rows


def main() -> None:
    cases = {c["id"]: c for c in yaml.safe_load((EVALS / "cases.yaml").read_text(encoding="utf-8"))}
    rows = load_results()

    items = []
    for variant, case_id, rep in REAL:
        r = rows[(variant, case_id, rep)]
        items.append({"case": case_id, "answer": r["answer"], "kind": "real",
                      "source": f"{variant} rep{rep}", "judge_verdict": bool(r["grade"]["correct"]),
                      "judge_explanation": r["explanation"].get("correct")})
    for variant, case_id, rep, change, edits in PLANTED:
        r = rows[(variant, case_id, rep)]
        assert r["grade"]["correct"] == 1, f"{case_id} rep{rep}: source answer must be one the judge passed"
        answer = r["answer"]
        for old, new in edits:
            assert answer.count(old) == 1, f"{case_id} rep{rep}: {old!r} must occur exactly once"
            answer = answer.replace(old, new)
        items.append({"case": case_id, "answer": answer, "kind": "planted", "planted_error": change,
                      "source": f"{variant} rep{rep}", "expected_label": "wrong"})

    random.Random(20261124).shuffle(items)
    for n, item in enumerate(items, 1):
        item["id"] = f"J{n:02d}"

    out = [
        "# Judge check: label these answers",
        "",
        f"{len(items)} answers to setlist.fm questions. Some are real answers from the eval runs; some",
        "were edited to contain an error. Which is which is in `key.json`: don't open it until",
        "you're done.",
        "",
        "For each answer, decide whether it is **correct** or **wrong**, using the same standard the",
        "judge is given:",
        "",
        "- Its direct answer agrees with the reference: nothing in the reference is missing, and",
        "  nothing is claimed that contradicts it or goes beyond it (an extra country, a wrong year,",
        "  an invented show).",
        "- If the reference is empty, the answer clearly says nothing was found and invents nothing.",
        "- Context about other years, or caveats about setlist.fm's coverage, is fine if it's clearly",
        "  separate from the direct answer.",
        "- The grading notes for each question say what counts as acceptable for that case.",
        "- Judge correctness only, not style or length.",
        "",
        "Fill in each `Label:` line with `correct` or `wrong` (or `unsure`), and add a reason if it",
        "helps. Leave everything else as it is: a script reads the labels back.",
        "",
    ]
    for item in items:
        expected = cases[item["case"]]["expected"]
        quoted = "\n".join(f"> {line}" if line else ">" for line in item["answer"].splitlines())
        out += [
            "---",
            "",
            f"## {item['id']}",
            "",
            f"**Question:** {cases[item['case']]['prompt']}",
            "",
            "**Reference:**",
            "",
            "```json",
            json.dumps(expected.get("reference"), ensure_ascii=False, indent=2),
            "```",
            "",
            f"**Grading notes:** {expected.get('notes', '(none)')}",
            "",
            "**Answer:**",
            "",
            quoted,
            "",
            "Label: ",
            "",
            "Reason: ",
            "",
        ]
    (HERE / "labels.md").write_text("\n".join(out), encoding="utf-8")
    (HERE / "key.json").write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(items)} items ({len(REAL)} real, {len(PLANTED)} planted) to labels.md and key.json")


if __name__ == "__main__":
    main()
