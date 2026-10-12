"""cp-llm-agents: LLM agents that write, run, verify and self-correct
constraint-programming / optimisation models.

Three agents:
  - solve(problem, framework)             : solver, no verifier
  - build_verifier(problem)               : pytest feasibility verifier
  - solve_with_judge(problem, framework)  : solver guided by the verifier (judge loop)
"""

from .agents import solve, build_verifier, solve_with_judge

__all__ = ["solve", "build_verifier", "solve_with_judge"]
__version__ = "0.1.0"
