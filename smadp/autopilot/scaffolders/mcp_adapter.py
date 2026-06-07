"""MCPAdapterScaffolder: enriched profile + GitHub source → runnable adapter."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jinja2
import structlog

from smadp.autopilot.scaffolders.capability_policy import CapabilityPolicy
from smadp.autopilot.scaffolders.language_detector import Language

log = structlog.get_logger(__name__)

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

_ENRICHED_TIERS = {"docs-only", "profile-verified", "sandbox-validated"}

_LANGUAGE_TO_DOCKERFILE: dict[Language, str] = {
    Language.PYTHON: "python.Dockerfile",
    Language.NODE: "node.Dockerfile",
    Language.GO: "go.Dockerfile",
    Language.RUST: "rust.Dockerfile",
}

_LANGUAGE_TO_INVOCATION: dict[Language, str] = {
    Language.PYTHON: "python -m {slug}",
    Language.NODE: "npm start",
    Language.GO: "/usr/local/bin/agent",
    Language.RUST: "/usr/local/bin/agent",
}

_TRUST_FLOOR_BY_EVIDENCE: dict[str, float] = {
    "docs-only": 0.3,
    "profile-verified": 0.5,
    "sandbox-validated": 0.7,
}


@dataclass(frozen=True)
class ScaffoldResult:
    target_dir: Path
    files_written: list[Path] = field(default_factory=list)
    language: Language = Language.UNSUPPORTED
    success: bool = False
    reason: str = ""


class MCPAdapterScaffolder:
    name = "mcp_adapter"

    def __init__(
        self,
        *,
        detector: Any,
        commit_pin_resolver: Callable[[str], str],
    ) -> None:
        self.detector = detector
        self.commit_pin_resolver = commit_pin_resolver
        # autoescape=False is intentional: we render Dockerfiles, shell scripts,
        # and JSON — not HTML. HTML-escape would corrupt those formats. Templates
        # only consume trusted slugs/repo_urls from the catalog.
        self._env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(_TEMPLATES_DIR)),
            autoescape=False,  # noqa: S701
            keep_trailing_newline=True,
        )

    def scaffold(self, profile: dict[str, Any], *, target_dir: Path) -> ScaffoldResult:
        if profile.get("evidence_level") not in _ENRICHED_TIERS:
            return ScaffoldResult(target_dir=target_dir, reason="profile_not_enriched")

        github = self._extract_github_source(profile)
        if not github:
            return ScaffoldResult(target_dir=target_dir, reason="no_github_source")

        language = self.detector.detect(github_source=github)
        if language not in _LANGUAGE_TO_DOCKERFILE:
            return ScaffoldResult(
                target_dir=target_dir,
                language=language,
                reason="unsupported_language",
            )

        commit_pin = self.commit_pin_resolver(github)
        repo_url = f"https://github.com/{github}"
        slug = profile["slug"]
        now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        docker_args = CapabilityPolicy.to_docker_args(profile)
        env_required = (profile.get("permissions_requested") or {}).get("secrets_handled") or []

        template_vars: dict[str, Any] = {
            "slug": slug,
            "name": profile.get("name", slug),
            "description": profile.get("tagline") or "",
            "homepage": profile.get("homepage") or "",
            "repo_url": repo_url,
            "commit_pin": commit_pin,
            "commit_pin_short": commit_pin[:12],
            "now_iso": now_iso,
            "capabilities_json": json.dumps(profile.get("capabilities") or {}, indent=2),
            "io_surfaces_json": json.dumps(profile.get("io_surfaces") or {}, indent=2),
            "docker_args_json": json.dumps(docker_args, indent=2),
            "env_required_json": json.dumps(env_required),
            "trust_floor": _TRUST_FLOOR_BY_EVIDENCE.get(
                profile.get("evidence_level", "docs-only"), 0.3
            ),
            "agent_invocation": _LANGUAGE_TO_INVOCATION[language].format(slug=slug),
        }

        target_dir.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []

        dockerfile_template = self._env.get_template(_LANGUAGE_TO_DOCKERFILE[language])
        written.append(
            self._atomic_write(
                target_dir / "Dockerfile", dockerfile_template.render(**template_vars)
            )
        )

        entrypoint_template = self._env.get_template("entrypoint.sh")
        written.append(
            self._atomic_write(
                target_dir / "entrypoint.sh", entrypoint_template.render(**template_vars)
            )
        )

        mcp_template = self._env.get_template("mcp.json.tmpl")
        written.append(
            self._atomic_write(target_dir / "mcp.json", mcp_template.render(**template_vars))
        )

        provenance = {
            "slug": slug,
            "language": language.value,
            "commit_pin": commit_pin,
            "scaffolded_at": now_iso,
            "scaffolder_version": "v1",
            "template_versions": {
                "dockerfile": "v1",
                "entrypoint": "v1",
                "mcp_json": "v1",
            },
        }
        written.append(
            self._atomic_write(
                target_dir / ".scaffolded.json",
                json.dumps(provenance, indent=2) + "\n",
            )
        )

        return ScaffoldResult(
            target_dir=target_dir,
            files_written=written,
            language=language,
            success=True,
            reason="ok",
        )

    @staticmethod
    def _extract_github_source(profile: dict[str, Any]) -> str | None:
        onexus = profile.get("onexus") or {}
        gh = onexus.get("source_github")
        if gh:
            return str(gh)
        repo_url = profile.get("repo_url") or ""
        if "github.com/" in repo_url:
            return repo_url.split("github.com/", 1)[1].rstrip("/")
        return None

    @staticmethod
    def _atomic_write(path: Path, content: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp, path)
        except Exception:
            if tmp.exists():
                tmp.unlink()
            raise
        return path
