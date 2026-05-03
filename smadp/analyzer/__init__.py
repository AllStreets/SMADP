"""Pairwise Analyzer: turn two Profiles into a cited, scored Verdict."""

from smadp.analyzer.bundle import JudgeBundle, build_bundle, load_evidence_for_profile
from smadp.analyzer.pipeline import AnalyzerError, generate_verdict
from smadp.analyzer.scoring import (
    SEVERITY_SCORES,
    WEIGHTS,
    composite_score,
    severity_to_score,
)

__all__ = [
    "AnalyzerError",
    "JudgeBundle",
    "SEVERITY_SCORES",
    "WEIGHTS",
    "build_bundle",
    "composite_score",
    "generate_verdict",
    "load_evidence_for_profile",
    "severity_to_score",
]
