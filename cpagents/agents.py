"""High-level entry points for the three agents."""

from .config import RUNS_DIR
from .backend import run_agent
from .tools import (ToolExecutorSolver, ToolExecutorVerifierPytest,
                    ToolExecutorSolverWithJudge)
from .prompts import (build_system_prompt_solver, build_system_prompt_verifier_pytest,
                      build_system_prompt_solver_with_judge, build_user_prompt)


def solve(problem, framework):
    """Agent 1 - solver, no verifier access."""
    executor = ToolExecutorSolver(problem, framework, RUNS_DIR / problem["id"])
    return run_agent(executor, build_system_prompt_solver(framework),
                     build_user_prompt(problem, framework=framework))


def build_verifier(problem):
    """Agent 2 - verifier as a pytest test suite (feasibility only)."""
    executor = ToolExecutorVerifierPytest(problem, RUNS_DIR / problem["id"])
    return run_agent(executor, build_system_prompt_verifier_pytest(),
                     build_user_prompt(problem))


def solve_with_judge(problem, framework):
    """Agent 3 - solver that runs and judges the pre-built pytest verifier.

    Requires build_verifier(problem) to have run first (verification_pytest.py in the
    same per-problem directory)."""
    executor = ToolExecutorSolverWithJudge(problem, framework, RUNS_DIR / problem["id"])
    return run_agent(executor, build_system_prompt_solver_with_judge(framework),
                     build_user_prompt(problem, framework=framework))
