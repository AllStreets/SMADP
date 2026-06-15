"""LLM-judge invocation for one Bundle. Produces validated SubVerdicts.

The judge call returns a structured payload with:

- ``headline`` (str)
- ``evidence_level`` (one of the enum)
- ``confidence`` (float)
- ``sub_verdicts`` (the five risk objects)
- ``framework_mappings`` (dict)

This module returns that payload (validated) plus the parsed
:class:`SubVerdicts`. The pipeline assembles the final Verdict.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import structlog

from smadp.analyzer.bundle import JudgeBundle, evidence_bundle_for_prompt
from smadp.llm.client import LLMClient
from smadp.llm.prompts import pairwise_judge
from smadp.schemas.verdict import EvidenceLevel, SubVerdicts

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class JudgeOutput:
    """Validated, parsed result of one pairwise judge call."""

    headline: str
    evidence_level: EvidenceLevel
    confidence: float
    sub_verdicts: SubVerdicts
    framework_mappings: dict[str, list[str]]
    raw: dict[str, Any]
    """The raw tool-input dict the model produced (kept for diagnostics)."""


async def judge_bundle(bundle: JudgeBundle, *, llm: LLMClient) -> JudgeOutput:
    """Run the pairwise judge on ``bundle`` and return parsed sub-verdicts."""
    payload = pairwise_judge.JudgeInput(
        rubric_json=json.dumps(bundle.rubric, sort_keys=True, indent=2, ensure_ascii=False),
        profile_a_json=_profile_to_prompt_json(bundle, "agent_a"),
        profile_b_json=_profile_to_prompt_json(bundle, "agent_b"),
        evidence_bundle_json=pairwise_judge.serialize_evidence_bundle(
            evidence_bundle_for_prompt(bundle)
        ),
    )
    result = await llm.judge_pair(payload)
    raw = dict(result.tool_input)

    headline = str(raw.get("headline", "")).strip()
    if not headline:
        raise ValueError("Judge output missing 'headline'.")
    evidence_level = raw.get("evidence_level")
    if evidence_level not in (
        "unverified-profile",
        "docs-only",
        "behavior-observed",
        "profile-verified",
        "sandbox-validated",
    ):
        raise ValueError(f"Judge output has invalid evidence_level: {evidence_level!r}")
    confidence_raw = raw.get("confidence", 0.0)
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Judge output has non-numeric confidence: {confidence_raw!r}") from exc
    confidence = max(0.0, min(1.0, confidence))

    sub_verdicts_payload = raw.get("sub_verdicts")
    if not isinstance(sub_verdicts_payload, dict):
        raise ValueError("Judge output is missing 'sub_verdicts' object.")
    sub_verdicts = SubVerdicts.model_validate(sub_verdicts_payload)

    framework_mappings_raw = raw.get("framework_mappings") or {}
    framework_mappings: dict[str, list[str]] = {}
    if isinstance(framework_mappings_raw, dict):
        for key, value in framework_mappings_raw.items():
            if isinstance(value, list):
                framework_mappings[str(key)] = [str(v) for v in value]

    logger.info(
        "analyzer.judge.ok",
        slug_a=bundle.profile_a.slug,
        slug_b=bundle.profile_b.slug,
        evidence_level=evidence_level,
        confidence=confidence,
        usage=result.usage,
    )
    return JudgeOutput(
        headline=headline[:240],
        evidence_level=evidence_level,
        confidence=confidence,
        sub_verdicts=sub_verdicts,
        framework_mappings=framework_mappings,
        raw=raw,
    )


def _profile_to_prompt_json(bundle: JudgeBundle, role: str) -> str:
    """Render one profile as JSON, prefixed with its role label for the prompt."""
    profile = bundle.profile_a if role == "agent_a" else bundle.profile_b
    payload = {role: profile.model_dump(mode="json", exclude_none=True)}
    return json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False)
