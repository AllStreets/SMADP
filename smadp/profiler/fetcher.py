"""Async source fetchers for the Profiler.

Three source families are recognized:

- **GitHub repository** (``https://github.com/<owner>/<repo>[/...]``) — fetch
  the README via ``api.github.com/repos/{owner}/{repo}/readme``.
- **HuggingFace model** (``https://huggingface.co/<owner>/<model>``) — fetch
  the model card via ``huggingface.co/api/models/<owner>/<model>``.
- **Generic HTTP(S) page** — fetch the body with ``httpx``; HTML pages are
  returned as-is (the extractor strips tags).

Each fetcher returns one or more :class:`FetchedDoc` objects. The fetcher
never raises on a single source failure; it logs and skips, returning only
the docs that succeeded.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

import httpx
import structlog

from smadp.utils import utcnow

logger = structlog.get_logger(__name__)

DEFAULT_USER_AGENT = "smadp-profiler/0.1 (+https://github.com/AllStreets/SMADP)"
DEFAULT_TIMEOUT_SECONDS = 30.0

_GITHUB_REPO_RE = re.compile(
    r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/#?]+)(?:/.*)?$"
)
_HF_MODEL_RE = re.compile(
    r"^https?://huggingface\.co/(?P<owner>[^/]+)/(?P<model>[^/#?]+)(?:/.*)?$"
)


@dataclass(frozen=True)
class FetchedDoc:
    """One fetched source document."""

    url: str
    content: str
    media_type: str
    fetched_at: datetime
    fingerprint: str | None = None
    """Server-supplied identity (ETag, content-hash) when available."""


def _strip_repo_suffix(repo: str) -> str:
    """``smadp.git`` -> ``smadp``."""
    return repo.removesuffix(".git")


async def fetch_sources(
    urls: Iterable[str],
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[FetchedDoc]:
    """Fetch all supplied URLs concurrently. Failures are logged and dropped."""
    url_list = list(urls)
    if not url_list:
        return []

    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(
            headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": "*/*"},
            timeout=timeout,
            follow_redirects=True,
        )
    try:
        tasks = [_fetch_one(url, client) for url in url_list]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        if owns_client:
            await client.aclose()

    docs: list[FetchedDoc] = []
    for url, result in zip(url_list, results, strict=True):
        if isinstance(result, BaseException):
            logger.warning("profiler.fetch.failed", url=url, error=str(result))
            continue
        docs.extend(result)
    return docs


async def _fetch_one(url: str, client: httpx.AsyncClient) -> list[FetchedDoc]:
    """Dispatch ``url`` to the best-matching specialized fetcher."""
    if (m := _GITHUB_REPO_RE.match(url)) is not None:
        return await _fetch_github_readme(
            owner=m.group("owner"),
            repo=_strip_repo_suffix(m.group("repo")),
            client=client,
            origin_url=url,
        )
    if (m := _HF_MODEL_RE.match(url)) is not None:
        return await _fetch_huggingface_card(
            owner=m.group("owner"),
            model=m.group("model"),
            client=client,
            origin_url=url,
        )
    return [await _fetch_generic_http(url, client)]


async def _fetch_github_readme(
    *, owner: str, repo: str, client: httpx.AsyncClient, origin_url: str
) -> list[FetchedDoc]:
    api = f"https://api.github.com/repos/{owner}/{repo}/readme"
    headers = {"Accept": "application/vnd.github.raw+json"}
    resp = await client.get(api, headers=headers)
    resp.raise_for_status()
    body = resp.text
    fingerprint = resp.headers.get("etag")
    return [
        FetchedDoc(
            url=origin_url,
            content=body,
            media_type="text/markdown",
            fetched_at=utcnow(),
            fingerprint=fingerprint,
        )
    ]


async def _fetch_huggingface_card(
    *, owner: str, model: str, client: httpx.AsyncClient, origin_url: str
) -> list[FetchedDoc]:
    api = f"https://huggingface.co/api/models/{owner}/{model}"
    resp = await client.get(api, params={"full": "true"})
    resp.raise_for_status()
    payload = resp.json()
    card = payload.get("cardData") or {}
    readme = payload.get("modelCard") or payload.get("readme") or ""
    body_parts: list[str] = []
    if card:
        body_parts.append("# Model Card\n\n")
        for key in sorted(card):
            body_parts.append(f"- **{key}**: {card[key]}\n")
        body_parts.append("\n")
    if readme:
        body_parts.append(str(readme))
    body = "".join(body_parts).strip() or str(payload)
    fingerprint = resp.headers.get("etag")
    return [
        FetchedDoc(
            url=origin_url,
            content=body,
            media_type="text/markdown",
            fetched_at=utcnow(),
            fingerprint=fingerprint,
        )
    ]


async def _fetch_generic_http(url: str, client: httpx.AsyncClient) -> FetchedDoc:
    resp = await client.get(url)
    resp.raise_for_status()
    media_type = (resp.headers.get("content-type", "text/html").split(";", 1)[0]).strip()
    fingerprint = resp.headers.get("etag")
    return FetchedDoc(
        url=url,
        content=resp.text,
        media_type=media_type or "text/html",
        fetched_at=utcnow(),
        fingerprint=fingerprint,
    )
