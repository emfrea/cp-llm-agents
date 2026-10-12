"""Claude Agent SDK backend (subscription billing) — the one the thesis experiments used.

Routes through the `claude` CLI, authenticating with your Claude Pro/Max SUBSCRIPTION
instead of pay-as-you-go API credits — PROVIDED `ANTHROPIC_API_KEY` is not set (that env
var forces API billing; we pop it from the child environment). You must be logged in via
`claude /login` (or `claude setup-token`), and have `pip install claude-agent-sdk`.

The executor's tools are exposed to the model as in-process SDK MCP tools, so the agent
behaves the same as the API backend. Returns the executor; the dispatcher in backend.py
calls summary_record().
"""

import asyncio
import os
import sys

from claude_agent_sdk import (
    tool, create_sdk_mcp_server, query, ClaudeAgentOptions,
    AssistantMessage, TextBlock, ResultMessage,
)

from .config import MODEL, AGENT_MAX_TURNS

_JSON2PY = {"string": str, "object": dict, "number": float,
            "integer": int, "boolean": bool, "array": list}

# Keep the agent to OUR tools only; deny the CLI's built-in tools.
_BUILTIN_DISALLOW = ["Bash", "Write", "Edit", "Read", "Glob", "Grep",
                     "WebFetch", "WebSearch", "NotebookEdit", "TodoWrite", "Task"]


def _read_user_env(name):
    """Windows-only: read a User-scope env var from the registry (needed when the
    process was launched before the var was set). Returns None elsewhere."""
    if sys.platform != "win32":
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
            return value
    except OSError:
        return None


def _build_tools(executor):
    sdk_tools = []
    for schema in executor.tool_schemas:
        name = schema["name"]
        props = (schema.get("input_schema") or {}).get("properties", {})
        in_schema = {k: _JSON2PY.get(v.get("type"), str) for k, v in props.items()}

        def make_cb(tool_name):
            async def cb(args):
                result = executor.dispatch(tool_name, args or {})
                return {"content": [{"type": "text", "text": str(result)}]}
            return cb

        sdk_tools.append(tool(name, schema["description"], in_schema)(make_cb(name)))
    return sdk_tools


async def _run_async(executor, system_prompt, user_prompt):
    server = create_sdk_mcp_server(name="agent", version="1.0.0", tools=_build_tools(executor))
    allowed = [f"mcp__agent__{s['name']}" for s in executor.tool_schemas]
    child_env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    if "CLAUDE_CODE_OAUTH_TOKEN" not in child_env:
        token = _read_user_env("CLAUDE_CODE_OAUTH_TOKEN")
        if token:
            child_env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    child_env.setdefault("CLAUDE_CODE_MAX_OUTPUT_TOKENS", "65536")

    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        mcp_servers={"agent": server},
        allowed_tools=allowed,
        disallowed_tools=_BUILTIN_DISALLOW,
        permission_mode="bypassPermissions",
        model=MODEL,
        max_turns=AGENT_MAX_TURNS,
        env=child_env,
        setting_sources=None,   # don't load project/user CLI settings
    )

    last_result = None
    try:
        async for msg in query(prompt=user_prompt, options=options):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        executor.log_assistant(block.text)
            elif isinstance(msg, ResultMessage):
                last_result = msg
                executor.log(f"\n[sdk result] subtype={msg.subtype} turns={msg.num_turns} "
                             f"is_error={msg.is_error} cost_usd={msg.total_cost_usd}")
    except Exception as e:
        # The CLI can exit non-zero after a normal (subtype=success) completion, which
        # makes the SDK raise a spurious error. Swallow it; re-raise genuine failures.
        if last_result is not None and last_result.subtype == "success":
            executor.log(f"\n[sdk] ignoring post-completion exit error: {e}")
        else:
            raise
    return executor


def run_agent_sdk(executor, system_prompt, user_prompt):
    os.environ.pop("ANTHROPIC_API_KEY", None)   # ensure subscription auth, not API billing
    return asyncio.run(_run_async(executor, system_prompt, user_prompt))
