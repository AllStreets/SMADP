"""bootstrap_onexus: one-shot importer + planner.

Reads the ONEXUS catalog, normalizes each record into an SMADP profile stub,
writes the profile JSON (skipping any file containing ``"manual": true``), then
runs EnrichmentPlanner against the resulting profile set and appends WorkItems
into ``state/docs_only_queue.jsonl``.

Each WorkItem requests ``profile_enrich`` so the enrichment judge fetches the
GitHub README and upgrades the stub to a full profile. Pair-judge work is only
enqueued later (via ``pair-gate-plan``) once both sides have been enriched.

Also folds in pre-existing SMADP profiles on disk so the top-N union covers
hand-curated agents (aider, cursor, etc.) that may have lower ONEXUS scores.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import structlog

from smadp.autopilot.planners.enrichment import EnrichmentPlanner
from smadp.autopilot.profilers.onexus import OnexusProfiler
from smadp.autopilot.sources.onexus import OnexusSource
from smadp.autopilot.work_queue import append_items

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class BootstrapSummary:
    profiles_written: int
    profiles_skipped: int
    pairs_queued: int


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise


def _existing_profile_has_manual_flag(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        return bool(json.loads(path.read_text("utf-8")).get("manual"))
    except (OSError, json.JSONDecodeError):
        return False


_ENRICHED_TIERS = {"docs-only", "profile-verified", "sandbox-validated"}


def _existing_profile_is_enriched(path: Path) -> bool:
    """True if the file is already at docs-only tier or higher.

    Without this guard, bootstrap would clobber LLM-enriched profiles back
    to bare stubs every time it runs. Enrichment is expensive; preserve it.
    """
    if not path.exists():
        return False
    try:
        return json.loads(path.read_text("utf-8")).get("evidence_level") in _ENRICHED_TIERS
    except (OSError, json.JSONDecodeError):
        return False


def _load_existing_profiles(profiles_dir: Path) -> list[dict]:
    if not profiles_dir.exists():
        return []
    out: list[dict] = []
    for path in profiles_dir.glob("*.json"):
        try:
            out.append(json.loads(path.read_text("utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return out


def bootstrap_onexus(
    *,
    repo_root: Path,
    onexus_root: Path,
    top_n: int,
    pair_cap: int,
) -> BootstrapSummary:
    source = OnexusSource(root=onexus_root)
    profiler = OnexusProfiler()
    profiles_dir = repo_root / "catalog" / "profiles"

    written = 0
    skipped = 0
    new_profiles: list[dict] = []
    for raw in source.fetch():
        path = profiles_dir / f"{raw.slug}.json"
        if _existing_profile_has_manual_flag(path):
            skipped += 1
            log.info("bootstrap.skip_manual", slug=raw.slug)
            continue
        if _existing_profile_is_enriched(path):
            skipped += 1
            log.info("bootstrap.skip_enriched", slug=raw.slug)
            continue
        profile = profiler.normalize(raw)
        _atomic_write(path, profile)
        new_profiles.append(profile)
        written += 1

    # Union with existing profiles for TopN — preserves hand-curated agents.
    union: dict[str, dict] = {}
    for p in _load_existing_profiles(profiles_dir):
        if not p.get("slug"):
            continue
        union[p["slug"]] = p
    # Slot in the freshly-written ones (in case a hand-curated one had no score):
    for p in new_profiles:
        union.setdefault(p["slug"], p)

    planner = EnrichmentPlanner(top_n=top_n)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    items = planner.plan(profiles=list(union.values()), now_iso=now)
    queue_path = repo_root / "state" / "docs_only_queue.jsonl"
    append_items(queue_path, items)

    return BootstrapSummary(
        profiles_written=written,
        profiles_skipped=skipped,
        pairs_queued=len(items),   # name preserved; semantically "items queued"
    )
