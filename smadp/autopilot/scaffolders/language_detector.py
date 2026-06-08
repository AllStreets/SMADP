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

        # First pass: probe at the repo root. Covers the common single-package
        # case (~80% of agents).
        language = self._probe_at(owner, repo, "", branch, headers)
        if language != Language.UNSUPPORTED:
            return language

        # Second pass: probe common monorepo subdirectory patterns. AutoGPT
        # keeps the canonical package at classic/, langchain-ai/langgraph at
        # libs/langgraph/, gpt-engineer/gpt-engineer at the repo-named subdir,
        # JS monorepos at packages/<name>/.
        for subdir in self._monorepo_subdirs(repo):
            language = self._probe_at(owner, repo, subdir, branch, headers)
            if language != Language.UNSUPPORTED:
                log.info(
                    "language_detector.monorepo_match",
                    github_source=github_source,
                    subdir=subdir,
                    language=language.value,
                )
                return language
        return Language.UNSUPPORTED

    @staticmethod
    def _monorepo_subdirs(repo: str) -> list[str]:
        """Common monorepo paths to probe when the root has no manifest.

        Each path is rendered relative to the repo root (no leading slash);
        the manifest filename is appended at probe time.
        """
        # `repo` may be mixed-case (Significant-Gravitas/AutoGPT); GitHub
        # paths are case-sensitive, so probe both the literal and lowercase
        # forms.
        repo_lower = repo.lower()
        bases = ["classic", "libs", "packages", "src", "python"]
        out: list[str] = []
        # libs/<repo> style — langchain pattern.
        for base in bases:
            out.append(f"{base}/{repo}")
            if repo_lower != repo:
                out.append(f"{base}/{repo_lower}")
        # <repo>/ style — gpt-engineer pattern.
        out.append(repo)
        if repo_lower != repo:
            out.append(repo_lower)
        # Bare classic/ — AutoGPT-style legacy moved to a sibling.
        out.append("classic")
        return out

    def _probe_at(
        self,
        owner: str,
        repo: str,
        subdir: str,
        branch: str,
        headers: dict[str, str],
    ) -> Language:
        """Probe each manifest filename inside ``subdir`` of the repo."""
        prefix = f"{subdir.rstrip('/')}/" if subdir else ""
        for manifest, language in _MANIFEST_TO_LANGUAGE:
            path = f"{prefix}{manifest}"
            try:
                resp = httpx.get(
                    f"https://api.github.com/repos/{owner}/{repo}/contents/{path}",
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
