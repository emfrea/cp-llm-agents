"""Load problems from a JSONL file.

Each line is one problem:
    {
      "id": "knapsack",
      "description": "... natural-language statement ...",
      "decision_variables": ["x"],
      "instances": [{"values": [...], "weights": [...], "capacity": 7}],
      "example_solution": {"x": [0, 0, 1, 1, 0]}
    }

Only `id` and `description` are required. `instances[0]` is pre-injected into the
solver/verifier namespace; `example_solution` conveys output format only.
"""

import json
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "examples" / "problems.jsonl"


def load_problems(path=None):
    path = Path(path) if path else DEFAULT_PATH
    problems = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            problems[item["id"]] = {
                "id": item["id"],
                "description": item.get("description", ""),
                "instances": item.get("instances", []) or [],
                "decision_variables": item.get("decision_variables", []) or [],
                "example_solution": item.get("example_solution", {}) or {},
            }
    return problems
