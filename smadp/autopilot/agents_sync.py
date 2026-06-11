"""Nightly ONEXUS-Agents -> SMADP research bridge.

The ``onexus-agents-smadp-sync`` console script (shipped by the
onexus-agents-pipeline package) lands fresh runnable agents as seed
profiles under ``catalog/profiles/_unverified/``. That directory is a
staging buffer: SMADP's autopilot planners glob ``catalog/profiles/*.json``
non-recursively, so ``_unverified/`` entries are visible to the catalog
API and ``smadp lint`` but never enter the research queue on their own.

``sync_onexus`` closes that gap with three bounded, idempotent steps:

  1. Kill switch. If ``state/AGENTS_SYNC_DISABLED`` exists, do nothing.
  2. Promote. Move up to ``max_promote`` staged seeds (highest
     composite_score first) from ``_unverified/`` into ``catalog/profiles/``.
     A move (not a copy) keeps each slug in exactly one place, so
     ``smadp lint``'s duplicate-slug check stays green.
  3. Enqueue. Run the existing :class:`EnrichmentPlanner` over the promoted
     profiles and append the resulting work items to
     ``state/docs_only_queue.jsonl`` — the same queue the launchd
     ``docs-only-tick`` already drains. No new research machinery; the
     promoted agents simply become eligible for the enrichment judge.

This bridge is deliberately independent of the NEXUS catalog pipeline:
different repo, different machine path, its own file-based kill switch.
Neither can trigger or break the other.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from smadp.autopilot.bootstrap import _atomic_write
from smadp.autopilot.planners.enrichment import EnrichmentPlanner
from smadp.autopilot.work_queue import append_items

KILL_SWITCH = "AGENTS_SYNC_DISABLED"


@dataclass(frozen=True)
class SyncSummary:
    disabled: bool
    promoted: int
    queued: int
    staged_remaining: int


def _eligible(profile: dict[str, Any]) -> bool:
    """A staged seed can enter research once it carries the catalog
    provenance the EnrichmentPlanner keys on."""
    if profile.get("evidence_level") != "unverified-profile":
        return False
    return bool((profile.get("onexus") or {}).get("source_github"))


def sync_onexus(*, repo_root: Path, max_promote: int) -> SyncSummary:
    """Promote staged ONEXUS seeds into research, capped at max_promote."""
    state_dir = repo_root / "state"
    if (state_dir / KILL_SWITCH).exists():
        return SyncSummary(disabled=True, promoted=0, queued=0, staged_remaining=0)

    profiles_dir = repo_root / "catalog" / "profiles"
    staging_dir = profiles_dir / "_unverified"

    staged: list[tuple[float, Path, dict[str, Any]]] = []
    for path in sorted(staging_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not _eligible(data):
            continue
        # Don't promote a slug SMADP already researches.
        if (profiles_dir / path.name).exists():
            continue
        score = float(data.get("composite_score") or 0.0)
        staged.append((score, path, data))

    staged.sort(key=lambda t: t[0], reverse=True)
    selected = staged[: max(0, max_promote)]

    promoted: list[dict[str, Any]] = []
    for _score, path, data in selected:
        _atomic_write(profiles_dir / path.name, data)
        path.unlink()
        promoted.append(data)

    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    items = EnrichmentPlanner(top_n=len(promoted)).plan(profiles=promoted, now_iso=now)
    if items:
        append_items(state_dir / "docs_only_queue.jsonl", items)

    return SyncSummary(
        disabled=False,
        promoted=len(promoted),
        queued=len(items),
        staged_remaining=len(staged) - len(selected),
    )
