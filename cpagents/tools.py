"""Tool schemas and ToolExecutors for the three agents.

Each executor exposes a fixed set of tools (Anthropic tool schemas). Tool calls are
routed through dispatch(); no tool can crash the loop (exceptions become messages).

  ToolExecutorSolver            - solver agent, no verifier
  ToolExecutorVerifierPytest    - verifier agent (writes a pytest test suite)
  ToolExecutorSolverWithJudge   - solver that runs + judges the pytest verifier
"""

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from .malformed import generate_malformed
from .execution import instance_prelude, run_solver, run_verifier
from .config import FRAMEWORK_EXT, AGENT_MAX_ITERS

VERIFIER_FILE = "verification_pytest.py"

# --- pytest harness injected around the agent's test functions ---------------
PYTEST_PREAMBLE = '''
import os, json, pytest

@pytest.fixture
def solution():
    with open(os.environ["CP_SOLUTION_PATH"]) as _f:
        return json.load(_f)
'''

PYTEST_FOOTER = '''
if __name__ == "__main__":
    import sys
    os.environ["CP_SOLUTION_PATH"] = sys.argv[1]
    _code = pytest.main([__file__, "-q", "-p", "no:cacheprovider"])
    if _code == 0:
        print("PASS")
    elif _code == 1:
        print("FAIL: one or more feasibility tests failed")
    else:
        print(f"ERROR: pytest exit code {_code}")
    sys.exit(0)
'''


def _ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class _Base:
    """Shared file writing + logging."""

    def __init__(self, problem, problem_dir):
        self.problem = problem
        self.dir = Path(problem_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.prelude = instance_prelude(problem.get("instances"))
        self.finished = False

    def _log_header(self, title):
        with open(self.log_file, "w", encoding="utf-8") as f:
            f.write(f"=== {title}: {self.problem['id']} ===\nstarted: {_ts()}\n\n")

    def log(self, text):
        with open(self.log_file, "a", encoding="utf-8", errors="replace") as f:
            f.write(text.rstrip() + "\n")

    def log_assistant(self, text):
        if text and text.strip():
            self.log(f"\n[assistant {_ts()}]\n{text.strip()}")

    def _write_with_prelude(self, filename, content):
        body = content
        if self.prelude and not filename.endswith(".mzn"):
            body = self.prelude + "\n" + content
        with open(self.dir / filename, "w", encoding="utf-8") as f:
            f.write(body)


# ---------------------------------------------------------------------------
# Agent 1 - solver, no verifier
# ---------------------------------------------------------------------------
SOLVER_TOOL_SCHEMAS = [
    {"name": "write_file",
     "description": "Write the solver file for this problem. Instance parameters are auto-injected "
                    "at the top. Overwrites any previous version.",
     "input_schema": {"type": "object",
                      "properties": {"content": {"type": "string", "description": "Full source of the solver."}},
                      "required": ["content"]}},
    {"name": "run_solver",
     "description": "Run the current solver. Captures its JSON solution. Returns the parsed "
                    "solution or an error.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "done",
     "description": "Declare the problem solved. Only valid once run_solver has produced a valid solution.",
     "input_schema": {"type": "object", "properties": {}}},
]


class ToolExecutorSolver(_Base):
    tool_schemas = SOLVER_TOOL_SCHEMAS

    def __init__(self, problem, framework, problem_dir):
        super().__init__(problem, problem_dir)
        self.fw = framework
        ext = FRAMEWORK_EXT.get(framework, "py")
        self.solver_file = f"solver_{framework}.{ext}"
        self.solution_file = f"solution_{framework}.json"
        self.log_file = self.dir / f"log_solver_{framework}.txt"
        self.iter = 0
        self.solver_ran = False
        self.last_solution = None
        self._log_header(f"solver log [{framework}]")

    def write_file(self, content):
        self._write_with_prelude(self.solver_file, content)
        self.log(f"\n[tool {_ts()}] write_file -> {self.solver_file}")
        return f"Wrote {self.solver_file}."

    def run_solver(self):
        if not (self.dir / self.solver_file).exists():
            return "ERROR: no solver file yet. Use write_file() first."
        self.iter += 1
        ok, result, *_ = run_solver(self.dir, self.solver_file, self.fw)
        self.solver_ran = ok
        if ok:
            self.last_solution = result
            with open(self.dir / self.solution_file, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2)
            self.log(f"\n[tool {_ts()}] run_solver (iter {self.iter}) -> OK\nsolution: {json.dumps(result)}")
            return f"Solver ran. Solution:\n{json.dumps(result, indent=2)}"
        self.last_solution = None
        self.log(f"\n[tool {_ts()}] run_solver (iter {self.iter}) -> ERROR\n{result}")
        return f"Solver did NOT produce a valid solution:\n{result}"

    def done(self):
        if not self.solver_ran or self.last_solution is None:
            return "ERROR: cannot finish. run_solver() must succeed first."
        self.finished = True
        self.log(f"\n[tool {_ts()}] done -> complete after {self.iter} iterations")
        return "Done. The solver produced a solution."

    def dispatch(self, name, args):
        args = args or {}
        try:
            if name == "write_file":
                return self.write_file(args.get("content", ""))
            if name == "run_solver":
                return self.run_solver()
            if name == "done":
                return self.done()
            return f"ERROR: unknown tool '{name}'."
        except Exception as e:
            self.log(f"\n[tool-error {_ts()}] {name}: {e}")
            return f"ERROR while running {name}: {e}"

    def summary_record(self):
        src = (self.dir / self.solver_file).read_text(encoding="utf-8") if (self.dir / self.solver_file).exists() else ""
        return {"id": self.problem["id"], "framework": self.fw, "solver": src,
                "output": self.last_solution if self.last_solution is not None else {},
                "tries": self.iter, "finished": self.finished}


# ---------------------------------------------------------------------------
# Agent 2 - verifier as a pytest test suite
# ---------------------------------------------------------------------------
VERIFIER_PYTEST_TOOL_SCHEMAS = [
    {"name": "write_file",
     "description": "Write the pytest test suite. Write ONLY the test functions; the imports, the "
                    "`solution` fixture and the run harness are injected. Instance parameters are "
                    "auto-injected at the top. Overwrites any previous version.",
     "input_schema": {"type": "object",
                      "properties": {"content": {"type": "string", "description": "The test functions."}},
                      "required": ["content"]}},
    {"name": "check_verifier_robustness",
     "description": "Run the suite against structurally-invalid inputs (missing keys, wrong types, "
                    "null, empty). A correct suite rejects all of them (FAIL) and never crashes (ERROR).",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "check_verifier_on",
     "description": "Run the suite against a solution YOU supply (a JSON object of decision variables) "
                    "and see its verdict. Returns PASS / FAIL / ERROR.",
     "input_schema": {"type": "object",
                      "properties": {"solution": {"type": "object", "description": "Candidate solution."}},
                      "required": ["solution"]}},
    {"name": "mark_verification_ready",
     "description": "Signal that the test suite is complete. Runs a robustness check.",
     "input_schema": {"type": "object", "properties": {}}},
]


class ToolExecutorVerifierPytest(_Base):
    tool_schemas = VERIFIER_PYTEST_TOOL_SCHEMAS

    def __init__(self, problem, problem_dir):
        super().__init__(problem, problem_dir)
        self.verifier_file = VERIFIER_FILE
        self.log_file = self.dir / "log_verifier.txt"
        self.last_robustness = None
        self._log_header("verify log")

    def write_file(self, content):
        wrapped = PYTEST_PREAMBLE + "\n" + content + "\n" + PYTEST_FOOTER
        self._write_with_prelude(self.verifier_file, wrapped)
        self.log(f"\n[tool {_ts()}] write_file -> {self.verifier_file}")
        return f"Wrote {self.verifier_file} (pytest suite, feasibility-only)."

    def _run_on(self, solution):
        fd, path = tempfile.mkstemp(suffix=".json", prefix="sol_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(solution, f)
        try:
            return run_verifier(self.dir, self.verifier_file, path)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def check_verifier_robustness(self):
        if not (self.dir / self.verifier_file).exists():
            return "ERROR: no verifier file yet. Use write_file() first."
        cases = generate_malformed(self.problem.get("decision_variables"),
                                   self.problem.get("example_solution"))
        if not cases:
            self.last_robustness = {"rejected": 0, "accepted": 0, "crashes": 0, "total": 0}
            return "No shape info to build malformed inputs; robustness check skipped."
        rejected = accepted = crashes = 0
        lines = []
        for label, case in cases:
            status, _ = self._run_on(case)
            if status == "FAIL":
                rejected += 1; lines.append(f"  {label}: rejected (good)")
            elif status == "PASS":
                accepted += 1; lines.append(f"  {label}: ACCEPTED malformed input (BUG)")
            else:
                crashes += 1; lines.append(f"  {label}: ERROR/crash (BUG)")
        self.last_robustness = {"rejected": rejected, "accepted": accepted,
                                "crashes": crashes, "total": len(cases)}
        summary = f"rejected {rejected}/{len(cases)}, wrongly-accepted {accepted}, crashed {crashes}"
        self.log(f"\n[tool {_ts()}] check_verifier_robustness -> {summary}\n" + "\n".join(lines))
        msg = ("Robustness (structurally-invalid inputs, which MUST be rejected without crashing):\n"
               f"{summary}\n" + "\n".join(lines))
        if crashes or accepted:
            msg += "\nThe suite is buggy on malformed input: it must FAIL and never crash."
        return msg

    def check_verifier_on(self, solution):
        if not (self.dir / self.verifier_file).exists():
            return "ERROR: no verifier file yet. Use write_file() first."
        if not isinstance(solution, dict):
            return "ERROR: `solution` must be a JSON object (dict)."
        status, detail = self._run_on(solution)
        self.log(f"\n[tool {_ts()}] check_verifier_on {json.dumps(solution)} -> {status}\n{detail}")
        return (f"Verifier verdict on the solution you supplied: {status}.\n{detail}\n"
                "(Judge correctness from the problem statement.)")

    def mark_verification_ready(self):
        if not (self.dir / self.verifier_file).exists():
            return "ERROR: no verifier file yet."
        note = self.check_verifier_robustness()
        self.finished = True
        self.log(f"\n[tool {_ts()}] mark_verification_ready")
        return "Verification marked ready. " + note

    def dispatch(self, name, args):
        args = args or {}
        try:
            if name == "write_file":
                return self.write_file(args.get("content", ""))
            if name == "check_verifier_robustness":
                return self.check_verifier_robustness()
            if name == "check_verifier_on":
                return self.check_verifier_on(args.get("solution"))
            if name == "mark_verification_ready":
                return self.mark_verification_ready()
            return f"ERROR: unknown tool '{name}'."
        except Exception as e:
            self.log(f"\n[tool-error {_ts()}] {name}: {e}")
            return f"ERROR while running {name}: {e}"

    def summary_record(self):
        src = (self.dir / self.verifier_file).read_text(encoding="utf-8") if (self.dir / self.verifier_file).exists() else ""
        return {"id": self.problem["id"], "verifier": src,
                "robustness": self.last_robustness, "finished": self.finished}


# ---------------------------------------------------------------------------
# Agent 3 - solver guided by the verifier (judge loop)
# ---------------------------------------------------------------------------
SOLVER_WITH_JUDGE_TOOL_SCHEMAS = [
    {"name": "write_file",
     "description": "Write the solver file. Instance parameters are auto-injected. Cannot be called "
                    "while a verifier verdict is awaiting judgment.",
     "input_schema": {"type": "object",
                      "properties": {"content": {"type": "string", "description": "Full source of the solver."}},
                      "required": ["content"]}},
    {"name": "run_solver",
     "description": "Run the current solver. Cannot be called while a verdict is awaiting judgment.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "run_verifier_on_solver",
     "description": "Run the pre-built verifier against the solver's latest solution. Returns "
                    "PASS / FAIL / ERROR. A FAIL or ERROR requires an immediate judge_verifier_verdict().",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "check_verifier_on",
     "description": "Run the verifier against a solution YOU supply. May be called while a verdict is "
                    "awaiting judgment.",
     "input_schema": {"type": "object",
                      "properties": {"solution": {"type": "object", "description": "Candidate solution."}},
                      "required": ["solution"]}},
    {"name": "judge_verifier_verdict",
     "description": "MANDATORY after every FAIL or ERROR. Commit to whether the verifier's verdict is "
                    "correct, judged against the NL description. true = verifier right, fix the solver; "
                    "false = verifier wrong, keep your solution and call done().",
     "input_schema": {"type": "object",
                      "properties": {"agrees_with_verifier": {"type": "string", "enum": ["true", "false"]},
                                     "reasoning": {"type": "string"}},
                      "required": ["agrees_with_verifier", "reasoning"]}},
    {"name": "done",
     "description": "Declare the problem solved. Valid after a PASS, or right after "
                    "judge_verifier_verdict(agrees_with_verifier=false).",
     "input_schema": {"type": "object", "properties": {}}},
]


class ToolExecutorSolverWithJudge(_Base):
    """Reads the pre-built verifier (verification_pytest.py) from the same problem_dir."""
    tool_schemas = SOLVER_WITH_JUDGE_TOOL_SCHEMAS

    def __init__(self, problem, framework, problem_dir):
        super().__init__(problem, problem_dir)
        self.fw = framework
        ext = FRAMEWORK_EXT.get(framework, "py")
        self.verifier_file = VERIFIER_FILE
        self.solver_file = f"solver_{framework}.{ext}"
        self.solution_file = f"solution_{framework}.json"
        self.log_file = self.dir / f"log_solver_judge_{framework}.txt"
        self.iter = 0
        self.solver_ran = False
        self.last_solution = None
        self.last_verify_status = None
        self.pending_judgment = False
        self.judgments = []
        self.disputed = False
        self._log_header(f"solver (with-judge) log [{framework}]")

    def write_file(self, content):
        if self.pending_judgment:
            return "ERROR: call judge_verifier_verdict() before modifying the solver."
        self._write_with_prelude(self.solver_file, content)
        self.log(f"\n[tool {_ts()}] write_file -> {self.solver_file}")
        return f"Wrote {self.solver_file}."

    def run_solver(self):
        if self.pending_judgment:
            return "ERROR: call judge_verifier_verdict() before running the solver again."
        if not (self.dir / self.solver_file).exists():
            return "ERROR: no solver file yet. Use write_file() first."
        ok, result, *_ = run_solver(self.dir, self.solver_file, self.fw)
        self.solver_ran = ok
        if ok:
            self.last_solution = result
            with open(self.dir / self.solution_file, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2)
            self.log(f"\n[tool {_ts()}] run_solver -> OK\nsolution: {json.dumps(result)}")
            return f"Solver ran. Solution:\n{json.dumps(result, indent=2)}"
        self.last_solution = None
        self.log(f"\n[tool {_ts()}] run_solver -> ERROR\n{result}")
        return f"Solver did NOT produce a valid solution:\n{result}"

    def run_verifier_on_solver(self):
        if self.pending_judgment:
            return "ERROR: call judge_verifier_verdict() for the previous FAIL/ERROR first."
        if not (self.dir / self.verifier_file).exists():
            return f"ERROR: verifier not found ({self.verifier_file}). Build it first."
        if not self.solver_ran or self.last_solution is None:
            return "ERROR: run_solver() must succeed before run_verifier_on_solver()."
        status, detail = run_verifier(self.dir, self.verifier_file, self.dir / self.solution_file)
        self.last_verify_status = status
        self.iter += 1
        self.log(f"\n[tool {_ts()}] run_verifier_on_solver (iter {self.iter}) -> {status}\n{detail}")
        if status != "PASS":
            self.pending_judgment = True
            note = ""
            if self.iter >= AGENT_MAX_ITERS:
                note = f"\nNOTE: iteration budget ({AGENT_MAX_ITERS}) reached. You MUST still judge before done()."
            return f"Verifier result: {status}.\n{detail}\nYou MUST call judge_verifier_verdict() before proceeding.{note}"
        return f"Verifier result: PASS.\n{detail}"

    def _run_on(self, solution):
        fd, path = tempfile.mkstemp(suffix=".json", prefix="sol_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(solution, f)
        try:
            return run_verifier(self.dir, self.verifier_file, path)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def check_verifier_on(self, solution):
        if not (self.dir / self.verifier_file).exists():
            return f"ERROR: verifier not found ({self.verifier_file})."
        if not isinstance(solution, dict):
            return "ERROR: `solution` must be a JSON object (dict)."
        status, detail = self._run_on(solution)
        self.log(f"\n[tool {_ts()}] check_verifier_on {json.dumps(solution)} -> {status}\n{detail}")
        return f"Verifier verdict on the solution you supplied: {status}.\n{detail}"

    def judge_verifier_verdict(self, agrees_with_verifier, reasoning):
        if not self.pending_judgment:
            return "ERROR: judge_verifier_verdict() is only valid after a FAIL or ERROR."
        if isinstance(agrees_with_verifier, str):
            agrees = agrees_with_verifier.strip().lower() == "true"
        elif isinstance(agrees_with_verifier, bool):
            agrees = agrees_with_verifier
        else:
            return "ERROR: agrees_with_verifier must be 'true' or 'false'."
        if not reasoning or not reasoning.strip():
            return "ERROR: reasoning must not be empty."
        self.judgments.append({"iter": self.iter, "verify_status": self.last_verify_status,
                               "agrees_with_verifier": agrees, "reasoning": reasoning, "ts": _ts()})
        self.pending_judgment = False
        label = "AGREE - verifier correct, fix solver" if agrees else "DISAGREE - verifier wrong, disputing"
        self.log(f"\n[judgment {_ts()}] iter={self.iter} status={self.last_verify_status} verdict={label}\nreasoning: {reasoning}")
        if agrees:
            return f"Judgment recorded: {label}.\nFix the solver with write_file(), then run_solver() and run_verifier_on_solver()."
        return f"Judgment recorded: {label}.\nYour current solution is accepted under dispute. Call done() to finalize."

    def done(self):
        if self.pending_judgment:
            return "ERROR: call judge_verifier_verdict() before done()."
        if self.last_verify_status == "PASS":
            self.finished = True; self.disputed = False
            self.log(f"\n[tool {_ts()}] done -> PASS after {self.iter} iterations")
            return "Done. The solver's output passed the verifier."
        last = self.judgments[-1] if self.judgments else None
        if last is not None and last["iter"] == self.iter and last["agrees_with_verifier"] is False:
            self.finished = True; self.disputed = True
            self.log(f"\n[tool {_ts()}] done -> DISPUTED after {self.iter} iterations")
            return "Done. Solution accepted under dispute - verifier verdict rejected."
        return (f"ERROR: cannot call done(). Last verifier status was {self.last_verify_status!r}. "
                "Either achieve a PASS, or dispute via judge_verifier_verdict(agrees_with_verifier=false, ...).")

    def dispatch(self, name, args):
        args = args or {}
        try:
            if name == "write_file":
                return self.write_file(args.get("content", ""))
            if name == "run_solver":
                return self.run_solver()
            if name == "run_verifier_on_solver":
                return self.run_verifier_on_solver()
            if name == "check_verifier_on":
                return self.check_verifier_on(args.get("solution"))
            if name == "judge_verifier_verdict":
                return self.judge_verifier_verdict(args.get("agrees_with_verifier"), args.get("reasoning", ""))
            if name == "done":
                return self.done()
            return f"ERROR: unknown tool '{name}'."
        except Exception as e:
            self.log(f"\n[tool-error {_ts()}] {name}: {e}")
            return f"ERROR while running {name}: {e}"

    def summary_record(self):
        src = (self.dir / self.solver_file).read_text(encoding="utf-8") if (self.dir / self.solver_file).exists() else ""
        return {"id": self.problem["id"], "framework": self.fw, "solver": src,
                "output": self.last_solution if self.last_solution is not None else {},
                "tries": self.iter, "judgments": self.judgments,
                "disputed": self.disputed, "finished": self.finished,
                "self_consistent": self.finished and not self.disputed}
