"""GithubReadmeFetcher: fetch raw README.md from a GitHub repo and cache locally.

Tries ``HEAD`` first (covers most modern repos), falls back to ``master``.
Caches the raw text under ``<cache_dir>/<owner>__<repo>.txt`` keyed by
``owner/repo``. Cache hit short-circuits the HTTP call.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import structlog

log = structlog.get_logger(__name__)


class ReadmeFetchError(RuntimeError):
    """Raised when no README can be fetched."""


class GithubReadmeFetcher:
    name = "github_readme"

    def __init__(self, *, cache_dir: Path, token: str | None) -> None:
        self.cache_dir = cache_dir
        self.token = token

    def fetch(self, github_source: str) -> str:
        """Fetch and cache README text for ``owner/repo``.

        Raises ReadmeFetchError on empty input or HTTP failure.
        """
        if not github_source or "/" not in github_source:
            raise ReadmeFetchError(f"invalid github source: {github_source!r}")

        cache_key = github_source.replace("/", "__") + ".txt"
        cache_path = self.cache_dir / cache_key
        if cache_path.exists():
            return cache_path.read_text("utf-8")

        text = self._http_fetch(github_source)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(text, encoding="utf-8")
        return text

    def _http_fetch(self, github_source: str) -> str:
        # First pass: authed (if token present), then anonymous on auth rejection.
        # GitHub's raw endpoint returns 404 (not 401) when sent an invalid bearer
        # token, so the fallback triggers whenever ANY authed attempt failed.
        header_sets: list[dict[str, str]] = []
        base_headers = {"Accept": "text/plain"}
        if self.token:
            header_sets.append({**base_headers, "Authorization": f"Bearer {self.token}"})
        header_sets.append(dict(base_headers))

        for headers in header_sets:
            authed = "Authorization" in headers
            for branch in ("HEAD", "master", "main"):
                url = f"https://raw.githubusercontent.com/{github_source}/{branch}/README.md"
                try:
                    resp = httpx.get(url, headers=headers, timeout=15.0, follow_redirects=True)
                except httpx.HTTPError as exc:
                    log.warning("github_readme.transport_error", url=url, error=repr(exc))
                    continue
                if 200 <= resp.status_code < 300:
                    return resp.text
                log.info("github_readme.miss", url=url, status=resp.status_code, authed=authed)
            if authed:
                log.warning("github_readme.authed_attempts_failed_falling_back_anonymous",
                            github_source=github_source)
        raise ReadmeFetchError(f"could not fetch README for {github_source}")
