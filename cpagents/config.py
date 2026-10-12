"""Configuration for the cp-llm-agents pipeline.

The Anthropic API key is read from the environment (never hard-coded):
    ANTHROPIC_API_KEY
Override the model or limits with environment variables if you like.
"""

import os
from pathlib import Path

# --- Paths -------------------------------------------------------------------
HERE = Path(__file__).resolve().parent.parent
RUNS_DIR = HERE / "runs"          # per-problem agent artifacts are written here

# --- API key (from env) ------------------------------------------------------
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

# --- Model -------------------------------------------------------------------
# Any current Claude model id works. Override with CP_AGENTS_MODEL.
MODEL = os.environ.get("CP_AGENTS_MODEL", "claude-sonnet-4-5")

# --- Solver frameworks -------------------------------------------------------
FRAMEWORKS = ["cpmpy", "or-tools", "gurobipy", "minizinc"]
FRAMEWORK_EXT = {"cpmpy": "py", "or-tools": "py", "gurobipy": "py", "minizinc": "mzn"}

# --- Loop / execution limits -------------------------------------------------
AGENT_MAX_TURNS = int(os.environ.get("CP_AGENTS_MAX_TURNS", "60"))   # LLM round-trips / problem
AGENT_MAX_ITERS = int(os.environ.get("CP_AGENTS_MAX_ITERS", "12"))   # verify-on-solver iterations
MAX_TOKENS = int(os.environ.get("CP_AGENTS_MAX_TOKENS", "16384"))

SOLVER_TIMEOUT = 60      # seconds
VERIFIER_TIMEOUT = 30    # seconds
MINIZINC_TIMEOUT = 30    # seconds
