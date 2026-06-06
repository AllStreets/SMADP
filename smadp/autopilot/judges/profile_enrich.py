"""ProfileEnrichmentJudge: upgrade an unverified-profile stub to docs-only.

Fetches the agent's GitHub README, chunks it into evidence items, and asks
``LLMClient.extract_profile`` to emit a fully-cited Safety Profile. The
existing extract_profile prompt enforces verbatim-quote-only outputs, so the
resulting profile is evidence-grounded by construction.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import structlog

from smadp.autopilot.work_queue import WorkItem
from smadp.llm.prompts import profile_extraction

log = structlog.get_logger(__name__)

_CHUNK_CHARS = 8_000
_MAX_CHUNKS = 6


@dataclass(frozen=True)
class JudgeResult:
    verdict: dict[str, Any]
    cost_usd: float


class ProfileEnrichmentJudge:
    name = "profile_enrich"
    version = "v1"
    evidence_level = "docs-only"
    cost_per_call_usd = 0.04

    def __init__(self, *, client, readme_fetcher, model: str) -> None:
        self.client = client
        self.readme_fetcher = readme_fetcher
        self.model = model

    def evaluate(self, work: WorkItem, *, profiles: dict[str, dict]) -> JudgeResult:
        slug = work.pair[0]
        stub = profiles[slug]
        github = (stub.get("onexus") or {}).get("source_github")
        if not github:
            raise ValueError(f"profile {slug!r}: no GitHub source — cannot enrich")

        readme = self.readme_fetcher.fetch(github)
        evidence = self._chunk_readme(readme, source_url=f"https://github.com/{github}/blob/HEAD/README.md")

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        payload = profile_extraction.ProfileExtractionInput(
            slug=slug,
            name=stub.get("name", slug),
            source_type="github",
            category=stub.get("category", "uncategorized"),
            homepage=None,
            repo_url=f"https://github.com/{github}",
            docs_urls=stub.get("docs_urls", []),
            now_iso=now_iso,
            evidence=evidence,
        )
        result = asyncio.run(self.client.extract_profile(payload))
        enriched = dict(result.tool_input)
        enriched["evidence_level"] = "docs-only"
        if "onexus" in stub:
            enriched["onexus"] = stub["onexus"]
        if "composite_score" in stub:
            enriched["composite_score"] = stub["composite_score"]
        return JudgeResult(verdict=enriched, cost_usd=self.cost_per_call_usd)

    @staticmethod
    def _chunk_readme(text: str, *, source_url: str) -> list[dict[str, str]]:
        if not text:
            return []
        chunks: list[dict[str, str]] = []
        for i in range(0, len(text), _CHUNK_CHARS):
            if len(chunks) >= _MAX_CHUNKS:
                break
            quote = text[i : i + _CHUNK_CHARS]
            sha = hashlib.sha256(quote.encode("utf-8")).hexdigest()
            chunks.append(
                {
                    "sha": sha,
                    "source_url": source_url,
                    "media_type": "text/markdown",
                    "quote": quote,
                    "context": f"README chunk {len(chunks) + 1}",
                }
            )
        return chunks
