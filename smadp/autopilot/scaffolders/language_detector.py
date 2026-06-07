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

        owner, _, repo = github_source.partition("/")
        headers = {"Accept": "application/vnd.github+json"}
        if self.token:
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
