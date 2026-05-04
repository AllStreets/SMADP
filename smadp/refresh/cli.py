"""Click subgroup: smadp refresh {enqueue, drain, poll, ls}."""

from __future__ import annotations

import time
from typing import Any

import click
from rich.console import Console
from rich.table import Table

from smadp.config import load_config
from smadp.refresh import evaluator, queue
from smadp.schemas.refresh import RefreshTrigger

_console = Console()


@click.group(name="refresh")
def refresh_group() -> None:
    """Refresh queue: enqueue, drain, poll, list."""


@refresh_group.command("enqueue")
@click.option("--verdict-id", required=True)
@click.option("--reason", default=None)
def _enqueue(verdict_id: str, reason: str | None) -> None:
    cfg = load_config()
    detail: dict[str, Any] = {"reason": reason} if reason else {}
    item = queue.enqueue(
        verdict_id=verdict_id,
        trigger=RefreshTrigger.MANUAL,
        trigger_detail=detail,
        config=cfg,
    )
    _console.print(f"enqueued  id={item.id}  verdict={item.verdict_id}")


@refresh_group.command("ls")
def _ls() -> None:
    cfg = load_config()
    rows = queue.list_pending(config=cfg)
    table = Table(title="Pending refresh queue")
    for col in ("id", "verdict_id", "trigger", "enqueued_at", "claimed_at"):
        table.add_column(col)
    for r in rows:
        table.add_row(
            str(r.id),
            r.verdict_id,
            r.trigger.value,
            r.enqueued_at.isoformat(),
            r.claimed_at.isoformat() if r.claimed_at else "—",
        )
    _console.print(table)


@refresh_group.command("drain")
@click.option(
    "--max",
    "max_count",
    type=int,
    default=1,
    help="Maximum rows to drain in this invocation.",
)
def _drain(max_count: int) -> None:
    cfg = load_config()
    drained = 0
    for _ in range(max_count):
        item = evaluator.drain_one(config=cfg)
        if item is None:
            break
        drained += 1
        _console.print(f"drained  id={item.id}  verdict={item.verdict_id}")
    _console.print(f"total drained: {drained}")


@refresh_group.command("poll")
@click.option(
    "--interval",
    type=float,
    default=10.0,
    help="Seconds between watcher sweeps.",
)
@click.option("--once", is_flag=True, help="Run one sweep and exit (for tests).")
def _poll(interval: float, once: bool) -> None:
    cfg = load_config()
    from smadp.refresh.poller import sweep

    while True:
        sweep(config=cfg)
        while evaluator.drain_one(config=cfg) is not None:
            pass
        queue.reap_stale(config=cfg)
        if once:
            return
        time.sleep(interval)


__all__ = ["refresh_group"]
