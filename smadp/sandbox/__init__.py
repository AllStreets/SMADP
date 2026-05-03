"""Sandbox Validator subsystem.

The Sandbox Validator runs pairs of open-source agents in airtight containers
and observes their interactions to either confirm or contradict LLM-judged
verdicts. See ``isolation.py`` for the full threat model and ``runner.py`` for
the execution pipeline.

Public surface (consumed by CLI / REST API):

    enqueue_sandbox_run, get_run_status, iter_runs, list_pending  (queue.py)
    execute_run                                                   (runner.py)
"""

from __future__ import annotations

from smadp.sandbox.queue import (
    enqueue_sandbox_run,
    get_run_status,
    iter_runs,
    list_pending,
)
from smadp.sandbox.runner import execute_run

__all__ = [
    "enqueue_sandbox_run",
    "execute_run",
    "get_run_status",
    "iter_runs",
    "list_pending",
]
