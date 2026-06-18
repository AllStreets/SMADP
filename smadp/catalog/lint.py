"""Catalog linter: schema + Pydantic + cross-reference validation.

Run from the CLI as `smadp validate` (alias `smadp lint`). Returns a
structured `LintReport` so the CLI / API can render it however they want.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from pydantic import ValidationError

from smadp.catalog.repo import CatalogRepo
from smadp.config import Config, load_config
from smadp.schemas import Chain, Evidence, Profile, Verdict
from smadp.utils.slug import sort_pair


@dataclass(frozen=True)
class LintIssue:
    severity: str  # "error" | "warning"
    kind: str  # e.g. "profile.schema", "verdict.cross-ref"
    target: str  # path or slug or pair identifier
    message: str


@dataclass
class LintReport:
    profiles_checked: int = 0
    verdicts_checked: int = 0
    evidence_checked: int = 0
    chains_checked: int = 0
    issues: list[LintIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[LintIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[LintIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def add(self, severity: str, kind: str, target: str, message: str) -> None:
        self.issues.append(LintIssue(severity, kind, target, message))


def _load_schema(path: Path) -> Draft202012Validator | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as fh:
        schema = json.load(fh)
    return Draft202012Validator(schema)


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return None
        return data
    except (OSError, json.JSONDecodeError):
        return None


def lint_catalog(config: Config | None = None) -> LintReport:
    """Validate every profile, verdict, and evidence file in the catalog."""
    cfg = config or load_config()
    CatalogRepo(cfg)
    report = LintReport()

    profile_validator = _load_schema(cfg.schema_dir / "profile.schema.json")
    # Tier-aware: autopilot-bootstrapped stubs carry evidence_level
    # ``unverified-profile`` and don't yet have the full Safety Profile shape.
    # They validate against a minimal schema until enrichment lifts them to
    # docs-only (or higher).
    unverified_profile_validator = _load_schema(cfg.schema_dir / "profile.unverified.schema.json")
    verdict_validator = _load_schema(cfg.schema_dir / "verdict.schema.json")
    evidence_validator = _load_schema(cfg.schema_dir / "evidence.schema.json")

    # ----------------------------------------------------------- profiles
    profile_slugs: set[str] = set()
    profile_evidence_refs: set[str] = set()
    profile_pairings: dict[str, list[str]] = {}
    profile_dirs = [cfg.profiles_dir, cfg.unverified_profiles_dir]
    for profile_dir in profile_dirs:
        if not profile_dir.exists():
            continue
        for path in sorted(profile_dir.glob("*.json")):
            report.profiles_checked += 1
            target = str(path)
            data = _load_json(path)
            if data is None:
                report.add("error", "profile.parse", target, "could not parse JSON")
                continue
            tier = data.get("evidence_level")
            if tier == "unverified-profile":
                # Stubs are autopilot-bootstrapped from ONEXUS records and
                # don't yet have the full Safety Profile fields (vendor,
                # source_type, sandboxing, etc.) — those land at enrichment
                # time. Validate against the relaxed schema only; skip the
                # full Pydantic model since the stub shape is constructed in
                # code and known-valid by construction.
                if unverified_profile_validator is not None:
                    for err in unverified_profile_validator.iter_errors(data):
                        report.add(
                            "error",
                            "profile.unverified-schema",
                            target,
                            f"{'/'.join(str(p) for p in err.absolute_path)}: {err.message}",
                        )
                slug = data.get("slug")
                if not isinstance(slug, str):
                    report.add("error", "profile.unverified-schema", target, "slug missing")
                    continue
                if path.stem != slug:
                    report.add(
                        "error",
                        "profile.filename",
                        target,
                        f"filename {path.stem!r} does not match slug {slug!r}",
                    )
                if slug in profile_slugs:
                    report.add(
                        "error",
                        "profile.duplicate",
                        slug,
                        f"slug {slug!r} appears in multiple files",
                    )
                profile_slugs.add(slug)
                # Track pairings/evidence_refs so cross-refs against a
                # full-tier profile still resolve. The stub may have an
                # empty pairings list or a partial one — that's still the
                # source of truth for whether reciprocation holds.
                pairings = data.get("pairings") or []
                if isinstance(pairings, list):
                    profile_pairings[slug] = [p for p in pairings if isinstance(p, str)]
                refs = data.get("evidence_refs") or []
                if isinstance(refs, list):
                    for ref in refs:
                        if isinstance(ref, str):
                            profile_evidence_refs.add(ref)
                continue
            else:
                if profile_validator is not None:
                    for err in profile_validator.iter_errors(data):
                        report.add(
                            "error",
                            "profile.schema",
                            target,
                            f"{'/'.join(str(p) for p in err.absolute_path)}: {err.message}",
                        )
                try:
                    profile = Profile.model_validate(data)
                except ValidationError as exc:
                    report.add("error", "profile.pydantic", target, str(exc))
                    continue
            # Check filename matches slug
            if path.stem != profile.slug:
                report.add(
                    "error",
                    "profile.filename",
                    target,
                    f"filename {path.stem!r} does not match slug {profile.slug!r}",
                )
            if profile.slug in profile_slugs:
                report.add(
                    "error",
                    "profile.duplicate",
                    profile.slug,
                    f"slug {profile.slug!r} appears in multiple files",
                )
            profile_slugs.add(profile.slug)
            profile_pairings[profile.slug] = profile.pairings
            for ref in profile.evidence_refs:
                profile_evidence_refs.add(ref)

    # ----------------------------------------------------- pairings xref
    for slug, pairings in profile_pairings.items():
        for partner in pairings:
            if partner == slug:
                report.add(
                    "error",
                    "profile.pairings-self",
                    slug,
                    f"profile {slug!r} pairs with itself",
                )
                continue
            if partner not in profile_slugs:
                report.add(
                    "error",
                    "profile.pairings-xref",
                    slug,
                    f"pairings references unknown slug {partner!r}",
                )
                continue
            partner_pairings = profile_pairings.get(partner, [])
            if slug not in partner_pairings:
                report.add(
                    "error",
                    "profile.pairings-symmetric",
                    slug,
                    f"pairings with {partner!r} is not reciprocated",
                )

    # ---------------------------------------------------------- evidence
    on_disk_evidence: set[str] = set()
    if cfg.evidence_dir.exists():
        for path in sorted(cfg.evidence_dir.glob("sha256-*.json")):
            report.evidence_checked += 1
            target = str(path)
            data = _load_json(path)
            if data is None:
                report.add("error", "evidence.parse", target, "could not parse JSON")
                continue
            if evidence_validator is not None:
                for err in evidence_validator.iter_errors(data):
                    report.add(
                        "error",
                        "evidence.schema",
                        target,
                        f"{'/'.join(str(p) for p in err.absolute_path)}: {err.message}",
                    )
            try:
                evidence = Evidence.model_validate(data)
            except ValidationError as exc:
                report.add("error", "evidence.pydantic", target, str(exc))
                continue
            expected_filename = f"sha256-{evidence.sha256}.json"
            if path.name != expected_filename:
                report.add(
                    "error",
                    "evidence.filename",
                    target,
                    f"filename should be {expected_filename!r}",
                )
            on_disk_evidence.add(evidence.evidence_ref)

    # ---------------------------------------------------------- verdicts
    verdict_evidence_refs: set[str] = set()
    if cfg.verdicts_dir.exists():
        for path in sorted(cfg.verdicts_dir.glob("*.json")):
            if path.name.endswith(".sig.json"):
                continue  # detached BYOK signature sidecar, not a verdict
            report.verdicts_checked += 1
            target = str(path)
            data = _load_json(path)
            if data is None:
                report.add("error", "verdict.parse", target, "could not parse JSON")
                continue
            if verdict_validator is not None:
                for err in verdict_validator.iter_errors(data):
                    report.add(
                        "error",
                        "verdict.schema",
                        target,
                        f"{'/'.join(str(p) for p in err.absolute_path)}: {err.message}",
                    )
            try:
                verdict = Verdict.model_validate(data)
            except ValidationError as exc:
                report.add("error", "verdict.pydantic", target, str(exc))
                continue
            if verdict.pair is None:
                # N-ary verdicts (3+ participants) skip the pair-order check;
                # that check is intentionally 2-agent only.
                continue
            a, b = verdict.pair
            # Pair must be alphabetized
            if (a, b) != sort_pair(a, b):
                report.add(
                    "error",
                    "verdict.pair-order",
                    target,
                    f"pair {(a, b)!r} is not alphabetized",
                )
            # Filename must match the alphabetized pair OR the autopilot's
            # date-prefixed verdict_id form (multiple verdicts per pair
            # over time keep history without clobbering).
            expected_name = f"{min(a, b)}__{max(a, b)}.json"
            autopilot_name = f"{verdict.verdict_id}.json"
            if path.name not in (expected_name, autopilot_name):
                report.add(
                    "error",
                    "verdict.filename",
                    target,
                    f"filename should be {expected_name!r} or {autopilot_name!r}",
                )
            # Both slugs must resolve to existing profiles
            for slug in (a, b):
                if slug not in profile_slugs:
                    report.add(
                        "error",
                        "verdict.cross-ref",
                        target,
                        f"verdict references unknown profile {slug!r}",
                    )
            # Collect evidence refs from sub-verdicts
            for sv_name in (
                "A_prompt_injection",
                "B_data_leakage",
                "C_capability_conflict",
                "D_cascading_error",
                "E_compliance",
            ):
                sv = getattr(verdict.sub_verdicts, sv_name)
                for citation in sv.citations:
                    if citation.evidence_ref:
                        verdict_evidence_refs.add(citation.evidence_ref)

    # ---------------------------------------------------- evidence cross-refs
    for ref in profile_evidence_refs | verdict_evidence_refs:
        if ref not in on_disk_evidence:
            severity = "error"
            kind = "evidence.missing"
            report.add(severity, kind, ref, f"referenced evidence {ref} is not in _evidence/")

    # ----------------------------------------------------------- chains
    chain_validator = _load_schema(cfg.schema_dir / "chain.schema.json")
    if cfg.chains_dir.exists():
        for path in sorted(cfg.chains_dir.glob("*.json")):
            report.chains_checked += 1
            target = str(path)
            data = _load_json(path)
            if data is None:
                report.add("error", "chain.parse", target, "could not parse JSON")
                continue
            if chain_validator is not None:
                for err in chain_validator.iter_errors(data):
                    report.add(
                        "error",
                        "chain.schema",
                        target,
                        f"{'/'.join(str(p) for p in err.absolute_path)}: {err.message}",
                    )
            try:
                chain = Chain.model_validate(data)
            except ValidationError as exc:
                report.add("error", "chain.pydantic", target, str(exc))
                continue
            if path.stem != chain.chain_id:
                report.add(
                    "error",
                    "chain.filename",
                    target,
                    f"filename {path.stem!r} does not match chain_id {chain.chain_id!r}",
                )
            participant_slugs = {p.slug for p in chain.participants}
            for p in chain.participants:
                if p.slug not in profile_slugs:
                    report.add(
                        "error",
                        "chain.participant-xref",
                        target,
                        f"participant {p.slug!r} has no profile",
                    )
            for e in chain.edges:
                if e.from_ not in participant_slugs or e.to not in participant_slugs:
                    report.add(
                        "error",
                        "chain.edge-endpoint",
                        target,
                        f"edge {e.from_!r}->{e.to!r} not within participants",
                    )

    return report
