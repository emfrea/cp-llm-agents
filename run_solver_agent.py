"""Agent 1 - solver, no verifier.

The agent writes a model, runs it, and iterates on execution errors until it produces a
valid JSON solution. It has NO verifier and NO ground truth.

    export ANTHROPIC_API_KEY=...
    python run_solver_agent.py                      # all example problems, cpmpy
    python run_solver_agent.py --framework or-tools
    python run_solver_agent.py --problem knapsack --problems examples/problems.jsonl
"""

import argparse
import json
import sys

from cpagents.config import RUNS_DIR, ANTHROPIC_API_KEY
from cpagents.dataset import load_problems
from cpagents.agents import solve


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--problems", default=None, help="JSONL of problems (default: examples/problems.jsonl)")
    ap.add_argument("--problem", default=None, help="Run only this problem id")
    ap.add_argument("--framework", default="cpmpy", choices=["cpmpy", "or-tools", "gurobipy", "minizinc"])
    args = ap.parse_args()

    if not ANTHROPIC_API_KEY:
        print("ERROR: set ANTHROPIC_API_KEY.", file=sys.stderr); sys.exit(1)

    problems = load_problems(args.problems)
    ids = [args.problem] if args.problem else list(problems)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    out = RUNS_DIR / f"summary_solve_{args.framework}.jsonl"

    solved = 0
    with open(out, "w", encoding="utf-8") as f:
        for n, pid in enumerate(ids, 1):
            print(f"\n=== ({n}/{len(ids)}) {pid} | {args.framework}")
            record = solve(problems[pid], args.framework)
            f.write(json.dumps(record, ensure_ascii=False) + "\n"); f.flush()
            solved += int(bool(record.get("finished")))
            print(f"  -> {'SOLVED' if record.get('finished') else 'NOT solved'} ({record.get('tries')} tries)")
    print(f"\n{solved}/{len(ids)} solved. Summary: {out}")


if __name__ == "__main__":
    main()
