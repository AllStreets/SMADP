"""End-to-end Pairwise Analyzer pipeline.

The pipeline orchestrates:

1. Bundle assembly (rubric + both profiles + dereferenced evidence).
2. LLM-judge call.
3. Deterministic composite-score computation.
4. Reproducibility hashing of the inputs (profiles + evidence bundle).
5. Verdict assembly + Pydantic validation.
"""

from __future__ import annotations

from collections.abc import Mapping

import structlog

from smadp.analyzer.bundle import build_bundle
from smadp.analyzer.judge import judge_bundle
from smadp.analyzer.scoring import composite_score
from smadp.config import RUBRIC_VERSION, Config, load_config
from smadp.llm.client import LLMClient
from smadp.schemas.evidence import Evidence
from smadp.schemas.profile import Profile
from smadp.schemas.verdict import Reproducibility, Verdict, VerdictModel
from smadp.utils import sha256_canonical_json, sort_pair, utcnow, utcnow_iso

logger = structlog.get_logger(__name__)

_RUBRIC_URL_TEMPLATE = "/_meta/rubric/{version}.json"


class AnalyzerError(RuntimeError):
    """Raised when a Verdict cannot be produced or fails validation."""


async def generate_verdict(
    slug_a: str,
    slug_b: str,
    *,
    profile_a: Profile,
    profile_b: Profile,
    evidence: Mapping[str, Evidence],
    config: Config | None = None,
    llm: LLMClient | None = None,
) -> Verdict:
    """Generate a validated :class:`Verdict` for the pair (``slug_a``, ``slug_b``).

    The slugs may be passed in any order; the resulting Verdict is canonicalized
    so that ``pair[0] < pair[1]`` lexicographically. Evidence is supplied
    explicitly (keyed by either ``sha256:<hash>`` or bare ``<hash>``); the
    bundler will fall back to the catalog ``_evidence/`` directory if any
    referenced shas are missing from the mapping.

    Args:
        slug_a, slug_b: Slugs of the two agents (any order).
        profile_a, profile_b: Validated Profile objects (must match the slugs).
        evidence: Mapping providing every evidence sha referenced by either
            profile. Keys may be ``sha256:<hash>`` or just ``<hash>``.
        config: Optional Config; defaults to ``load_config()``.
        llm: Optional pre-built LLMClient; created from config otherwise.

    Returns:
        A validated :class:`Verdict`.

    Raises:
        AnalyzerError: When inputs disagree or the judge output cannot be
            assembled into a valid Verdict.
    """
    cfg = config or load_config()

    if profile_a.slug != slug_a or profile_b.slug != slug_b:
        raise AnalyzerError(
            "Profile slugs do not match the supplied pair: "
            f"got ({profile_a.slug!r}, {profile_b.slug!r}); "
            f"expected ({slug_a!r}, {slug_b!r})."
        )

    # Canonicalize pair order: profile_a holds slug_a, etc., but the on-disk
    # convention is alphabetized. We swap if needed for output assembly.
    canonical_a, canonical_b = sort_pair(slug_a, slug_b)
    swapped = canonical_a != slug_a
    if swapped:
        profile_a, profile_b = profile_b, profile_a

    bundle = build_bundle(
        profile_a=profile_a,
        profile_b=profile_b,
        config=cfg,
        explicit_evidence=evidence,
    )

    client = llm or LLMClient(config=cfg)
    try:
        judge_output = await judge_bundle(bundle, llm=client)
    except Exception as exc:
        raise AnalyzerError(f"Judge call failed: {exc}") from exc

    score = composite_score(judge_output.sub_verdicts)

    profile_a_hash = sha256_canonical_json(profile_a.model_dump(mode="json", exclude_none=True))
    profile_b_hash = sha256_canonical_json(profile_b.model_dump(mode="json", exclude_none=True))
    evidence_for_hash = {
        sha: ev.model_dump(mode="json", exclude_none=True)
        for sha, ev in sorted(bundle.all_evidence.items())
    }
    evidence_hash = sha256_canonical_json(evidence_for_hash)

    reproducibility = Reproducibility(
        rubric_url=_RUBRIC_URL_TEMPLATE.format(version=RUBRIC_VERSION),
        profile_a_hash=f"sha256:{profile_a_hash}",
        profile_b_hash=f"sha256:{profile_b_hash}",
        evidence_bundle_hash=f"sha256:{evidence_hash}",
    )

    # Verdict ID: v_YYYY-MM-DD_<a>__<b>_<short-hash>. Short hash derived from
    # the deterministic inputs so re-running the same pair on the same day
    # produces the same id.
    today = utcnow().strftime("%Y-%m-%d")
    short = sha256_canonical_json(
        {
            "a": profile_a_hash,
            "b": profile_b_hash,
            "ev": evidence_hash,
            "rubric": RUBRIC_VERSION,
            "model": client.model_id,
            "day": today,
        }
    )[:8]
    verdict_id = f"v_{today}_{canonical_a}__{canonical_b}_{short}"

    # The judge's evidence_level is a starting point; if either profile is
    # unverified we override to 'unverified-profile' (with a confidence haircut)
    # per the spec.
    evidence_level = judge_output.evidence_level
    confidence = judge_output.confidence
    if (
        profile_a.verification.status == "unverified"
        or profile_b.verification.status == "unverified"
    ):
        evidence_level = "unverified-profile"
        confidence = round(min(confidence, 0.6) * 0.85, 4)

    # Generated_at uses ISO with 'Z'; parse back through Pydantic via raw dict.
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "pair": (canonical_a, canonical_b),
        "verdict_id": verdict_id,
        "generated_at": utcnow_iso(),
        "model": VerdictModel(
            name=client.model_name,
            id=client.model_id,
            rubric_version=RUBRIC_VERSION,
        ).model_dump(),
        "evidence_level": evidence_level,
        "confidence": confidence,
        "composite_score": score,
        "headline": judge_output.headline,
        "sub_verdicts": judge_output.sub_verdicts.model_dump(),
        "framework_mappings": judge_output.framework_mappings,
        "reproducibility": reproducibility.model_dump(),
        "sandbox_runs": [],
    }

    try:
        verdict = Verdict.model_validate(payload)
    except Exception as exc:
        raise AnalyzerError(f"Verdict failed schema validation: {exc}") from exc

    logger.info(
        "analyzer.pipeline.ok",
        verdict_id=verdict.verdict_id,
        composite_score=verdict.composite_score,
        evidence_level=verdict.evidence_level,
    )
    return verdict
