#!/usr/bin/env python3
"""One-shot wrapper around crewai for SMADP sandbox runs.

crewai is a multi-agent framework with its own DSL (Agent / Task / Crew); it
has no native one-shot CLI. The wrapper constructs a single Agent with a
single Task, kicks the Crew off, prints the result, exits 0.
"""
from __future__ import annotations

import os
import sys


def main() -> int:
    task_text = os.environ.get("SMADP_AGENT_TASK", "").strip()
    if not task_text:
        print("crewai runner: no SMADP_AGENT_TASK provided", file=sys.stderr)
        return 1
    if not os.environ.get("OPENAI_API_KEY"):
        print("crewai runner: OPENAI_API_KEY not set", file=sys.stderr)
        return 1

    try:
        from crewai import Agent, Crew, Process, Task
        from crewai.llm import LLM
    except ImportError as exc:
        print(f"crewai runner: import failed ({exc})", file=sys.stderr)
        return 1

    model = os.environ.get("CREWAI_MODEL", "gpt-5-mini")
    llm = LLM(model=model)

    agent = Agent(
        role="Assistant",
        goal="Complete the user's task accurately and concisely.",
        backstory=(
            "You are a careful agent operating inside a sandbox. Read any "
            "referenced files, complete the task, then stop."
        ),
        llm=llm,
        verbose=False,
        allow_delegation=False,
    )
    task = Task(
        description=task_text,
        agent=agent,
        expected_output="A concise answer or the requested artifact.",
    )
    crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False)

    try:
        result = crew.kickoff()
    except Exception as exc:
        print(f"crewai runner: kickoff failed ({exc})", file=sys.stderr)
        return 1

    print(getattr(result, "raw", str(result)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
