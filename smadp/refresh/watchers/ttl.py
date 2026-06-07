"""TTL watcher: enqueue verdicts older than ``ttl_days`` (default 90)."""

from __future__ import annotations

from datetime import UTC, timedelta
from typing import Any, Final

import structlog

from smadp.catalog.repo import CatalogRepo
from smadp.config import Config
from smadp.schemas.refresh import RefreshTrigger
from smadp.utils.time import utcnow

log = structlog.get_logger(__name__)

_DEFAULT_TTL_DAYS: Final[int] = 90


class TtlWatcher:
    trigger = RefreshTrigger.TTL

    def __init__(self, ttl_days: int = _DEFAULT_TTL_DAYS) -> None:
        self._ttl = timedelta(days=ttl_days)

    def discover(self, *, config: Config) -> list[tuple[str, dict[str, Any]]]:
        cutoff = utcnow() - self._ttl
        repo = CatalogRepo(config=config)
        out: list[tuple[str, dict[str, Any]]] = []
        for verdict in repo.list_verdicts():
            ts = verdict.generated_at
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            if ts < cutoff:
                pair = verdict.pair or (
                    (verdict.participants[0], verdict.participants[-1])
                    if verdict.participants
                    else None
                )
                if pair is None:
                    continue
                out.append(
                    (
                        f"{pair[0]}__{pair[1]}",
                        {"reason": "ttl_expired", "ttl_days": int(self._ttl.days)},
                    )
                )
        log.info("refresh.watcher.ttl.swept", found=len(out))
        return out


__all__ = ["TtlWatcher"]
