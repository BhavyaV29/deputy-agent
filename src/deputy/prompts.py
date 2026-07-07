"""Prompt and transcript text for the agent loop.

Observations are threaded back as plain ``user`` turns rather than Ollama's
native ``tool`` role: the loop runs its own JSON action protocol, so it stays
model-agnostic instead of relying on any one runtime's tool-calling semantics.
"""

from __future__ import annotations

from deputy.tools import ToolRegistry, signature


def system_prompt(registry: ToolRegistry) -> str:
    catalog = "\n".join(f"- {signature(tool)}: {tool.description}" for tool in registry)
    return (
        "You are Deputy, a private on-device assistant. Reach the user's goal one step "
        "at a time, using tools when they help.\n\n"
        f"Tools:\n{catalog}\n\n"
        "Reply on every turn with a single JSON object, either\n"
        '  {"tool": "<name>", "args": {...}}  to run a tool, or\n'
        '  {"final": "<answer>"}              once you can answer the goal.\n'
        "Base each step on the observations returned by earlier tool calls."
    )


def observation_message(tool: str, observation: str) -> str:
    return f"Observation from `{tool}`:\n{observation}"


def denial_message(tool: str, reason: str) -> str:
    detail = f" ({reason})" if reason else ""
    return f"Your request to run `{tool}` was declined{detail}. Choose a different action."


def critic_message(feedback: str) -> str:
    return f"A self-check rejected that answer: {feedback}\nAddress it, then answer again."
