"""Shared base for fixture-driven stub watchers.

Each subclass sets ``trigger`` (RefreshTrigger) and ``fixture_name`` (str). The
base reads ``<cache_dir>/refresh_fixtures/<fixture_name>.json`` and returns
its contents — a JSON list of ``[verdict_id, detail_dict]`` pairs. A missing
file is not an error: it simply yields ``[]``. Production deployments will
replace these stubs with real integrations (GitHub release polling, OSV CVE
feed, etc.); the fixture-driven shape lets us deterministically test wiring.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

from smadp.config import Config
from smadp.schemas.refresh import RefreshTrigger


class FixtureWatcher:
    trigger: ClassVar[RefreshTrigger]
    fixture_name: ClassVar[str]

    def discover(self, *, config: Config) -> list[tuple[str, dict[str, Any]]]:
        path = config.cache_dir / "refresh_fixtures" / f"{self.fixture_name}.json"
        if not path.exists():
            return []
        raw = json.loads(path.read_text("utf-8"))
        out: list[tuple[str, dict[str, Any]]] = []
        for entry in raw:
            verdict_id, detail = entry
            out.append((str(verdict_id), dict(detail)))
        return out


__all__ = ["FixtureWatcher"]
