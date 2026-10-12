# cp-llm-agents

Minimal, self-contained LLM agents that **write, run, verify and self-correct**
constraint-programming / optimisation models from a natural-language description.

Three agents, each a small tool-use loop over the Anthropic API:

| Agent | Tools | Produces |
|---|---|---|
| **Solver** (no verifier) | `write_file` · `run_solver` · `done` | a model + its JSON solution |
| **Verifier** (pytest suite) | `write_file` · `check_verifier_robustness` · `check_verifier_on` · `mark_verification_ready` | `verification_pytest.py` (feasibility-only) |
| **Solver guided by the verifier** | `write_file` · `run_solver` · `run_verifier_on_solver` · `judge_verifier_verdict` · `done` | a solution that passed (or disputed) the verifier |

```
                 ┌─────────────────────────────┐
  Solver agent   │ write_file → run_solver      │  erreur ─┐
  (no verifier)  │               ↓  succès      │          │ (fix & retry)
                 │             done()           │ ◀────────┘
                 └─────────────────────────────┘

                 ┌─────────────────────────────┐
  Verifier agent │ write_file (pytest tests)    │  défaut ─┐
  (pytest suite) │ check_verifier_robustness    │          │ (refine)
                 │ check_verifier_on            │ ◀────────┘
                 │ mark_verification_ready      │  satisfait
                 └─────────────────────────────┘

                 ┌─────────────────────────────┐
  Solver guided  │ write_file, run_solver       │
  by the verifier│ run_verifier_on_solver       │  FAIL/ERROR → judge_verifier_verdict
                 │ judge_verifier_verdict       │    agree  → fix solver, retry
                 │ done()                       │    dispute → keep answer, done()
                 └─────────────────────────────┘
```

Key design points:
- **No ground truth at generation time.** Correctness is derived from the problem
  description alone. The example solution conveys *output format* only.
- **The verifier checks feasibility, not optimality** — one assertion per constraint.
- The generated verifier is a **self-running** pytest file: `python verification_pytest.py
  solution.json` prints `PASS` / `FAIL` / `ERROR` on its last line.
- Every tool call is sandboxed in a subprocess with a timeout; a tool can never crash the loop.

## Install

```bash
pip install -r requirements.txt
export CP_AGENTS_MODEL=claude-sonnet-4-5   # optional: any current Claude model id
```

MiniZinc also needs the [MiniZinc CLI](https://www.minizinc.org) on `PATH`; Gurobi needs a licence.

## Backends

The agent loop runs through one of two backends, selected by `CP_AGENTS_BACKEND`:

- **`sdk`** — the **Claude Agent SDK**, authenticating with a Claude Pro/Max **subscription**
  via the `claude` CLI. **This is what the thesis experiments used.** Needs
  `pip install claude-agent-sdk`, the `claude` CLI logged in (`claude /login` or
  `claude setup-token`), and `ANTHROPIC_API_KEY` **unset** (it would force API billing).
- **`api`** — the **Anthropic API** (pay-as-you-go). Needs only `anthropic` and
  `ANTHROPIC_API_KEY`. This is the default (zero extra setup).

```bash
# subscription backend (as in the thesis)
export CP_AGENTS_BACKEND=sdk      # and `claude /login`, and unset ANTHROPIC_API_KEY

# API backend (default)
export CP_AGENTS_BACKEND=api
export ANTHROPIC_API_KEY=sk-ant-...
```

Both drive the exact same executors and prompts; only the transport/billing differs.

## Run

```bash
# 1) Solver, no verifier
python run_solver_agent.py --framework cpmpy

# 2) Verifier (pytest feasibility suite) — writes runs/<id>/verification_pytest.py
python run_verifier_agent.py

# 3) Solver guided by the verifier (run #2 first)
python run_solver_with_judge.py --framework cpmpy

# a single problem
python run_solver_agent.py --problem knapsack
```

Artifacts land in `runs/<problem_id>/` (generated model, verifier, logs) plus a
`summary_*.jsonl` per run. `runs/` is git-ignored.

## Problem format

Problems are JSONL (`examples/problems.jsonl`); one object per line:

```json
{
  "id": "knapsack",
  "description": "Choose a subset of items ... Print x, a list of 0/1 integers ...",
  "decision_variables": ["x"],
  "instances": [{"values": [4,2,3,7,1], "weights": [3,1,2,5,4], "capacity": 7}],
  "example_solution": {"x": [0, 0, 1, 1, 0]}
}
```

- `instances[0]` is pre-injected into the solver/verifier namespace (Python frameworks);
  for MiniZinc the values are embedded directly in the model.
- `example_solution` is **format only** — its values are not assumed valid.
- Point the scripts at your own file with `--problems path/to/problems.jsonl`.

## Library use

```python
from cpagents import solve, build_verifier, solve_with_judge
from cpagents.dataset import load_problems

problem = load_problems()["knapsack"]
solve(problem, "cpmpy")            # agent 1
build_verifier(problem)            # agent 2  -> verification_pytest.py
solve_with_judge(problem, "cpmpy") # agent 3
```

## Layout

```
cpagents/
  config.py      model, limits, paths
  dataset.py     load problems from JSONL
  prompts.py     the three system prompts + user prompt
  tools.py       tool schemas + the three ToolExecutors
  execution.py   run_solver / run_verifier (subprocess, timeouts)
  malformed.py   robustness inputs for the verifier
  backend.py     dispatcher (sdk | api)
  backend_sdk.py Claude Agent SDK loop (subscription)
  backend_api.py Anthropic API loop (pay-as-you-go)
  agents.py      solve / build_verifier / solve_with_judge
run_solver_agent.py · run_verifier_agent.py · run_solver_with_judge.py
examples/problems.jsonl
```

## License

MIT — see [LICENSE](LICENSE).
