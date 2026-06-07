"""GithubMetadataLanguageDetector: classify a repo by which manifest it ships.

Uses the GitHub Contents API to check for pyproject.toml / package.json /
go.mod / Cargo.toml (in that order — Python is the most common ONEXUS-agent
language by a wide margin). Each lookup is a single HEAD-style API call.

Authed limit: 5,000/hr. Anonymous: 60/hr — fine for scaffolder smokes,
not for bulk scaffolding without GITHUB_TOKEN.
"""

from __future__ import annotations

from enum import StrEnum

import httpx
import structlog

log = structlog.get_logger(__name__)


class Language(StrEnum):
    PYTHON = "python"
    NODE = "node"
    GO = "go"
    RUST = "rust"
    UNSUPPORTED = "unsupported"


# Order matters: most-common-language first → fewer API calls on average.
_MANIFEST_TO_LANGUAGE: tuple[tuple[str, Language], ...] = (
    ("pyproject.toml", Language.PYTHON),
    ("requirements.txt", Language.PYTHON),
    ("setup.py", Language.PYTHON),
    ("package.json", Language.NODE),
    ("go.mod", Language.GO),
    ("Cargo.toml", Language.RUST),
)


class GithubMetadataLanguageDetector:
    name = "github_metadata"

    def __init__(self, *, token: str | None) -> None:
        self.token = token

    def detect(self, *, github_source: str) -> Language:
        if not github_source or "/" not in github_source:
            raise ValueError(f"invalid github source: {github_source!r}")

        # Try authed first (if token), fall back to anonymous on rejection.
        # GitHub returns 401 on bad bearer; the api.github.com endpoint surfaces
        # this directly (unlike raw.githubusercontent which lies with 404).
        for use_token in (True, False) if self.token else (False,):
            language = self._probe(github_source, use_token=use_token)
            if language != Language.UNSUPPORTED:
                return language
        return Language.UNSUPPORTED

    def _probe(self, github_source: str, *, use_token: bool) -> Language:
        owner, _, repo = github_source.partition("/")
        headers = {"Accept": "application/vnd.github+json"}
        if use_token and self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        try:
            meta_resp = httpx.get(
                f"https://api.github.com/repos/{owner}/{repo}",
                headers=headers,
                timeout=15.0,
            )
        except httpx.HTTPError as exc:
            log.warning("language_detector.transport_error", error=repr(exc))
            return Language.UNSUPPORTED
        if not (200 <= meta_resp.status_code < 300):
            return Language.UNSUPPORTED
        branch = (meta_resp.json() or {}).get("default_branch") or "main"

        for manifest, language in _MANIFEST_TO_LANGUAGE:
            try:
                resp = httpx.get(
                    f"https://api.github.com/repos/{owner}/{repo}/contents/{manifest}",
                    headers=headers,
                    params={"ref": branch},
                    timeout=15.0,
                )
            except httpx.HTTPError as exc:
                log.warning("language_detector.transport_error", error=repr(exc))
                continue
            if 200 <= resp.status_code < 300:
                return language
        return Language.UNSUPPORTED
