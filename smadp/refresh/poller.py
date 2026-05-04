"""Refresh poller entry — runs all watchers and enqueues new work.

Entry: ``python -m smadp.refresh.poller`` runs a forever-loop with a
default 10-second interval. Most operators will instead use
``smadp refresh poll`` from the Click CLI; this module exposes the
``sweep`` primitive and a thin ``__main__`` wrapper.
"""

from __future__ import annotations

import time
from typing import Final

import structlog

from smadp.config import Config, load_config
from smadp.refresh import queue
from smadp.refresh.watchers import iter_watchers
from smadp.schemas.refresh import RefreshTrigger

log = structlog.get_logger(__name__)

_DEFAULT_INTERVAL_S: Final[float] = 10.0


def _already_pending(verdict_id: str, trigger: RefreshTrigger, *, config: Config) -> bool:
    for row in queue.list_pending(config=config):
        if row.verdict_id == verdict_id and row.trigger is trigger:
            return True
    return False


def sweep(*, config: Config | None = None) -> int:
    cfg = config or load_config()
    enqueued = 0
    for w in iter_watchers():
        for verdict_id, detail in w.discover(config=cfg):
            if _already_pending(verdict_id, w.trigger, config=cfg):
                continue
            queue.enqueue(
                verdict_id=verdict_id,
                trigger=w.trigger,
                trigger_detail=detail,
                config=cfg,
            )
            enqueued += 1
    if enqueued:
        log.info("refresh.poller.sweep", enqueued=enqueued)
    return enqueued


def main() -> None:
    cfg = load_config()
    while True:
        sweep(config=cfg)
        queue.reap_stale(config=cfg)
        time.sleep(_DEFAULT_INTERVAL_S)


if __name__ == "__main__":
    main()


__all__ = ["main", "sweep"]
