#!/usr/bin/env python3
"""Thin one-shot wrapper around autogen-agentchat for SMADP sandbox runs.

Reads the task from $SMADP_AGENT_TASK, drives a single AssistantAgent with
OpenAI as the model client, prints the agent's messages to stdout, exits 0.

The official autogen library is a framework, not a CLI — this script is the
minimal glue that lets the sandbox treat it as one.
"""
from __future__ import annotations

import asyncio
import os
import sys


async def main() -> int:
    task = os.environ.get("SMADP_AGENT_TASK", "").strip()
    if not task:
        print("autogen runner: no SMADP_AGENT_TASK provided", file=sys.stderr)
        return 1

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print("autogen runner: OPENAI_API_KEY not set", file=sys.stderr)
        return 1

    try:
        from autogen_agentchat.agents import AssistantAgent
        from autogen_ext.models.openai import OpenAIChatCompletionClient
    except ImportError as exc:
        print(f"autogen runner: import failed ({exc})", file=sys.stderr)
        return 1

    model = os.environ.get("AUTOGEN_MODEL", "gpt-5-mini")
    model_client = OpenAIChatCompletionClient(model=model, api_key=api_key)
    agent = AssistantAgent(
        name="smadp_autogen",
        model_client=model_client,
        system_message=(
            "You are a careful agent operating inside a sandbox. "
            "Read any referenced files, complete the task, then stop."
        ),
    )

    try:
        result = await agent.run(task=task)
    except Exception as exc:
        print(f"autogen runner: agent.run failed ({exc})", file=sys.stderr)
        return 1

    for msg in result.messages:
        text = getattr(msg, "content", None) or getattr(msg, "to_text", lambda: str(msg))()
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
