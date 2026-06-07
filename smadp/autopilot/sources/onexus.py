"""OnexusSource: yield raw agent records from the ONEXUS-Agents catalog.

Catalog layout: ``<root>/<category>/<slug>.json`` — flat per-category dirs of
agent JSON. Parse failures are logged and skipped, not raised, so a single
malformed file cannot abort an entire bootstrap run.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class RawOnexusAgent:
    slug: str
    name: str
    category: str
    tags: list[str]
    author_handle: str
    source_github: str | None
    source_homepage: str | None
    license: str | None
    composite_score: float
    runnable: bool


class OnexusSource:
    name = "onexus"

    def __init__(self, *, root: Path) -> None:
        self.root = root

    def fetch(self) -> Iterator[RawOnexusAgent]:
        if not self.root.exists():
            return
        for category_dir in sorted(self.root.iterdir()):
            if not category_dir.is_dir():
                continue
            if category_dir.name.startswith("_"):
                # ONEXUS uses underscore-prefixed dirs for metadata only.
                continue
            for json_path in sorted(category_dir.glob("*.json")):
                try:
                    raw = json.loads(json_path.read_text("utf-8"))
                    yield self._normalize(raw)
                except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                    log.warning(
                        "onexus.source.parse_skip",
                        path=str(json_path),
                        error=repr(exc),
                    )
                    continue

    @staticmethod
    def _normalize(raw: dict) -> RawOnexusAgent:
        source = raw.get("source") or {}
        author = raw.get("author") or {}
        return RawOnexusAgent(
            slug=str(raw["slug"]),
            name=str(raw.get("name", raw["slug"])),
            category=str(raw.get("category", "uncategorized")),
            tags=list(raw.get("tags") or []),
            author_handle=str(author.get("handle", "")),
            source_github=source.get("github"),
            source_homepage=source.get("homepage"),
            license=raw.get("license"),
            composite_score=float(raw.get("composite_score", 0.0)),
            runnable=bool(raw.get("runnable", False)),
        )
