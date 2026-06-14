"""Chain composer driver (S2.1 integration).

Walks authored chains (``catalog/chains/*.json`` — topology + participants +
edges), resolves each edge to a published pairwise ``Verdict`` (``present=False``
when the verdict is missing), runs the deterministic :func:`compose_chain`, and
writes a *composed chain candidate* into ``catalog/pending/chains/``.

Python produces every number on the candidate (composite, confidence,
max severity). The LLM judge never runs here. Candidates whose composed
confidence falls below the publish threshold are counted as ``needs_judge`` for
the bounded confirmation batch (Task 9). The operator promotes a candidate via
``approve_chain`` (Task 10). Honors the ``chain_composition`` kill switch.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Protocol

from smadp.analyzer.chains import ComposedChain, LinkInput, compose_chain
from smadp.analyzer.chains import _composite_from_bands as _composite_from_bands
from smadp.autopilot.config import AutopilotConfig
from smadp.catalog.chronicle import Chronicle
from smadp.catalog.repo import CatalogRepo, NotFoundError
from smadp.config import Config
from smadp.schemas.chain import Chain, Edge
from smadp.schemas.verdict import Verdict
from smadp.utils.slug import sort_pair
from smadp.utils.time import utcnow

_RISK_KEYS = (
    "A_prompt_injection",
    "B_data_leakage",
    "C_capability_conflict",
    "D_cascading_error",
    "E_compliance",
)
COMPOSITION_METHOD = "deterministic-v1"


@dataclass(frozen=True)
class ComposeSummary:
    disabled: bool
    composed: int
    needs_judge: int


def _link_for_edge(repo: CatalogRepo, edge: Edge) -> LinkInput:
    """Resolve one authored edge to a LinkInput from its pairwise verdict.

    Self-loop edges (from == to) have no pairwise verdict; they are returned as
    a present=False placeholder so the missing-link penalty applies.
    """
    if edge.from_ == edge.to:
        return LinkInput(
            from_slug=edge.from_, to_slug=edge.to,
            severities={k: "none" for k in _RISK_KEYS},
            confidence=0.0, present=False, carries=list(edge.carries),
        )
    a, b = sort_pair(edge.from_, edge.to)
    try:
        verdict: Verdict = repo.load_verdict(a, b)
    except NotFoundError:
        return LinkInput(
            from_slug=edge.from_, to_slug=edge.to,
            severities={k: "none" for k in _RISK_KEYS},
            confidence=0.0, present=False, carries=list(edge.carries),
        )
    sv = verdict.sub_verdicts
    return LinkInput(
        from_slug=edge.from_, to_slug=edge.to,
        severities={
            "A_prompt_injection": sv.A_prompt_injection.severity,
            "B_data_leakage": sv.B_data_leakage.severity,
            "C_capability_conflict": sv.C_capability_conflict.severity,
            "D_cascading_error": sv.D_cascading_error.severity,
            "E_compliance": sv.E_compliance.severity,
        },
        confidence=verdict.confidence,
        present=True,
        carries=list(edge.carries),
    )


def _composed_from(repo: CatalogRepo, chain: Chain) -> list[str]:
    refs: list[str] = []
    for edge in chain.edges:
        if edge.from_ == edge.to:
            continue
        a, b = sort_pair(edge.from_, edge.to)
        try:
            verdict = repo.load_verdict(a, b)
        except NotFoundError:
            continue
        if verdict.verdict_id not in refs:
            refs.append(verdict.verdict_id)
    return refs


def compose_chain_candidate(repo: CatalogRepo, chain: Chain) -> tuple[Chain, ComposedChain]:
    """Compose one authored chain into a candidate Chain (pure; no write)."""
    links = [_link_for_edge(repo, edge) for edge in chain.edges]
    node_count = len({p.slug for p in chain.participants})
    composed = compose_chain(topology=chain.topology, links=links, node_count=node_count)

    candidate = chain.model_copy(
        update={
            "schema_version": "1.1",
            "composite_score": composed.composite,
            "confidence": composed.confidence,
            "max_severity": composed.max_severity,
            "composition_method": COMPOSITION_METHOD,
            "composed_from": _composed_from(repo, chain),
            "last_refreshed_at": utcnow(),
        }
    )
    return candidate, composed


def compose_authored_chains(
    *, repo_root, config: Config, autopilot_cfg: AutopilotConfig
) -> ComposeSummary:
    if not autopilot_cfg.chain_composition_enabled:
        return ComposeSummary(disabled=True, composed=0, needs_judge=0)

    repo = CatalogRepo(config)
    chronicle = Chronicle(config)
    threshold = autopilot_cfg.chain_publish_confidence_threshold

    composed_count = 0
    needs_judge = 0
    for chain in repo.list_chains():
        if not chain.edges:
            continue
        candidate, composed = compose_chain_candidate(repo, chain)
        repo.save_pending_chain(candidate)
        composed_count += 1
        flagged = composed.confidence < threshold
        if flagged:
            needs_judge += 1
        chronicle.record(
            "chain.created",
            by="autopilot",
            details={
                "chain_id": candidate.chain_id,
                "composition_method": COMPOSITION_METHOD,
                "confidence": composed.confidence,
                "needs_judge": flagged,
            },
        )
    return ComposeSummary(disabled=False, composed=composed_count, needs_judge=needs_judge)


# --------------------------------------------------------------------------
# Task 9 — bounded LLM confirmation batch for low-confidence chains.
#
# The judge may only return narrative + symbolic per-risk bands. Python keeps
# every number: the symbolic bands are fed back through ``_composite_from_bands``
# so the composite is still computed deterministically in Python.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ChainJudgement:
    """Symbols-only output of the chain judge (no numbers)."""

    severities: dict[str, str]
    headline: str = ""


class ChainJudge(Protocol):
    async def confirm_chain(self, candidate: Chain) -> ChainJudgement: ...


@dataclass(frozen=True)
class JudgeSummary:
    disabled: bool
    judged: int
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


def _normalize_bands(raw: dict[str, str]) -> dict[str, str]:
    """Validate + fill the five risk bands the judge returned (symbols only)."""
    out: dict[str, str] = {}
    for key in _RISK_KEYS:
        band = raw.get(key, "none")
        if band not in ("none", "low", "medium", "high", "critical"):
            band = "none"
        out[key] = band
    return out


async def confirm_low_confidence_chains_async(
    *, repo_root, config: Config, autopilot_cfg: AutopilotConfig, judge: ChainJudge
) -> JudgeSummary:
    if not autopilot_cfg.chain_composition_enabled:
        return JudgeSummary(disabled=True, judged=0)

    repo = CatalogRepo(config)
    chronicle = Chronicle(config)
    threshold = autopilot_cfg.chain_publish_confidence_threshold
    batch_max = autopilot_cfg.chain_judge_batch_max

    # Worst-first: lowest confidence at the front.
    flagged = [
        c
        for c in repo.list_pending_chains()
        if c.confidence is not None and c.confidence < threshold
    ]
    flagged.sort(key=lambda c: (c.confidence if c.confidence is not None else 0.0))

    judged = 0
    skipped = 0
    errors: list[str] = []
    for candidate in flagged:
        if judged >= batch_max:
            skipped += 1
            continue
        try:
            judgement = await judge.confirm_chain(candidate)
        except Exception as exc:  # noqa: BLE001 - one bad chain must not kill the batch
            errors.append(f"{candidate.chain_id}: {exc}")
            continue
        bands = _normalize_bands(judgement.severities)
        # Python recomputes the composite from the judge's symbolic bands.
        composite = _composite_from_bands(bands)
        max_sev = max(
            bands.values(),
            key=("none", "low", "medium", "high", "critical").index,
        )
        updated = candidate.model_copy(
            update={
                "composite_score": composite,
                "max_severity": max_sev,
                "headline": judgement.headline or candidate.headline,
                "last_refreshed_at": utcnow(),
            }
        )
        repo.save_pending_chain(updated)
        judged += 1
        chronicle.record(
            "chain.created",
            by="autopilot",
            details={
                "chain_id": updated.chain_id,
                "judged": True,
                "composite_score": composite,
            },
        )
    return JudgeSummary(disabled=False, judged=judged, skipped=skipped, errors=errors)


def confirm_low_confidence_chains(
    *, repo_root, config: Config, autopilot_cfg: AutopilotConfig, judge: ChainJudge
) -> JudgeSummary:
    """Synchronous wrapper mirroring ``refresh/evaluator.py``."""
    return asyncio.run(
        confirm_low_confidence_chains_async(
            repo_root=repo_root, config=config, autopilot_cfg=autopilot_cfg, judge=judge
        )
    )
