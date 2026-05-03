"""Assemble the LLM-judge input bundle from two Profiles + their evidence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import structlog

from smadp.config import Config
from smadp.schemas.evidence import Evidence
from smadp.schemas.profile import Profile

logger = structlog.get_logger(__name__)

_EVIDENCE_PREFIX = "sha256:"
EVIDENCE_FILENAME_TEMPLATE = "sha256-{sha}.json"


@dataclass(frozen=True)
class JudgeBundle:
    """Inputs to a single pairwise judge call."""

    rubric: dict[str, Any]
    profile_a: Profile
    profile_b: Profile
    evidence_a: dict[str, Evidence]
    evidence_b: dict[str, Evidence]

    @property
    def all_evidence(self) -> dict[str, Evidence]:
        """Union of both agents' evidence, keyed by sha (no ``sha256:`` prefix)."""
        merged: dict[str, Evidence] = {}
        merged.update(self.evidence_a)
        merged.update(self.evidence_b)
        return merged


def load_evidence_for_profile(
    profile: Profile,
    *,
    evidence_dir: Path,
    explicit: Mapping[str, Evidence] | None = None,
) -> dict[str, Evidence]:
    """Resolve every ``sha256:`` ref on the profile to an :class:`Evidence`.

    If ``explicit`` is supplied, items are looked up there first (useful for
    in-memory pipelines/tests). Refs that resolve nowhere raise.
    """
    resolved: dict[str, Evidence] = {}
    for ref in profile.evidence_refs:
        if not ref.startswith(_EVIDENCE_PREFIX):
            raise ValueError(f"Profile {profile.slug!r} has invalid evidence ref {ref!r}")
        sha = ref[len(_EVIDENCE_PREFIX) :]
        if explicit and ref in explicit:
            resolved[sha] = explicit[ref]
            continue
        if explicit and sha in explicit:
            resolved[sha] = explicit[sha]
            continue
        path = evidence_dir / EVIDENCE_FILENAME_TEMPLATE.format(sha=sha)
        if not path.exists():
            raise FileNotFoundError(
                f"Profile {profile.slug!r} references {ref} but {path} is missing."
            )
        resolved[sha] = Evidence.model_validate_json(path.read_text(encoding="utf-8"))
    return resolved


def build_bundle(
    *,
    profile_a: Profile,
    profile_b: Profile,
    config: Config,
    explicit_evidence: Mapping[str, Evidence] | None = None,
) -> JudgeBundle:
    """Load the rubric and dereference both profiles' evidence into a Bundle."""
    rubric_path = config.rubric_path
    if not rubric_path.exists():
        raise FileNotFoundError(f"Rubric not found at {rubric_path}")
    rubric = json.loads(rubric_path.read_text(encoding="utf-8"))

    evidence_a = load_evidence_for_profile(
        profile_a, evidence_dir=config.evidence_dir, explicit=explicit_evidence
    )
    evidence_b = load_evidence_for_profile(
        profile_b, evidence_dir=config.evidence_dir, explicit=explicit_evidence
    )
    logger.info(
        "analyzer.bundle.built",
        slug_a=profile_a.slug,
        slug_b=profile_b.slug,
        evidence_a=len(evidence_a),
        evidence_b=len(evidence_b),
    )
    return JudgeBundle(
        rubric=rubric,
        profile_a=profile_a,
        profile_b=profile_b,
        evidence_a=evidence_a,
        evidence_b=evidence_b,
    )


def evidence_bundle_for_prompt(bundle: JudgeBundle) -> dict[str, dict[str, str]]:
    """Project the bundle's evidence into the dict shape the judge prompt expects."""
    out: dict[str, dict[str, str]] = {}
    for sha, ev in bundle.all_evidence.items():
        out[f"sha256:{sha}"] = {
            "source_url": str(ev.source_url),
            "media_type": ev.media_type,
            "quote": ev.quote,
            "context": ev.context or "",
        }
    return out
