"""Capability-drift refresh hook (S2.2 integration).

On re-profile, diff the new profile against the on-disk one. If the capability
hash is unchanged the call is a no-op. Otherwise a ``CapabilityHistoryEntry`` is
appended (append-only) and the profile is saved. On any *expansion*: a
``capability_drift`` chronicle event is emitted, and every published verdict
touching that slug is flagged ``stale_reason="capability_drift"`` (surfaced,
never re-scored).
"""

from __future__ import annotations

from dataclasses import dataclass

from smadp.analyzer.capability_drift import capability_hash, diff_capabilities
from smadp.catalog.chronicle import Chronicle
from smadp.catalog.repo import CatalogRepo, NotFoundError
from smadp.config import Config
from smadp.schemas.profile import CapabilityHistoryEntry, Profile


@dataclass(frozen=True)
class DriftSummary:
    slug: str
    changed: bool
    expanded: bool
    staled_verdicts: int = 0
    summary: str = "no capability change"


def _version_string(profile: Profile) -> str:
    onexus = profile.onexus or {}
    version = onexus.get("version") if isinstance(onexus, dict) else None
    if isinstance(version, str) and version.strip():
        return version
    return profile.last_refreshed_at.date().isoformat()


def apply_capability_drift(*, config: Config, new_profile: Profile) -> DriftSummary:
    repo = CatalogRepo(config)
    try:
        old = repo.load_profile(new_profile.slug)
    except NotFoundError:
        # First time we see this slug: persist it; nothing to diff against.
        repo.save_profile(new_profile)
        return DriftSummary(slug=new_profile.slug, changed=False, expanded=False)

    if capability_hash(old) == capability_hash(new_profile):
        return DriftSummary(slug=new_profile.slug, changed=False, expanded=False)

    diff = diff_capabilities(old, new_profile)

    entry = CapabilityHistoryEntry(
        version=_version_string(new_profile),
        observed_at=new_profile.last_refreshed_at,
        capability_hash=capability_hash(new_profile),
        diff_summary=diff.summary[:600],
    )
    history = [*new_profile.capability_history, entry]
    updated = new_profile.model_copy(update={"capability_history": history})
    repo.save_profile(updated)

    staled = 0
    if diff.has_expansion:
        chronicle = Chronicle(config)
        chronicle.record(
            "capability_drift",
            by="autopilot",
            slug=new_profile.slug,
            details={
                "expansions": [c.field for c in diff.expansions],
                "summary": diff.summary,
            },
        )
        for verdict in repo.list_verdicts(slug=new_profile.slug):
            if verdict.stale_reason == "capability_drift":
                continue
            repo.save_verdict(verdict.model_copy(update={"stale_reason": "capability_drift"}))
            staled += 1

    return DriftSummary(
        slug=new_profile.slug,
        changed=True,
        expanded=diff.has_expansion,
        staled_verdicts=staled,
        summary=diff.summary,
    )
