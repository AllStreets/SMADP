"""Docs-only tick: drain work queue → dispatch to right judge → publish.

Multi-judge dispatch: the caller passes a ``judges`` mapping
``{requested_judge_name: judge_instance}``. Each WorkItem is routed to the
judge whose name matches ``item.requested_judge``. The publisher writes to
``catalog/profiles/`` for enrichment judges (judge.name == "profile_enrich")
and to ``catalog/verdicts/`` (or pending/) for pair judges.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from smadp.autopilot.approve import ApproveError, approve
from smadp.autopilot.budget import (
    can_enqueue,
    load_budget,
    record_run_actual,
)
from smadp.autopilot.config import load_autopilot_config
from smadp.autopilot.judges import Judge
from smadp.autopilot.pause import is_paused
from smadp.autopilot.publishers.policy import PolicyPublisher
from smadp.autopilot.work_queue import drain_items, read_all_items

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class DocsOnlyTickSummary:
    published: int
    failed: int
    reason: str  # "ok" | "paused" | "budget_exhausted" | "no_work"
    auto_published: int = 0  # of `published`, how many cleared the high-confidence lane


def _load_profiles(profiles_dir: Path) -> dict[str, dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}
    if not profiles_dir.exists():
        return profiles
    for path in profiles_dir.glob("*.json"):
        try:
            profile = json.loads(path.read_text("utf-8"))
        except json.JSONDecodeError:
            continue
        slug = profile.get("slug") or path.stem
        profiles[slug] = profile
    return profiles


def _log_failure(state_dir: Path, *, pair: tuple[str, str], judge_name: str, error: str) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    row = {
        "pair": list(pair),
        "judge": judge_name,
        "error": error,
        "attempted_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    with (state_dir / "judge_errors.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def _publish(publisher: PolicyPublisher, judge_name: str, output: dict[str, Any]) -> Path:
    if judge_name == "profile_enrich":
        return publisher.commit_profile(output)
    return publisher.commit(output)


def _persist_evidence_chunk(evidence_dir: Path, chunk: dict[str, str]) -> None:
    """Write one README chunk to catalog/_evidence/sha256-<hash>.json.

    Skips chunks that are already on disk (sha-addressed, so identical
    content is content-addressed-stable). Safe to call repeatedly.
    """
    sha = chunk.get("sha")
    if not sha:
        return
    evidence_dir.mkdir(parents=True, exist_ok=True)
    target = evidence_dir / f"sha256-{sha}.json"
    if target.exists():
        return
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "sha256": sha,
        "source_url": chunk.get("source_url", ""),
        "fetched_at": now,
        "fetcher": "smadp.autopilot.profile_enrich.v1",
        "media_type": chunk.get("media_type", "text/markdown"),
        "quote": chunk.get("quote", ""),
        "context": chunk.get("context"),
    }
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(target)


def run_docs_only_tick(
    *,
    repo_root: Path,
    judges: Mapping[str, Judge],
    batch_size: int = 10,
) -> DocsOnlyTickSummary:
    state_dir = repo_root / "state"
    queue_path = state_dir / "docs_only_queue.jsonl"

    if is_paused(state_dir):
        log.info("docs_only_tick.paused")
        return DocsOnlyTickSummary(published=0, failed=0, reason="paused")

    cfg = load_autopilot_config(repo_root / "config" / "autopilot.yaml")
    budget_path = state_dir / "budget.json"
    budget = load_budget(budget_path)

    if budget.runs_today >= cfg.runs_per_day:
        return DocsOnlyTickSummary(published=0, failed=0, reason="budget_exhausted")
    if budget.dollars_today >= cfg.dollars_per_day:
        return DocsOnlyTickSummary(published=0, failed=0, reason="budget_exhausted")

    items = read_all_items(queue_path)
    if not items:
        return DocsOnlyTickSummary(published=0, failed=0, reason="no_work")

    profiles = _load_profiles(repo_root / "catalog" / "profiles")
    # All autopilot output routes to catalog/pending/ now. Promotion to
    # catalog/verdicts/ (the public catalog the site indexes) requires a
    # human gate via `smadp pending approve` (single or batch). This is
    # the review point — autopilot keeps producing freely, the operator
    # decides what's posted.
    publisher = PolicyPublisher(
        catalog_root=repo_root / "catalog",
        auto_publish={
            "docs-only": False,
            "profile-verified": False,
            "sandbox-validated": False,
            "sandbox-run": False,
        },
    )

    max_cost = max(
        (float(getattr(j, "cost_per_call_usd", 0.04)) for j in judges.values()),
        default=0.04,
    )
    cap_by_runs = cfg.runs_per_day - budget.runs_today
    cap_by_dollars = int(max(0, (cfg.dollars_per_day - budget.dollars_today) // max_cost))
    effective = max(0, min(batch_size, cap_by_runs, cap_by_dollars))

    drained = drain_items(queue_path, limit=effective)
    published = 0
    failed = 0
    auto_published = 0
    auto_min = cfg.auto_publish_docs_only_min_confidence
    for work in drained:
        judge = judges.get(work.requested_judge)
        if judge is None:
            failed += 1
            _log_failure(
                state_dir,
                pair=work.pair,
                judge_name=work.requested_judge,
                error=f"no judge registered for {work.requested_judge!r}",
            )
            continue
        cost_per_call = float(getattr(judge, "cost_per_call_usd", 0.04))
        if not can_enqueue(load_budget(budget_path), cfg, expected_cost=cost_per_call):
            break
        try:
            result = judge.evaluate(work, profiles=profiles)
            # Persist any evidence the judge produced so the refs the verdict
            # carries are resolvable by `smadp validate`. Without this step
            # docs-only enrichments accumulate orphan evidence refs.
            for chunk in getattr(result, "evidence", []) or []:
                _persist_evidence_chunk(repo_root / "catalog" / "_evidence", chunk)
            published_path = _publish(publisher, str(judge.name), result.verdict)
            record_run_actual(budget_path, dollars=float(result.cost_usd))
            published += 1
            # High-confidence auto-publish lane: a strong docs-only verdict is
            # promoted straight past the operator gate (signed via the normal
            # approve path) so the public catalog keeps growing unattended. Weaker
            # verdicts remain in pending/ for human review. Profiles never auto-
            # promote. Best-effort: a promotion failure leaves it safely in pending.
            if (
                auto_min > 0.0
                and str(judge.name) != "profile_enrich"
                and float(result.verdict.get("confidence") or 0.0) >= auto_min
            ):
                try:
                    approve(key=published_path.stem, repo_root=repo_root)
                    auto_published += 1
                except ApproveError as exc:
                    log.warning(
                        "docs_only_tick.auto_publish_failed",
                        key=published_path.stem,
                        error=repr(exc),
                    )
        except Exception as exc:
            failed += 1
            _log_failure(
                state_dir,
                pair=work.pair,
                judge_name=str(getattr(judge, "name", work.requested_judge)),
                error=repr(exc),
            )
            log.warning("docs_only_tick.judge_failed", pair=work.pair, error=repr(exc))
    if published == 0 and failed == 0:
        return DocsOnlyTickSummary(published=0, failed=0, reason="no_work")
    return DocsOnlyTickSummary(
        published=published, failed=failed, reason="ok", auto_published=auto_published
    )
