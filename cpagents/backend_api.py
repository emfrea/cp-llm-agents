"""Anthropic API backend (pay-as-you-go): a minimal tool-calling loop.

Requires `pip install anthropic` and ANTHROPIC_API_KEY. Returns the executor; the
dispatcher in backend.py calls summary_record().
"""

import anthropic

from .config import MODEL, MAX_TOKENS, AGENT_MAX_TURNS, ANTHROPIC_API_KEY


def run_agent_api(executor, system_prompt, user_prompt):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    messages = [{"role": "user", "content": user_prompt}]

    for _turn in range(AGENT_MAX_TURNS):
        resp = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            tools=executor.tool_schemas,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": resp.content})

        tool_results = []
        for block in resp.content:
            if block.type == "text":
                executor.log_assistant(block.text)
            elif block.type == "tool_use":
                result = executor.dispatch(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(result),
                })

        if resp.stop_reason != "tool_use":
            # Model stopped without a tool call. If it isn't actually done, nudge once.
            if not executor.finished:
                messages.append({"role": "user",
                                 "content": "Continue using the tools. Call done()/"
                                            "mark_verification_ready() when finished."})
                continue
            break

        messages.append({"role": "user", "content": tool_results})
        if executor.finished:
            break

    return executor
