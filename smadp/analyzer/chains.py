"""Deterministic N-agent chain composition over pairwise verdicts.

The LLM judge never runs here. Given each adjacent link's published pairwise
sub-verdict severities plus the chain topology, this module computes the
composed per-risk severities, composite score, and confidence with fixed rules:

* link risk = the adjacent pair's pairwise sub-severities;
* **D** (cascading error) compounds along path length: +1 band per hop beyond
  2 nodes, capped at ``critical``; a loop topology adds one extra D band;
* **B** (data leakage) = max over links sharing a carried data class
  (fallback: plain max when no link carries a data class);
* **A / C / E** = plain max over present links;
* confidence = ``min(present link confidences) * (1 - 0.15 * missing_links)``,
  clamped to ``[0, 1]``.

All numbers are produced here in Python, honoring the deterministic-composite
contract. The composite score reuses the canonical pairwise weights.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from smadp.analyzer.scoring import composite_score as _pairwise_composite
from smadp.schemas.verdict import SubVerdict, SubVerdicts

SEVERITY_BANDS: tuple[str, ...] = ("none", "low", "medium", "high", "critical")
_MISSING_LINK_PENALTY = 0.15


def bump_band(band: str, by: int) -> str:
    idx = min(SEVERITY_BANDS.index(band) + max(0, by), len(SEVERITY_BANDS) - 1)
    return SEVERITY_BANDS[idx]


def _max_band(bands: list[str]) -> str:
    if not bands:
        return "none"
    return max(bands, key=SEVERITY_BANDS.index)


@dataclass(frozen=True)
class LinkInput:
    from_slug: str
    to_slug: str
    severities: dict[str, str]  # risk key -> band
    confidence: float
    present: bool
    carries: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ComposedChain:
    severities: dict[str, str]
    composite: float
    confidence: float
    missing_links: int
    max_severity: str


def _compose_B(links: list[LinkInput]) -> str:
    classed = [link for link in links if link.carries]
    if not classed:
        return _max_band([link.severities["B_data_leakage"] for link in links])
    by_class: dict[str, list[str]] = {}
    for link in classed:
        for dc in link.carries:
            by_class.setdefault(dc, []).append(link.severities["B_data_leakage"])
    untagged = [link.severities["B_data_leakage"] for link in links if not link.carries]
    group_maxes = [_max_band(v) for v in by_class.values()] + (
        [_max_band(untagged)] if untagged else [])
    return _max_band(group_maxes)


def compose_chain(*, topology: str, links: list[LinkInput], node_count: int) -> ComposedChain:
    present = [link for link in links if link.present]
    missing = sum(1 for link in links if not link.present)

    sev: dict[str, str] = {}
    for key in ("A_prompt_injection", "C_capability_conflict", "E_compliance"):
        sev[key] = _max_band([link.severities[key] for link in present]) if present else "none"

    sev["B_data_leakage"] = _compose_B(present) if present else "none"

    base_d = (
        _max_band([link.severities["D_cascading_error"] for link in present])
        if present
        else "none"
    )
    hops_beyond_two = max(0, node_count - 2)
    loop_bonus = 1 if topology == "loop" else 0
    sev["D_cascading_error"] = bump_band(base_d, hops_beyond_two + loop_bonus)

    confidences = [link.confidence for link in present]
    base_conf = min(confidences) if confidences else 0.0
    conf = max(0.0, min(1.0, base_conf * (1.0 - _MISSING_LINK_PENALTY * missing)))

    composite = _composite_from_bands(sev)
    return ComposedChain(
        severities=sev,
        composite=composite,
        confidence=round(conf, 4),
        missing_links=missing,
        max_severity=_max_band(list(sev.values())),
    )


def _composite_from_bands(sev: dict[str, str]) -> float:
    """Reuse the canonical pairwise weights via a synthetic SubVerdicts."""
    def _sv(band: str) -> SubVerdict:
        return SubVerdict(
            severity=band,  # type: ignore[arg-type]
            rationale="composed",
            citations=[{"quote": "composed"}],  # type: ignore[list-item]
        )

    sub = SubVerdicts(
        A_prompt_injection=_sv(sev["A_prompt_injection"]),
        B_data_leakage=_sv(sev["B_data_leakage"]),
        C_capability_conflict=_sv(sev["C_capability_conflict"]),
        D_cascading_error=_sv(sev["D_cascading_error"]),
        E_compliance=_sv(sev["E_compliance"]),
    )
    return _pairwise_composite(sub)
