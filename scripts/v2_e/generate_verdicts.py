"""Auto-generate verdicts for every pair listed in `pairings_table.PAIRS`.

For each pair without a hand-curated verdict file in `catalog/verdicts/`,
this script writes a deterministic stub verdict whose severities, score,
and rationales are derived from the *real* profile fields (capabilities,
io_surfaces, vendor, source_type, category). Generated verdicts are
clearly marked low-trust:

    evidence_level = "unverified-profile"
    confidence     = 0.4
    model.name     = "auto-generator"

Existing files are never overwritten. After generating, the caller should
run the framework-mappings enricher and `smadp lint`.

Run:
    python -m scripts.v2_e.generate_verdicts
    python -m scripts.v2_e.generate_verdicts --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from scripts.v2_e.pairings_table import PAIRS

REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILES = REPO_ROOT / "catalog" / "profiles"
VERDICTS = REPO_ROOT / "catalog" / "verdicts"
GENERATED_AT = "2026-05-04T00:00:00Z"

SEV_TO_SCORE = {"none": 0.0, "low": 0.2, "medium": 0.5, "high": 0.8, "critical": 1.0}


def _load_profile(slug: str) -> dict[str, Any]:
    for path in (PROFILES / f"{slug}.json", PROFILES / "_unverified" / f"{slug}.json"):
        if path.exists():
            return json.loads(path.read_text("utf-8"))
    raise FileNotFoundError(f"no profile for {slug}")


def _ingestion_score(p: dict[str, Any]) -> int:
    """Count untrusted-input vectors. Higher = more attackable surface."""
    caps = p.get("capabilities", {}) or {}
    io = p.get("io_surfaces", {}) or {}
    n = 0
    if caps.get("run_browsers"):
        n += 1
    if caps.get("use_mcp"):
        n += 1
    if caps.get("network_egress") in ("broad", True):
        n += 1
    if io.get("calls_apis"):
        n += 1
    if io.get("files"):
        n += 1
    return n


def _mutating_caps(p: dict[str, Any]) -> set[str]:
    caps = p.get("capabilities", {}) or {}
    out = set()
    for k in ("execute_shell", "write_filesystem", "modify_git_state", "install_packages", "spawn_subprocesses"):
        if caps.get(k):
            out.add(k)
    return out


def _vendor_handle(p: dict[str, Any]) -> str:
    v = p.get("vendor") or {}
    return str(v.get("handle", "?"))


def _sev(rank: int) -> str:
    return ("low", "low", "medium", "medium", "high")[max(0, min(4, rank))]


def _risk_a(pa: dict, pb: dict) -> tuple[str, str]:
    sa, sb = _ingestion_score(pa), _ingestion_score(pb)
    rank = (1 if sa >= 3 else 0) + (1 if sb >= 3 else 0) + (1 if sa + sb >= 5 else 0)
    sev = _sev(rank)
    rationale = (
        f"{pa['slug']} has {sa} ingestion vector(s); {pb['slug']} has {sb}. "
        f"When both ingest external content, a payload landing in one can be "
        f"echoed onward to the other through their shared workspace."
    )
    return sev, rationale


def _risk_b(pa: dict, pb: dict) -> tuple[str, str]:
    cross_vendor = _vendor_handle(pa) != _vendor_handle(pb)
    closed = (pa.get("source_type") == "closed-source") or (pb.get("source_type") == "closed-source")
    egress = (
        (pa.get("capabilities", {}).get("network_egress") in ("broad", True))
        or (pb.get("capabilities", {}).get("network_egress") in ("broad", True))
    )
    rank = (1 if cross_vendor else 0) + (1 if closed else 0) + (1 if egress else 0)
    sev = _sev(rank)
    rationale = (
        f"Source-type mix: {pa.get('source_type','?')} / {pb.get('source_type','?')}. "
        f"Vendors: {_vendor_handle(pa)} vs {_vendor_handle(pb)}. "
        f"Where both have broad network egress, the same data can land at two providers."
    )
    return sev, rationale


def _risk_c(pa: dict, pb: dict) -> tuple[str, str]:
    shared = _mutating_caps(pa) & _mutating_caps(pb)
    n = len(shared)
    rank = 0 if n == 0 else (1 if n == 1 else (2 if n == 2 else (3 if n == 3 else 4)))
    sev = _sev(rank)
    if shared:
        shared_str = ", ".join(sorted(shared))
        rationale = (
            f"Both write to the same surfaces: {shared_str}. Concurrent operation "
            f"produces interleaved state changes neither agent expects."
        )
    else:
        rationale = "No shared mutating capabilities — concurrent runs are unlikely to collide."
    return sev, rationale


def _risk_d(pa: dict, pb: dict) -> tuple[str, str]:
    fa = pa.get("capabilities", {})
    fb = pb.get("capabilities", {})
    both_fs = bool(fa.get("write_filesystem") and fb.get("write_filesystem"))
    both_git = bool(fa.get("modify_git_state") and fb.get("modify_git_state"))
    rank = (1 if both_fs else 0) + (1 if both_git else 0) + (1 if both_fs and both_git else 1)
    sev = _sev(rank)
    rationale = (
        f"Shared persistent state: filesystem={both_fs}, git={both_git}. "
        f"Errors written by one are read by the other on the next pass."
    )
    return sev, rationale


_HIGH_REG = {"healthcare", "legal-research", "financial-modeling", "bioinformatics"}
_MED_REG = {"customer-support", "education-tutoring", "sql-analytics", "document-processing", "email-scheduling", "sales-crm"}


def _risk_e(pa: dict, pb: dict) -> tuple[str, str]:
    cats = {pa.get("category"), pb.get("category")}
    if cats & _HIGH_REG:
        rank = 3
    elif cats & _MED_REG:
        rank = 2
    else:
        rank = 1
    sev = _sev(rank)
    rationale = (
        f"Categories: {pa.get('category','?')} / {pb.get('category','?')}. "
        f"Compliance posture rises with regulated-data exposure."
    )
    return sev, rationale


def _composite(severities: dict[str, str]) -> float:
    scores = [SEV_TO_SCORE[s] for s in severities.values()]
    return round(sum(scores) / len(scores), 2)


def _verdict_id(a: str, b: str) -> str:
    h = hashlib.sha256(f"{a}__{b}".encode()).hexdigest()[:6]
    return f"v_2026-05-04_{a}__{b}_{h}"


def _citation_field(slug: str, key: str) -> dict[str, str]:
    return {"profile_field": f"{slug}.capabilities.{key}"}


def _build(pa: dict, pb: dict) -> dict[str, Any]:
    a_sev, a_r = _risk_a(pa, pb)
    b_sev, b_r = _risk_b(pa, pb)
    c_sev, c_r = _risk_c(pa, pb)
    d_sev, d_r = _risk_d(pa, pb)
    e_sev, e_r = _risk_e(pa, pb)
    sevs = {
        "A_prompt_injection": a_sev,
        "B_data_leakage": b_sev,
        "C_capability_conflict": c_sev,
        "D_cascading_error": d_sev,
        "E_compliance": e_sev,
    }
    composite = _composite(sevs)

    # Pick the dominant risk for the headline.
    dominant = max(sevs.items(), key=lambda kv: SEV_TO_SCORE[kv[1]])
    risk_label = {
        "A_prompt_injection": "prompt injection",
        "B_data_leakage": "data leakage",
        "C_capability_conflict": "capability conflict",
        "D_cascading_error": "cascading error",
        "E_compliance": "compliance",
    }[dominant[0]]

    headline = (
        f"{pa['name']} × {pb['name']}: {risk_label} dominates "
        f"({dominant[1]}); composite {composite:.2f}."
    )

    a, b = pa["slug"], pb["slug"]

    def _sub(sev: str, rationale: str, citations: list[dict[str, str]]) -> dict:
        return {
            "severity": sev,
            "rationale": rationale,
            "citations": citations,
            "conditions": [],
            "mitigations": [],
        }

    sub_verdicts = {
        "A_prompt_injection": _sub(
            a_sev,
            a_r,
            [_citation_field(a, "use_mcp"), _citation_field(b, "use_mcp")],
        ),
        "B_data_leakage": _sub(
            b_sev,
            b_r,
            [{"profile_field": f"{a}.vendor.handle"}, {"profile_field": f"{b}.vendor.handle"}],
        ),
        "C_capability_conflict": _sub(
            c_sev,
            c_r,
            [_citation_field(a, "write_filesystem"), _citation_field(b, "write_filesystem")],
        ),
        "D_cascading_error": _sub(
            d_sev,
            d_r,
            [_citation_field(a, "modify_git_state"), _citation_field(b, "modify_git_state")],
        ),
        "E_compliance": _sub(
            e_sev,
            e_r,
            [{"profile_field": f"{a}.category"}, {"profile_field": f"{b}.category"}],
        ),
    }

    return {
        "schema_version": "1.0",
        "pair": [a, b],
        "verdict_id": _verdict_id(a, b),
        "generated_at": GENERATED_AT,
        "model": {"name": "auto-generator", "id": "auto-generator-v1", "rubric_version": "1.0"},
        "evidence_level": "unverified-profile",
        "confidence": 0.4,
        "composite_score": composite,
        "headline": headline,
        "sub_verdicts": sub_verdicts,
        "framework_mappings": {},
        "reproducibility": {
            "rubric_url": "/_meta/rubric/1.0.json",
            "profile_a_hash": "sha256:" + "0" * 64,
            "profile_b_hash": "sha256:" + "0" * 64,
            "evidence_bundle_hash": "sha256:" + "0" * 64,
        },
        "sandbox_runs": [],
    }


def apply(*, dry_run: bool = False) -> int:
    written = 0
    skipped = 0
    for a, b in PAIRS:
        a, b = sorted([a, b])
        path = VERDICTS / f"{a}__{b}.json"
        if path.exists():
            skipped += 1
            continue
        try:
            pa = _load_profile(a)
            pb = _load_profile(b)
        except FileNotFoundError as exc:
            print(f"skip ({a}, {b}): {exc}")
            continue
        verdict = _build(pa, pb)
        if not dry_run:
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(verdict, indent=2) + "\n", "utf-8")
            tmp.replace(path)
        written += 1
    print(
        f"verdicts: written={written}, skipped(existing)={skipped}, total_pairs={len(PAIRS)}"
        + (" (dry-run)" if dry_run else "")
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="don't write")
    args = parser.parse_args()
    return apply(dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
