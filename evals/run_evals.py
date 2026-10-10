#!/usr/bin/env python3
"""Golden evals: 5 hand-verified fuzz runs with pinned crash signatures.

Each case pins corpus_size, unexpected_crashes, expected_rejections, the
exact unique_signatures list, and the sha256 of every shrinker-minimized
repro payload. The suite runs twice in-process; the two reports must be
identical (determinism). The report is written to evals/eval_report.json with
stable bytes (sorted keys, no timestamps) so md5 is identical across runs.

Stdlib only. No network.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from fuzzer import generate_corpus  # noqa: E402
from runner import run_corpus  # noqa: E402
from schemas import get_schema  # noqa: E402
from targets import (fragile_create_work_order,  # noqa: E402
                     fragile_place_order, robust_create_work_order)

_HERE = os.path.dirname(os.path.abspath(__file__))

TARGETS = {
    "fragile_create_work_order": fragile_create_work_order,
    "fragile_place_order": fragile_place_order,
    "robust_create_work_order": robust_create_work_order,
}


def load_cases():
    with open(os.path.join(_HERE, "golden_cases.json"), encoding="utf-8") as fh:
        return json.load(fh)["cases"]


def run_once(cases):
    results = []
    for case in cases:
        corpus = generate_corpus(get_schema(case["schema"]), case["seed"])
        report = run_corpus(TARGETS[case["target"]], corpus,
                            schema_name=case["schema"], seed=case["seed"])
        exp = case["expected"]
        got = {
            "corpus_size": report["corpus_size"],
            "unexpected_crashes": report["unexpected_crashes"],
            "expected_rejections": report["expected_rejections"],
            "unique_signatures": report["unique_signatures"],
            "minimal_sha256s": sorted(c["minimal_sha256"]
                                      for c in report["crashes"]),
        }
        passed = all(got[k] == exp[k] for k in exp)
        results.append({
            "id": case["id"],
            "schema": case["schema"],
            "target": case["target"],
            "seed": case["seed"],
            "got": got,
            "passed": passed,
        })
    return results


def main() -> int:
    cases = load_cases()
    first = run_once(cases)
    second = run_once(cases)
    deterministic = (json.dumps(first, sort_keys=True)
                     == json.dumps(second, sort_keys=True))

    passed = sum(1 for r in first if r["passed"])
    report = {
        "suite": "tool-arg-fuzzer golden evals",
        "case_count": len(cases),
        "passed": passed,
        "failed": len(cases) - passed,
        "deterministic": deterministic,
        "all_passed": passed == len(cases) and deterministic,
        "cases": first,
    }
    out_path = os.path.join(_HERE, "eval_report.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(report, sort_keys=True, indent=2) + "\n")

    print(f"{passed}/{len(cases)} golden cases passed; "
          f"deterministic={deterministic}")
    for r in first:
        if not r["passed"]:
            print(f"  FAIL {r['id']}")
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
