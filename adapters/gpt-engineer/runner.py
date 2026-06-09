#!/usr/bin/env python3
"""One-shot wrapper around gpt-engineer (gpte CLI) for SMADP sandbox runs.

gpt-engineer is interactive by default — it asks for clarification, runs
multi-step plans, and writes scaffolded projects. In the sandbox we want a
single non-interactive turn: read $SMADP_AGENT_TASK, run gpte against a
fresh workspace under /work/gpte/, print whatever it produces to stdout,
exit 0.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    task = os.environ.get("SMADP_AGENT_TASK", "").strip()
    if not task:
        print("gpt-engineer runner: no SMADP_AGENT_TASK provided", file=sys.stderr)
        return 1
    if not os.environ.get("OPENAI_API_KEY"):
        print("gpt-engineer runner: OPENAI_API_KEY not set", file=sys.stderr)
        return 1

    project = Path("/work/gpte")
    project.mkdir(parents=True, exist_ok=True)
    (project / "prompt").write_text(task, encoding="utf-8")

    model = os.environ.get("GPT_ENGINEER_MODEL", "gpt-5-mini")
    cmd = [
        "gpte",
        str(project),
        "--model", model,
        "--no_execution",
        "--lite",
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=240,
            check=False,
        )
    except FileNotFoundError:
        print("gpt-engineer runner: gpte CLI not on PATH", file=sys.stderr)
        return 1
    except subprocess.TimeoutExpired:
        print("gpt-engineer runner: gpte timed out after 240s", file=sys.stderr)
        return 1

    sys.stdout.write(proc.stdout or "")
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    return 0  # always exit 0 once gpte completes; transcript captures output


if __name__ == "__main__":
    sys.exit(main())
