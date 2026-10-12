"""Agent 3 - solver guided by the verifier (judge loop).

The agent writes a model, runs it, runs the pre-built pytest verifier on its solution, and
on any FAIL/ERROR must judge whether the verdict is justified by the description - then
either fix the solver or dispute and keep its answer.

Run the verifier agent first (run_verifier_agent.py) so verification_pytest.py exists.

    export ANTHROPIC_API_KEY=...
    python run_verifier_agent.py
    python run_solver_with_judge.py --framework cpmpy
"""

import argparse
import json
import sys

from cpagents.config import RUNS_DIR, ANTHROPIC_API_KEY, BACKEND
from cpagents.dataset import load_problems
from cpagents.agents import solve_with_judge


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--problems", default=None)
    ap.add_argument("--problem", default=None)
    ap.add_argument("--framework", default="cpmpy", choices=["cpmpy", "or-tools", "gurobipy", "minizinc"])
    args = ap.parse_args()

    if BACKEND == "api" and not ANTHROPIC_API_KEY:
        print("ERROR: BACKEND=api requires ANTHROPIC_API_KEY. "
              "(For the SDK/subscription backend set CP_AGENTS_BACKEND=sdk and log in with the `claude` CLI.)",
              file=sys.stderr); sys.exit(1)

    problems = load_problems(args.problems)
    ids = [args.problem] if args.problem else list(problems)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    out = RUNS_DIR / f"summary_solve_judge_{args.framework}.jsonl"

    for pid in ids:
        if not (RUNS_DIR / pid / "verification_pytest.py").exists():
            print(f"  WARNING: no verifier for '{pid}'. Run run_verifier_agent.py first "
                  "(run_verifier_on_solver will ERROR).")

    passed = disputed = incomplete = 0
    with open(out, "w", encoding="utf-8") as f:
        for n, pid in enumerate(ids, 1):
            print(f"\n=== ({n}/{len(ids)}) {pid} | {args.framework}")
            record = solve_with_judge(problems[pid], args.framework)
            f.write(json.dumps(record, ensure_ascii=False) + "\n"); f.flush()
            if record.get("self_consistent"):
                passed += 1; status = f"PASS ({record.get('tries')} iters)"
            elif record.get("disputed"):
                disputed += 1; status = f"DISPUTED ({record.get('tries')} iters)"
            else:
                incomplete += 1; status = "INCOMPLETE"
            print(f"  -> {status}")
    print(f"\nPASS={passed} DISPUTED={disputed} INCOMPLETE={incomplete}. Summary: {out}")


if __name__ == "__main__":
    main()
