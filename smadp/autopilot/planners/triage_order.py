"""Shared triage-urgency helper for pair planners (S2.3 ordering).

``urgency = band_weight + uncertainty`` where band weights deprioritize
high-confidence-safe pairs and front-load uncertain/risky ones. Triage NEVER
writes a verdict and never changes eligibility — it only scales planner order.
"""

from __future__ import annotations

from typing import Any

from smadp.analyzer.triage import TriageModel
from smadp.schemas.profile import Profile

_BAND_WEIGHT = {"safe": 0.0, "low": 0.3, "medium": 0.7, "high": 1.0}


def _to_profile(p: dict[str, Any]) -> Profile | None:
    try:
        return Profile.model_validate(p)
    except ValueError:
        return None


def triage_urgency(model: TriageModel, p1: dict[str, Any], p2: dict[str, Any]) -> float:
    """Return the multiplicative urgency for one pair (>= 0).

    Falls back to a neutral 1.0 when either profile dict cannot be reconstructed
    into a ``Profile`` (triage must never crash or change eligibility).
    """
    pa = _to_profile(p1)
    pb = _to_profile(p2)
    if pa is None or pb is None:
        return 1.0
    pred = model.predict(pa, pb)
    band_weight = _BAND_WEIGHT.get(pred.band, 0.0)
    return band_weight + pred.uncertainty
