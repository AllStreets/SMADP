"""Chunk fetched docs, persist as content-addressed evidence, and call the LLM.

Call flow:

1. :func:`chunk_documents` splits each :class:`FetchedDoc` into overlapping
   text chunks suitable for the LLM context window.
2. :func:`store_evidence` writes each chunk as
   ``_evidence/sha256-<hash>.json`` (idempotent — pre-existing files are not
   re-written) and returns the canonical :class:`Evidence` record.
3. :func:`extract_profile` builds the prompt payload, calls the LLM, and
   returns a validated :class:`Profile`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import ClassVar

import structlog

from smadp.config import Config
from smadp.llm.client import LLMClient
from smadp.llm.prompts import profile_extraction
from smadp.profiler.fetcher import FetchedDoc
from smadp.schemas.evidence import Evidence
from smadp.schemas.profile import Profile
from smadp.utils import sha256_text, utcnow, utcnow_iso

logger = structlog.get_logger(__name__)

DEFAULT_CHUNK_CHARS = 4000
DEFAULT_CHUNK_OVERLAP = 200
EVIDENCE_FILENAME_TEMPLATE = "sha256-{sha}.json"
DEFAULT_FETCHER_NAME = "smadp-profiler"

_HTMLISH_MEDIA_TYPES = {"text/html", "application/xhtml+xml"}


class _HTMLTextExtractor(HTMLParser):
    """Minimal HTML -> text stripper. Drops <script>/<style>; preserves whitespace."""

    _SKIP_TAGS: ClassVar[set[str]] = {"script", "style", "noscript", "template", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._buf: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in self._SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._buf.append(data)

    def text(self) -> str:
        joined = "".join(self._buf)
        return re.sub(r"\n{3,}", "\n\n", joined).strip()


def _normalize_to_text(doc: FetchedDoc) -> str:
    """Return plain-text content suitable for chunking."""
    if doc.media_type.lower() in _HTMLISH_MEDIA_TYPES:
        parser = _HTMLTextExtractor()
        try:
            parser.feed(doc.content)
        except Exception:
            return doc.content
        return parser.text()
    return doc.content


@dataclass(frozen=True)
class Chunk:
    """A single chunk of source text ready to become Evidence."""

    source_url: str
    media_type: str
    quote: str
    context: str | None
    fingerprint: str | None


def chunk_documents(
    docs: Iterable[FetchedDoc],
    *,
    chunk_chars: int = DEFAULT_CHUNK_CHARS,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[Chunk]:
    """Split each fetched document into overlapping text chunks.

    Tiny documents become a single chunk. We do NOT chunk on token boundaries
    (the model handles raw text fine and our extraction prompt is small).
    """
    if chunk_chars <= 0:
        raise ValueError("chunk_chars must be positive")
    if overlap < 0 or overlap >= chunk_chars:
        raise ValueError("overlap must be in [0, chunk_chars)")
    chunks: list[Chunk] = []
    for doc in docs:
        text = _normalize_to_text(doc)
        if not text:
            continue
        if len(text) <= chunk_chars:
            chunks.append(
                Chunk(
                    source_url=doc.url,
                    media_type=doc.media_type,
                    quote=text,
                    context=None,
                    fingerprint=doc.fingerprint,
                )
            )
            continue
        step = chunk_chars - overlap
        for start in range(0, len(text), step):
            piece = text[start : start + chunk_chars]
            if not piece.strip():
                continue
            chunks.append(
                Chunk(
                    source_url=doc.url,
                    media_type=doc.media_type,
                    quote=piece,
                    context=f"chars {start}..{start + len(piece)}",
                    fingerprint=doc.fingerprint,
                )
            )
            if start + chunk_chars >= len(text):
                break
    return chunks


def store_evidence(
    chunks: Iterable[Chunk],
    evidence_dir: Path,
    *,
    fetcher: str = DEFAULT_FETCHER_NAME,
) -> list[Evidence]:
    """Write each chunk to the evidence directory; return the records.

    Idempotent: if an ``sha256-<hash>.json`` file already exists with a
    matching sha, we re-use it without rewriting.
    """
    evidence_dir.mkdir(parents=True, exist_ok=True)
    records: list[Evidence] = []
    seen: set[str] = set()
    for chunk in chunks:
        sha = sha256_text(chunk.quote)
        if sha in seen:
            continue
        seen.add(sha)
        record = Evidence(
            sha256=sha,
            source_url=chunk.source_url,  # type: ignore[arg-type]
            fetched_at=utcnow(),
            fetcher=fetcher,
            media_type=chunk.media_type,
            quote=chunk.quote,
            context=chunk.context,
            fingerprint=chunk.fingerprint,
        )
        path = evidence_dir / EVIDENCE_FILENAME_TEMPLATE.format(sha=sha)
        if not path.exists():
            payload = record.model_dump(mode="json", exclude_none=True)
            path.write_text(
                json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        records.append(record)
    return records


async def extract_profile(
    *,
    slug: str,
    name: str,
    source_type: str,
    category: str,
    homepage: str | None,
    repo_url: str | None,
    docs_urls: list[str],
    evidence: list[Evidence],
    llm: LLMClient,
    config: Config,
    verified: bool = False,
) -> Profile:
    """Call the LLM with the evidence bundle and return a validated Profile."""
    if not evidence:
        raise ValueError("extract_profile requires at least one evidence record")

    payload_evidence: list[dict[str, str]] = [
        {
            "sha": e.sha256,
            "source_url": str(e.source_url),
            "media_type": e.media_type,
            "quote": e.quote,
            "context": e.context or "",
        }
        for e in evidence
    ]
    payload = profile_extraction.ProfileExtractionInput(
        slug=slug,
        name=name,
        source_type=source_type,
        category=category,
        homepage=homepage,
        repo_url=repo_url,
        docs_urls=list(docs_urls),
        now_iso=utcnow_iso(),
        evidence=payload_evidence,
    )
    result = await llm.extract_profile(payload)
    raw_profile = dict(result.tool_input)

    # Apply trusted overrides: caller-supplied identity and verification status
    # always win over what the model produced. This guards against the model
    # renaming the agent or claiming "verified" status.
    raw_profile["slug"] = slug
    raw_profile["name"] = name
    raw_profile["source_type"] = source_type
    raw_profile["category"] = category
    raw_profile.setdefault("verification", {})
    raw_profile["verification"] = {
        "status": "verified" if verified else "unverified",
        "verified_by": raw_profile.get("verification", {}).get("verified_by"),
        "verified_at": utcnow_iso(),
        "method": "manual-review-of-llm-extraction" if verified else "auto-only",
    }

    # Drop empty-string optional URL fields the model sometimes emits to keep
    # Pydantic's HttpUrl validator from rejecting them.
    for key in ("homepage", "repo_url"):
        value = raw_profile.get(key)
        if isinstance(value, str) and not value.strip():
            raw_profile.pop(key)

    raw_profile.setdefault("first_seen_at", utcnow_iso())
    raw_profile["last_refreshed_at"] = utcnow_iso()

    profile = Profile.model_validate(raw_profile)
    logger.info(
        "profiler.extracted",
        slug=profile.slug,
        evidence_refs=len(profile.evidence_refs),
        usage=result.usage,
    )
    return profile
