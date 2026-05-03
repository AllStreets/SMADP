"""End-to-end Profiler pipeline: URLs in, validated Profile on disk."""

from __future__ import annotations

import json
from pathlib import Path

import structlog

from smadp.config import Config, load_config
from smadp.llm.client import LLMClient
from smadp.profiler.citations import CitationReport, validate_citations
from smadp.profiler.extractor import (
    chunk_documents,
    extract_profile,
    store_evidence,
)
from smadp.profiler.fetcher import fetch_sources
from smadp.schemas.profile import Profile
from smadp.utils import normalize_slug

logger = structlog.get_logger(__name__)


class ProfilerError(RuntimeError):
    """Raised when the pipeline cannot produce a valid Profile."""


async def build_profile(
    source_url: str | list[str],
    *,
    slug: str | None = None,
    name: str | None = None,
    verified: bool = False,
    config: Config | None = None,
    llm: LLMClient | None = None,
    source_type: str = "open-source",
    category: str = "uncategorized",
    homepage: str | None = None,
    repo_url: str | None = None,
    write_to_disk: bool = True,
    validate_quotes: bool = False,
) -> Profile:
    """Build a :class:`Profile` from one or more source URLs.

    Pipeline:

    1. Fetch all source URLs concurrently.
    2. Chunk the fetched documents.
    3. Persist each chunk as content-addressed evidence under
       ``<catalog>/_evidence/sha256-<hash>.json``.
    4. Call the LLM-judge to extract a structured Profile from the bundle.
    5. Validate citations (existence; verbatim quotes only when
       ``validate_quotes=True`` to keep the default fast/offline-friendly).
    6. Optionally write the Profile JSON to ``<catalog>/profiles/`` (if
       ``verified``) or ``<catalog>/profiles/_unverified/`` (otherwise).

    Args:
        source_url: One URL or a list of URLs (GitHub, HuggingFace, generic HTTP).
        slug: Override / supply the canonical slug. If omitted, derived from
            ``name`` or the first URL.
        name: Display name of the agent. Required if ``slug`` is omitted and
            cannot be derived from the URL.
        verified: True for hand-verified seed entries, False for user
            submissions (changes ``verification.status`` and write target).
        config: Optional pre-built :class:`Config`.
        llm: Optional pre-built :class:`LLMClient` (one is created from
            ``config`` if absent).
        source_type, category, homepage, repo_url: Identity fields fed to the
            extraction prompt.
        write_to_disk: When False, the Profile is returned but not written.
        validate_quotes: When True, citation validation re-fetches each
            source URL and checks the quote still appears verbatim.

    Returns:
        The validated Profile.

    Raises:
        ProfilerError: When fetching fails completely, the LLM cannot extract
            a valid Profile, or citation validation fails.
    """
    cfg = config or load_config()
    cfg.ensure_dirs()
    urls = [source_url] if isinstance(source_url, str) else list(source_url)
    if not urls:
        raise ProfilerError("At least one source URL is required.")

    derived_name = name or _derive_name_from_urls(urls)
    derived_slug = slug or normalize_slug(derived_name)

    logger.info(
        "profiler.pipeline.start",
        slug=derived_slug,
        url_count=len(urls),
        verified=verified,
    )

    docs = await fetch_sources(urls)
    if not docs:
        raise ProfilerError(f"No source URLs could be fetched (tried {len(urls)}).")

    chunks = chunk_documents(docs)
    if not chunks:
        raise ProfilerError("Fetched sources produced no usable text chunks.")

    evidence_records = store_evidence(chunks, cfg.evidence_dir)
    if not evidence_records:
        raise ProfilerError("No evidence records were written.")

    client = llm or LLMClient(config=cfg)
    profile = await extract_profile(
        slug=derived_slug,
        name=derived_name,
        source_type=source_type,
        category=category,
        homepage=homepage or _first_homepage(urls),
        repo_url=repo_url or _first_github_repo(urls),
        docs_urls=urls,
        evidence=evidence_records,
        llm=client,
        config=cfg,
        verified=verified,
    )

    report: CitationReport = validate_citations(
        profile,
        cfg.evidence_dir,
        refetch=validate_quotes,
    )
    if not report.valid:
        raise ProfilerError(
            "Citation validation failed: "
            f"issues={report.issues}; fields_missing_evidence={report.fields_missing_evidence}"
        )

    if write_to_disk:
        target = _profile_path(cfg, profile.slug, verified=verified)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                profile.model_dump(mode="json", exclude_none=True),
                sort_keys=True,
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        logger.info(
            "profiler.pipeline.written",
            slug=profile.slug,
            path=str(target),
            verified=verified,
        )
    return profile


def _profile_path(cfg: Config, slug: str, *, verified: bool) -> Path:
    if verified:
        return cfg.profiles_dir / f"{slug}.json"
    return cfg.unverified_profiles_dir / f"{slug}.json"


def _derive_name_from_urls(urls: list[str]) -> str:
    for url in urls:
        if "github.com/" in url:
            tail = url.rstrip("/").rsplit("/", 1)[-1]
            return tail.removesuffix(".git") or tail
        if "huggingface.co/" in url:
            tail = url.rstrip("/").rsplit("/", 1)[-1]
            return tail
    # Fall back to the host of the first URL.
    first = urls[0]
    host = first.split("//", 1)[-1].split("/", 1)[0]
    return host or first


def _first_github_repo(urls: list[str]) -> str | None:
    for url in urls:
        if url.startswith("https://github.com/") or url.startswith("http://github.com/"):
            return url
    return None


def _first_homepage(urls: list[str]) -> str | None:
    for url in urls:
        if "github.com" in url or "huggingface.co" in url:
            continue
        return url
    return None
