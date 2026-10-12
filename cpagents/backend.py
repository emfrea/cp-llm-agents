"""Backend dispatcher.

Runs the agent loop through either the Claude Agent SDK (subscription — what the thesis
experiments used) or the Anthropic API (pay-as-you-go), selected by config.BACKEND
(env CP_AGENTS_BACKEND, "sdk" or "api"). Returns the executor's summary record.
"""

from .config import BACKEND


def run_agent(executor, system_prompt, user_prompt):
    if BACKEND == "sdk":
        from .backend_sdk import run_agent_sdk
        run_agent_sdk(executor, system_prompt, user_prompt)
    elif BACKEND == "api":
        from .backend_api import run_agent_api
        run_agent_api(executor, system_prompt, user_prompt)
    else:
        raise ValueError(f"Unknown CP_AGENTS_BACKEND={BACKEND!r} (use 'sdk' or 'api').")
    return executor.summary_record()
