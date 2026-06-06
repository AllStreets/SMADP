"""OnexusProfiler: turn a RawOnexusAgent into an SMADP profile STUB.

The stub is intentionally minimal. Capability inference, concurrency model,
data classes touched — all of that requires real evidence (GitHub README)
that the ProfileEnrichmentJudge later supplies. Until enrichment runs the
profile carries ``evidence_level: "unverified-profile"`` so the pair-judge
gate refuses to act on it.
"""

from __future__ import annotations

import hashlib
from typing import Any

from smadp.autopilot.sources.onexus import RawOnexusAgent


def _sha(s: str) -> str:
    return "sha256:" + hashlib.sha256(s.encode("utf-8")).hexdigest()


class OnexusProfiler:
    name = "onexus"
    accepts_source = "onexus"

    def normalize(self, raw: RawOnexusAgent) -> dict[str, Any]:
        docs_urls: list[str] = []
        if raw.source_homepage:
            docs_urls.append(raw.source_homepage)
        if raw.source_github:
            docs_urls.append(f"https://github.com/{raw.source_github}")
        evidence_refs = [_sha(f"onexus:{raw.slug}:{u}") for u in docs_urls]
        return {
            "slug": raw.slug,
            "name": raw.name,
            "category": raw.category,
            "evidence_level": "unverified-profile",
            "docs_urls": docs_urls,
            "evidence_refs": evidence_refs,
            "capabilities": None,
            "data_classes_touched": [],
            "concurrency_model": None,
            "composite_score": raw.composite_score,
            "license": raw.license,
            "onexus": {
                "source_github": raw.source_github,
                "author_handle": raw.author_handle,
                "tags": raw.tags,
                "runnable": raw.runnable,
            },
        }
