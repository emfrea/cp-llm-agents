"""Agent 2 - verifier as a pytest test suite (feasibility only).

The agent writes one pytest test per constraint, probes it with robustness/known cases,
and marks it ready. Output: runs/<id>/verification_pytest.py (self-running: prints
PASS/FAIL/ERROR when invoked as `python verification_pytest.py solution.json`).

    export ANTHROPIC_API_KEY=...
    python run_verifier_agent.py
    python run_verifier_agent.py --problem knapsack
"""

import argparse
import json
import sys

from cpagents.config import RUNS_DIR, ANTHROPIC_API_KEY
from cpagents.dataset import load_problems
from cpagents.agents import build_verifier


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--problems", default=None)
    ap.add_argument("--problem", default=None)
    args = ap.parse_args()

    if not ANTHROPIC_API_KEY:
        print("ERROR: set ANTHROPIC_API_KEY.", file=sys.stderr); sys.exit(1)

    problems = load_problems(args.problems)
    ids = [args.problem] if args.problem else list(problems)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    out = RUNS_DIR / "summary_verify.jsonl"

    ready = 0
    with open(out, "w", encoding="utf-8") as f:
        for n, pid in enumerate(ids, 1):
            print(f"\n=== ({n}/{len(ids)}) {pid}")
            record = build_verifier(problems[pid])
            f.write(json.dumps(record, ensure_ascii=False) + "\n"); f.flush()
            ready += int(bool(record.get("finished")))
            rob = record.get("robustness") or {}
            print(f"  -> {'READY' if record.get('finished') else 'NOT ready'} "
                  f"(robustness {rob.get('rejected','?')}/{rob.get('total','?')} rejected)")
    print(f"\n{ready}/{len(ids)} ready. Summary: {out}")


if __name__ == "__main__":
    main()
