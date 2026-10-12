"""Execution helpers: inject instance data, run solvers, run the verifier.

Everything runs in a subprocess using the current interpreter, with timeouts.
Solutions are JSON objects parsed from stdout.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

from .config import SOLVER_TIMEOUT, VERIFIER_TIMEOUT, MINIZINC_TIMEOUT


def instance_prelude(instances):
    """Python source binding the first instance's params into the namespace.

    Empty when there is no instance. Not used for MiniZinc (values are embedded
    directly in the .mzn model instead)."""
    if not instances:
        return ""
    lines = ["# --- instance parameters (pre-injected) ---"]
    for var_name, value in instances[0].items():
        lines.append(f"{var_name} = {value!r}")
    lines.append("# --- end instance parameters ---\n")
    return "\n".join(lines)


def _parse_json_stdout(stdout):
    try:
        return json.loads(stdout), None
    except json.JSONDecodeError:
        pass
    candidates = [ln.strip() for ln in stdout.splitlines()
                  if ln.strip().startswith("{") and ln.strip().endswith("}")]
    for ln in reversed(candidates):
        try:
            return json.loads(ln), None
        except json.JSONDecodeError:
            continue
    return None, f"Could not parse JSON from stdout. Raw stdout:\n{stdout}"


def run_solver_python(problem_dir, solver_filename, timeout=SOLVER_TIMEOUT):
    """Run a Python solver. Returns (ok, solution_or_error, stdout, stderr)."""
    solver_path = Path(problem_dir) / solver_filename
    if not solver_path.exists():
        return False, f"Solver file not found: {solver_path}", "", ""
    try:
        result = subprocess.run(
            [sys.executable, str(solver_path)], cwd=str(problem_dir),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return False, f"Timeout: solver exceeded {timeout}s.", "", ""
    if result.returncode != 0:
        return False, f"Solver crashed (exit {result.returncode}).\nstderr:\n{result.stderr}", result.stdout, result.stderr
    solution, err = _parse_json_stdout(result.stdout)
    if err:
        return False, err, result.stdout, result.stderr
    if not isinstance(solution, dict) or not solution:
        return False, f"Solver output is not a non-empty JSON object: {solution}", result.stdout, result.stderr
    if any(v is None for v in solution.values()):
        return False, f"Solver output contains None (no solution): {solution}", result.stdout, result.stderr
    return True, solution, result.stdout, result.stderr


def run_solver_minizinc(problem_dir, solver_filename, timeout=MINIZINC_TIMEOUT):
    """Run a MiniZinc model via the `minizinc` CLI (gecode)."""
    mzn_path = Path(problem_dir) / solver_filename
    if not mzn_path.exists():
        return False, f"Model file not found: {mzn_path}", "", ""
    exe = shutil.which("minizinc")
    if not exe:
        return False, "minizinc CLI not found on PATH.", "", ""
    try:
        result = subprocess.run(
            [exe, "--solver", "gecode", "--time-limit", str(int(timeout * 1000)), str(mzn_path)],
            cwd=str(problem_dir), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout + 10, check=False)
    except subprocess.TimeoutExpired:
        return False, f"Timeout: MiniZinc exceeded {timeout}s.", "", ""
    stdout, stderr = result.stdout or "", result.stderr or ""
    if result.returncode != 0:
        return False, f"MiniZinc crashed (exit {result.returncode}).\nstderr:\n{stderr}", stdout, stderr
    up = stdout.upper()
    if "UNSATISFIABLE" in up:
        return False, "MiniZinc: model is UNSATISFIABLE (no solution).", stdout, stderr
    if "=====UNKNOWN=====" in up or "UNBOUNDED" in up:
        return False, f"MiniZinc returned no concrete solution.\n{stdout}", stdout, stderr
    cleaned = "\n".join(ln for ln in stdout.splitlines()
                        if ln.strip() not in ("----------", "=========="))
    solution, err = _parse_json_stdout(cleaned)
    if err:
        return False, err, stdout, stderr
    if not isinstance(solution, dict) or not solution:
        return False, f"MiniZinc output is not a non-empty JSON object: {solution}", stdout, stderr
    return True, solution, stdout, stderr


def run_solver(problem_dir, solver_filename, framework):
    if framework == "minizinc":
        return run_solver_minizinc(problem_dir, solver_filename)
    return run_solver_python(problem_dir, solver_filename)


def run_verifier(problem_dir, verifier_filename, solution_path, timeout=VERIFIER_TIMEOUT):
    """Run the verifier on a solution file. Returns (status, detail) where status
    is "PASS", "FAIL", or "ERROR". The verifier must print "PASS" or "FAIL: ..."
    on the last line of stdout; anything else is treated as ERROR."""
    verifier_path = Path(problem_dir) / verifier_filename
    if not verifier_path.exists():
        return "ERROR", f"Verifier file not found: {verifier_path}"
    try:
        result = subprocess.run(
            [sys.executable, str(verifier_path), str(solution_path)], cwd=str(problem_dir),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return "ERROR", f"Verifier timed out after {timeout}s."
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    if result.returncode != 0:
        return "ERROR", f"Verifier crashed (exit {result.returncode}).\nstdout:\n{stdout}\nstderr:\n{stderr}"
    last = stdout.splitlines()[-1].strip() if stdout else ""
    if last == "PASS" or last.startswith("PASS"):
        return "PASS", stdout
    if last.startswith("FAIL"):
        return "FAIL", stdout
    return "ERROR", f"Verifier did not print PASS/FAIL. stdout:\n{stdout}\nstderr:\n{stderr}"
