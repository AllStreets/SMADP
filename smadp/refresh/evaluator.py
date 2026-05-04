"""Refresh evaluator: drain one queued row, re-evaluate, save, emit events.

Synchronous wrapper over the async analyzer pipeline. Each call processes ONE
row (caller loops). On exception, the queue row is left claimed and the reaper
will release it after the 5-minute lease.
"""

from __future__ import annotations

import asyncio
from typing import Any, Final

import structlog

from smadp.analyzer.pipeline import generate_verdict
from smadp.catalog.repo import CatalogRepo, NotFoundError
from smadp.config import Config, load_config
from smadp.refresh import queue, state
from smadp.schemas.evidence import Evidence
from smadp.schemas.refresh import RefreshQueueItem, RefreshTrigger
from smadp.schemas.verdict import Verdict
from smadp.schemas.webhooks import EventType
from smadp.transparency.journal import append_event
from smadp.utils.time import utcnow
from smadp.webhooks.dispatcher import dispatch_event

log = structlog.get_logger(__name__)

_DEFAULT_WORKSPACE: Final[str] = "default"

_SUB_VERDICT_KEYS: Final[tuple[str, ...]] = (
    "A_prompt_injection",
    "B_data_leakage",
    "C_capability_conflict",
    "D_cascading_error",
    "E_compliance",
)


def _split_verdict_id(verdict_id: str) -> tuple[str, str]:
    if "__" not in verdict_id:
        raise ValueError(f"verdict_id must be 'slug_a__slug_b': {verdict_id!r}")
    a, b = verdict_id.split("__", 1)
    return a, b


def _save_verdict(*, verdict: Verdict, config: Config) -> None:
    repo = CatalogRepo(config=config)
    repo.save_verdict(verdict)


def _reload_inputs(
    *, slug_a: str, slug_b: str, config: Config
) -> dict[str, Any]:
    """Re-read profiles + dereference evidence used by the prior verdict.

    Returns a dict with keys ``profile_a``, ``profile_b``, ``evidence`` —
    passed verbatim to ``generate_verdict``.
    """
    repo = CatalogRepo(config=config)
    profile_a = repo.load_profile(slug_a)
    profile_b = repo.load_profile(slug_b)
    evidence: dict[str, Evidence] = {}
    try:
        existing = repo.load_verdict(slug_a, slug_b)
    except NotFoundError:
        existing = None
    if existing is not None:
        refs: set[str] = set()
        for key in _SUB_VERDICT_KEYS:
            sv = getattr(existing.sub_verdicts, key)
            for cit in sv.citations:
                if cit.evidence_ref:
                    refs.add(cit.evidence_ref)
        for ref in refs:
            try:
                evidence[ref] = repo.load_evidence(ref)
            except NotFoundError:
                continue
    return {"profile_a": profile_a, "profile_b": profile_b, "evidence": evidence}


def _signing_key(config: Config) -> Any:
    """Obtain a transparency signing key.

    Plan 4's ``smadp.transparency.keys.load_or_create_signing_key`` is preferred
    when available; otherwise we synthesize an ephemeral Ed25519 key. The
    transparency journal is content-addressable, so an ephemeral key remains
    verifiable locally for the lifetime of the run.
    """
    try:
        from smadp.transparency.keys import load_or_create_signing_key

        return load_or_create_signing_key(config=config)
    except (ImportError, AttributeError):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
        )

        return Ed25519PrivateKey.generate()


def _emit_transparency(
    *,
    event_type: str,
    payload: dict[str, Any],
    config: Config,
) -> None:
    append_event(
        event_type=event_type,
        payload=payload,
        signing_key=_signing_key(config),
        config=config,
    )


def _dispatch_verdict_updated(
    *,
    verdict: Verdict,
    trigger: RefreshTrigger,
    config: Config,
) -> None:
    payload = {
        "verdict_id": verdict.verdict_id,
        "pair": [verdict.pair[0], verdict.pair[1]],
        "composite_score": verdict.composite_score,
        "trigger": trigger.value,
    }
    dispatch_event(
        event_type=EventType.VERDICT_UPDATED,
        payload=payload,
        workspace_id=_DEFAULT_WORKSPACE,
        signature_meta={"source": "refresh.evaluator"},
        config=config,
    )


def drain_one(*, config: Config | None = None) -> RefreshQueueItem | None:
    """Process one queued refresh row. Returns the claimed item, or None."""
    cfg = config or load_config()
    item = queue.claim(config=cfg)
    if item is None:
        return None

    slug_a, slug_b = _split_verdict_id(item.verdict_id)
    log.info(
        "refresh.evaluator.start",
        verdict_id=item.verdict_id,
        trigger=item.trigger.value,
    )

    inputs = _reload_inputs(slug_a=slug_a, slug_b=slug_b, config=cfg)
    new_verdict = asyncio.run(
        generate_verdict(
            slug_a,
            slug_b,
            profile_a=inputs["profile_a"],
            profile_b=inputs["profile_b"],
            evidence=inputs["evidence"],
            config=cfg,
        )
    )
    _save_verdict(verdict=new_verdict, config=cfg)

    now = utcnow()
    state.upsert_state(
        verdict_id=item.verdict_id,
        trigger=item.trigger,
        evaluated_at=now,
        config=cfg,
    )

    _emit_transparency(
        event_type="verdict.updated",
        payload={
            "verdict_id": item.verdict_id,
            "trigger": item.trigger.value,
            "evaluated_at": now.isoformat(),
        },
        config=cfg,
    )
    _dispatch_verdict_updated(verdict=new_verdict, trigger=item.trigger, config=cfg)

    queue.finalize(item_id=item.id, config=cfg)
    log.info("refresh.evaluator.done", verdict_id=item.verdict_id)
    return item


__all__ = ["drain_one"]
