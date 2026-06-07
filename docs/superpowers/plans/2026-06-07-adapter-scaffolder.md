# MCP Adapter Scaffolder — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a code generator that turns an enriched SMADP profile + its GitHub source into a runnable MCP adapter at `adapters/<slug>/{Dockerfile, entrypoint.sh, mcp.json, .scaffolded.json}`, verified end-to-end by a 5-agent smoke (gpt-researcher / autogpt / crewai / langgraph / continue-dev) that produces a buildable Docker image + valid mcp.json for each.

**Architecture:** Four-stage pipeline — LanguageDetector → CapabilityPolicy → TemplateRenderer → Verifier. Templates are Jinja2 files under `smadp/autopilot/scaffolders/templates/`. Output dir is `adapters/<slug>/` (matches existing hand-curated adapters like `adapters/aider/`).

**Tech Stack:** Python 3.11+ via project venv, `jinja2>=3.1` (already a dep), `httpx>=0.27` (already a dep) for GitHub Contents API, `docker` CLI (system requirement, NOT a Python dep). Click for the new `smadp adapters scaffold` subcommand. pytest for unit + integration coverage.

---

## File structure

### New files

| Path | Responsibility |
| --- | --- |
| `smadp/autopilot/scaffolders/__init__.py` | Package init + `Scaffolder` Protocol |
| `smadp/autopilot/scaffolders/language_detector.py` | `Language` enum + `GithubMetadataLanguageDetector.detect()` |
| `smadp/autopilot/scaffolders/capability_policy.py` | `CapabilityPolicy.to_docker_args()` mapping profile caps → docker run flags |
| `smadp/autopilot/scaffolders/mcp_adapter.py` | `MCPAdapterScaffolder.scaffold()` orchestrating the four stages |
| `smadp/autopilot/scaffolders/docker_verify.py` | `verify_adapter_build(adapter_dir)` runs `docker build` + parses result |
| `smadp/autopilot/scaffolders/templates/python.Dockerfile` | Python agent Dockerfile (Jinja2 template) |
| `smadp/autopilot/scaffolders/templates/node.Dockerfile` | Node agent Dockerfile (Jinja2 template) |
| `smadp/autopilot/scaffolders/templates/go.Dockerfile` | Go agent Dockerfile (Jinja2 template) |
| `smadp/autopilot/scaffolders/templates/rust.Dockerfile` | Rust agent Dockerfile (Jinja2 template) |
| `smadp/autopilot/scaffolders/templates/entrypoint.sh` | Shared entrypoint shim (writes $SMADP_AGENT_TASK + invokes agent) |
| `smadp/autopilot/scaffolders/templates/mcp.json.tmpl` | mcp.json Jinja2 template matching existing adapter schema |
| `tests/autopilot/scaffolders/__init__.py` | |
| `tests/autopilot/scaffolders/test_language_detector.py` | |
| `tests/autopilot/scaffolders/test_capability_policy.py` | |
| `tests/autopilot/scaffolders/test_mcp_adapter.py` | |
| `tests/autopilot/scaffolders/test_docker_verify.py` | |
| `tests/autopilot/scaffolders/fixtures/python_profile.json` | Enriched profile fixture (Python agent) |
| `tests/autopilot/scaffolders/fixtures/node_profile.json` | Enriched profile fixture (Node agent) |

### Modified files

| Path | Change |
| --- | --- |
| `smadp/cli.py` | Add `adapters` click group + `adapters scaffold --from-profile <slug>` subcommand |

### Self-contained constants (referenced across tasks)

- Image namespace: `smadp/agent`
- Output dir: `adapters/`
- Templates dir: `smadp/autopilot/scaffolders/templates/`
- `Language` values: `PYTHON`, `NODE`, `GO`, `RUST`, `UNSUPPORTED`
- `_ENRICHED_TIERS = {"docs-only", "profile-verified", "sandbox-validated"}` — gate for scaffold input
- GitHub Contents API URL: `https://api.github.com/repos/{owner}/{repo}/contents/{path}`
- GitHub default-branch API URL: `https://api.github.com/repos/{owner}/{repo}`
- Default `trust_floor_by_evidence`: `{"docs-only": 0.3, "profile-verified": 0.5, "sandbox-validated": 0.7}`

---

## Task 1: LanguageDetector

**Files:**
- Create: `smadp/autopilot/scaffolders/__init__.py`
- Create: `smadp/autopilot/scaffolders/language_detector.py`
- Create: `tests/autopilot/scaffolders/__init__.py`
- Create: `tests/autopilot/scaffolders/test_language_detector.py`

- [ ] **Step 1: Write the failing test**

`tests/autopilot/scaffolders/test_language_detector.py`:
```python
"""Tests for GithubMetadataLanguageDetector."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from smadp.autopilot.scaffolders.language_detector import (
    GithubMetadataLanguageDetector,
    Language,
)


def _fake_response(status: int, json_payload):
    resp = MagicMock()
    resp.status_code = status
    resp.json = MagicMock(return_value=json_payload)
    return resp


def test_detects_python_from_pyproject_toml() -> None:
    det = GithubMetadataLanguageDetector(token=None)
    responses = [
        _fake_response(200, {"default_branch": "main"}),
        _fake_response(200, {"name": "pyproject.toml"}),  # found
    ]
    with patch(
        "smadp.autopilot.scaffolders.language_detector.httpx.get", side_effect=responses
    ):
        assert det.detect(github_source="x/y") == Language.PYTHON


def test_detects_node_from_package_json() -> None:
    det = GithubMetadataLanguageDetector(token=None)
    responses = [
        _fake_response(200, {"default_branch": "main"}),
        _fake_response(404, None),  # no pyproject.toml
        _fake_response(404, None),  # no requirements.txt
        _fake_response(404, None),  # no setup.py
        _fake_response(200, {"name": "package.json"}),  # found
    ]
    with patch(
        "smadp.autopilot.scaffolders.language_detector.httpx.get", side_effect=responses
    ):
        assert det.detect(github_source="x/y") == Language.NODE


def test_detects_go_from_go_mod() -> None:
    det = GithubMetadataLanguageDetector(token=None)
    responses = [
        _fake_response(200, {"default_branch": "main"}),
        _fake_response(404, None),
        _fake_response(404, None),
        _fake_response(404, None),
        _fake_response(404, None),  # no package.json
        _fake_response(200, {"name": "go.mod"}),  # found
    ]
    with patch(
        "smadp.autopilot.scaffolders.language_detector.httpx.get", side_effect=responses
    ):
        assert det.detect(github_source="x/y") == Language.GO


def test_detects_rust_from_cargo_toml() -> None:
    det = GithubMetadataLanguageDetector(token=None)
    responses = [
        _fake_response(200, {"default_branch": "main"}),
        _fake_response(404, None),
        _fake_response(404, None),
        _fake_response(404, None),
        _fake_response(404, None),
        _fake_response(404, None),
        _fake_response(200, {"name": "Cargo.toml"}),  # found
    ]
    with patch(
        "smadp.autopilot.scaffolders.language_detector.httpx.get", side_effect=responses
    ):
        assert det.detect(github_source="x/y") == Language.RUST


def test_returns_unsupported_when_no_manifest_matches() -> None:
    det = GithubMetadataLanguageDetector(token=None)
    responses = [_fake_response(200, {"default_branch": "main"})] + [
        _fake_response(404, None)
    ] * 6
    with patch(
        "smadp.autopilot.scaffolders.language_detector.httpx.get", side_effect=responses
    ):
        assert det.detect(github_source="x/y") == Language.UNSUPPORTED


def test_invalid_github_source_raises() -> None:
    det = GithubMetadataLanguageDetector(token=None)
    with pytest.raises(ValueError):
        det.detect(github_source="")


def test_token_sent_in_authorization_header() -> None:
    det = GithubMetadataLanguageDetector(token="ghp_T")
    responses = [
        _fake_response(200, {"default_branch": "main"}),
        _fake_response(200, {"name": "pyproject.toml"}),
    ]
    with patch(
        "smadp.autopilot.scaffolders.language_detector.httpx.get", side_effect=responses
    ) as get:
        det.detect(github_source="x/y")
        for call in get.call_args_list:
            assert call.kwargs["headers"].get("Authorization") == "Bearer ghp_T"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd "/Users/connorevans/Desktop/Frontier_AI/Safe Multi-Agent Deployment Platform (SMADP)/SMADP"
.venv/bin/python -m pytest tests/autopilot/scaffolders/test_language_detector.py -v
```
Expected: ImportError on `smadp.autopilot.scaffolders.language_detector`.

- [ ] **Step 3: Implement**

`smadp/autopilot/scaffolders/__init__.py`:
```python
"""Adapter scaffolders — turn enriched profiles into runnable MCP adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class ScaffolderResultLike(Protocol):
    target_dir: Path
    files_written: list[Path]
    success: bool
    reason: str


class Scaffolder(Protocol):
    name: str

    def scaffold(
        self, profile: dict[str, Any], *, target_dir: Path
    ) -> ScaffolderResultLike: ...
```

`smadp/autopilot/scaffolders/language_detector.py`:
```python
"""GithubMetadataLanguageDetector: classify a repo by which manifest it ships.

Uses the GitHub Contents API to check for pyproject.toml / package.json /
go.mod / Cargo.toml (in that order — Python is the most common ONEXUS-agent
language by a wide margin). Each lookup is a single HEAD-style API call.

Authed limit: 5,000/hr. Anonymous: 60/hr — fine for scaffolder smokes,
not for bulk scaffolding without GITHUB_TOKEN.
"""

from __future__ import annotations

from enum import Enum

import httpx
import structlog

log = structlog.get_logger(__name__)


class Language(str, Enum):
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

        # 1. Resolve default branch (saves us from blind HEAD/master/main probes).
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

        # 2. Probe for each manifest in order; first hit wins.
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
```

- [ ] **Step 4: Run tests — should pass**

```bash
.venv/bin/python -m pytest tests/autopilot/scaffolders/test_language_detector.py -v
```
Expected: 7/7 PASS.

- [ ] **Step 5: Commit**

```bash
git add smadp/autopilot/scaffolders tests/autopilot/scaffolders
git commit -m "feat(scaffolders): LanguageDetector classifies repo by manifest file"
```

---

## Task 2: CapabilityPolicy

**Files:**
- Create: `smadp/autopilot/scaffolders/capability_policy.py`
- Create: `tests/autopilot/scaffolders/test_capability_policy.py`

- [ ] **Step 1: Write the failing test**

`tests/autopilot/scaffolders/test_capability_policy.py`:
```python
"""Tests for CapabilityPolicy.to_docker_args."""

from __future__ import annotations

from smadp.autopilot.scaffolders.capability_policy import CapabilityPolicy


def _profile(**caps) -> dict:
    return {"capabilities": caps}


def test_broad_network_means_host_network() -> None:
    args = CapabilityPolicy.to_docker_args(_profile(network_egress="broad"))
    assert args["network"] == "host"


def test_allowlisted_network_means_bridge() -> None:
    args = CapabilityPolicy.to_docker_args(_profile(network_egress="allowlisted"))
    assert args["network"] == "bridge"


def test_no_network_means_none() -> None:
    args = CapabilityPolicy.to_docker_args(_profile(network_egress="none"))
    assert args["network"] == "none"


def test_unset_network_defaults_to_none() -> None:
    args = CapabilityPolicy.to_docker_args(_profile())
    assert args["network"] == "none"


def test_write_filesystem_true_mounts_work_rw() -> None:
    args = CapabilityPolicy.to_docker_args(_profile(write_filesystem=True))
    assert "/work:rw" in args["volumes"]


def test_write_filesystem_false_mounts_work_ro() -> None:
    args = CapabilityPolicy.to_docker_args(_profile(write_filesystem=False))
    assert "/work:ro" in args["volumes"]


def test_privileged_is_always_false() -> None:
    """Even execute_shell=True must not escalate to privileged."""
    args = CapabilityPolicy.to_docker_args(_profile(execute_shell=True))
    assert args["privileged"] is False


def test_modify_git_state_mounts_git() -> None:
    args = CapabilityPolicy.to_docker_args(_profile(modify_git_state=True))
    assert any(".git" in v for v in args["volumes"])


def test_no_capabilities_dict_returns_safe_defaults() -> None:
    """A profile without a capabilities key gets the most restrictive args."""
    args = CapabilityPolicy.to_docker_args({})
    assert args["network"] == "none"
    assert args["privileged"] is False
    assert "/work:ro" in args["volumes"]
```

- [ ] **Step 2: Run, expect ImportError**

```bash
.venv/bin/python -m pytest tests/autopilot/scaffolders/test_capability_policy.py -v
```

- [ ] **Step 3: Implement**

`smadp/autopilot/scaffolders/capability_policy.py`:
```python
"""CapabilityPolicy: profile capabilities → docker run flags.

Translates the enriched-profile capability surface into the bounded set of
docker_args that the sandbox runner enforces at launch. The mapping is
deliberately conservative: missing/unknown capability defaults to the most
restrictive option.
"""

from __future__ import annotations

from typing import Any


class CapabilityPolicy:
    @staticmethod
    def to_docker_args(profile: dict[str, Any]) -> dict[str, Any]:
        caps = (profile.get("capabilities") or {}) if isinstance(profile, dict) else {}

        network_egress = caps.get("network_egress")
        if network_egress == "broad":
            network = "host"
        elif network_egress == "allowlisted":
            network = "bridge"
        else:
            network = "none"

        write_fs = bool(caps.get("write_filesystem"))
        volumes: list[str] = []
        volumes.append("/work:rw" if write_fs else "/work:ro")
        if caps.get("modify_git_state"):
            # Mount .git read-write so the agent can commit; sandbox uses
            # an ephemeral .git anyway, so this doesn't escape the container.
            volumes.append("/work/.git:rw")

        return {
            "network": network,
            "volumes": volumes,
            "privileged": False,  # never true; SMADP refuses to scale privilege
            "install_packages_allowed": bool(caps.get("install_packages")),
        }
```

- [ ] **Step 4: Tests pass**

```bash
.venv/bin/python -m pytest tests/autopilot/scaffolders/test_capability_policy.py -v
```
Expected: 9/9 PASS.

- [ ] **Step 5: Commit**

```bash
git add smadp/autopilot/scaffolders/capability_policy.py tests/autopilot/scaffolders/test_capability_policy.py
git commit -m "feat(scaffolders): CapabilityPolicy maps profile caps to docker_args"
```

---

## Task 3: Dockerfile + entrypoint + mcp.json templates

**Files:**
- Create: `smadp/autopilot/scaffolders/templates/python.Dockerfile`
- Create: `smadp/autopilot/scaffolders/templates/node.Dockerfile`
- Create: `smadp/autopilot/scaffolders/templates/go.Dockerfile`
- Create: `smadp/autopilot/scaffolders/templates/rust.Dockerfile`
- Create: `smadp/autopilot/scaffolders/templates/entrypoint.sh`
- Create: `smadp/autopilot/scaffolders/templates/mcp.json.tmpl`

These are pure asset files (no tests of their own; covered by scaffolder integration tests). Each is a Jinja2 template — variables are `{{slug}}`, `{{name}}`, `{{repo_url}}`, `{{commit_pin}}`, `{{description}}`, `{{capabilities_json}}`, `{{io_surfaces_json}}`, `{{docker_args_json}}`, `{{trust_floor}}`, `{{now_iso}}`.

- [ ] **Step 1: Write `python.Dockerfile`**

```dockerfile
# Generated by SMADP MCP Adapter Scaffolder. Do not edit by hand; rerun
# `smadp adapters scaffold --from-profile {{slug}}` to regenerate.
FROM python:3.11-slim

ARG REPO_URL={{repo_url}}
ARG COMMIT_PIN={{commit_pin}}

RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN git clone "$REPO_URL" . && git checkout "$COMMIT_PIN"

# Install: prefer pyproject.toml, fall back to requirements.txt, fall back to setup.py.
RUN if [ -f pyproject.toml ]; then pip install --no-cache-dir -e .; \
    elif [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; \
    elif [ -f setup.py ]; then pip install --no-cache-dir -e .; \
    else echo "no installable manifest"; exit 1; fi

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
```

- [ ] **Step 2: Write `node.Dockerfile`**

```dockerfile
# Generated by SMADP MCP Adapter Scaffolder.
FROM node:20-alpine

ARG REPO_URL={{repo_url}}
ARG COMMIT_PIN={{commit_pin}}

RUN apk add --no-cache git

WORKDIR /app
RUN git clone "$REPO_URL" . && git checkout "$COMMIT_PIN"
RUN npm install --no-audit --no-fund

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
```

- [ ] **Step 3: Write `go.Dockerfile`**

```dockerfile
# Generated by SMADP MCP Adapter Scaffolder.
FROM golang:1.21-alpine

ARG REPO_URL={{repo_url}}
ARG COMMIT_PIN={{commit_pin}}

RUN apk add --no-cache git

WORKDIR /app
RUN git clone "$REPO_URL" . && git checkout "$COMMIT_PIN"
RUN go build -o /usr/local/bin/agent ./...

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
```

- [ ] **Step 4: Write `rust.Dockerfile`**

```dockerfile
# Generated by SMADP MCP Adapter Scaffolder.
FROM rust:1.78-slim

ARG REPO_URL={{repo_url}}
ARG COMMIT_PIN={{commit_pin}}

RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates pkg-config libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN git clone "$REPO_URL" . && git checkout "$COMMIT_PIN"
RUN cargo build --release && cp target/release/* /usr/local/bin/ || true

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
```

- [ ] **Step 5: Write `entrypoint.sh`**

```bash
#!/usr/bin/env sh
# Generated by SMADP MCP Adapter Scaffolder. Receives the agent task via the
# SMADP_AGENT_TASK env var, writes it to /work/task.txt, then invokes the
# agent's binary. The {{agent_invocation}} placeholder is filled per-agent
# from the enriched profile's known CLI entrypoint (or "agent" fallback).
set -eu

mkdir -p /work
if [ -n "${SMADP_AGENT_TASK:-}" ]; then
  printf '%s\n' "$SMADP_AGENT_TASK" > /work/task.txt
fi

# Invoke the agent with the task path. {{agent_invocation}} is rendered at
# scaffold time — Python repos default to `python -m {{slug}}`, Node defaults
# to `npm start`, etc.
exec {{agent_invocation}}
```

- [ ] **Step 6: Write `mcp.json.tmpl`**

```jinja
{
  "schema_version": "1.0",
  "slug": "{{slug}}",
  "name": "{{name}}",
  "description": "{{description}}",
  "homepage": "{{homepage}}",
  "repo_url": "{{repo_url}}",
  "transport": "stdio",
  "scaffolded": true,
  "scaffolded_at": "{{now_iso}}",
  "command": ["sh", "-c", "/entrypoint.sh"],
  "env_required": {{env_required_json}},
  "env_optional": [],
  "image": "smadp/agent/{{slug}}:{{commit_pin_short}}",
  "image_digest_pinned": false,
  "capabilities": {{capabilities_json}},
  "io_surfaces": {{io_surfaces_json}},
  "trust_floor": {{trust_floor}},
  "docker_args": {{docker_args_json}},
  "notes": "Auto-scaffolded from {{repo_url}} @ {{commit_pin}}. Re-run `smadp adapters scaffold --from-profile {{slug}}` to refresh."
}
```

- [ ] **Step 7: Commit**

```bash
git add smadp/autopilot/scaffolders/templates
git commit -m "feat(scaffolders): Dockerfile + entrypoint + mcp.json Jinja2 templates"
```

---

## Task 4: MCPAdapterScaffolder + ScaffoldResult

**Files:**
- Create: `smadp/autopilot/scaffolders/mcp_adapter.py`
- Create: `tests/autopilot/scaffolders/test_mcp_adapter.py`
- Create: `tests/autopilot/scaffolders/fixtures/python_profile.json`

- [ ] **Step 1: Create fixture profile**

`tests/autopilot/scaffolders/fixtures/python_profile.json`:
```json
{
  "slug": "gpt-researcher",
  "name": "gpt-researcher",
  "category": "content-writing",
  "evidence_level": "docs-only",
  "homepage": "https://gptr.dev",
  "repo_url": "https://github.com/assafelovic/gpt-researcher",
  "tagline": "Autonomous research agent",
  "capabilities": {
    "execute_shell": false,
    "read_filesystem": true,
    "write_filesystem": true,
    "network_egress": "broad",
    "spawn_subprocesses": true,
    "use_mcp": true,
    "install_packages": true,
    "modify_git_state": false,
    "run_browsers": true
  },
  "io_surfaces": {
    "stdin_stdout": true,
    "files": ["PDF", "Markdown"],
    "clipboard": false,
    "screen_capture": false,
    "audio": false,
    "calls_apis": ["OpenAI API", "Tavily API"]
  },
  "permissions_requested": {
    "oauth_scopes": [],
    "secrets_handled": ["OPENAI_API_KEY", "TAVILY_API_KEY"],
    "elevated_privileges": []
  },
  "onexus": {
    "source_github": "assafelovic/gpt-researcher",
    "author_handle": "assafelovic",
    "tags": ["agent", "ai", "research"]
  }
}
```

- [ ] **Step 2: Write the failing test**

`tests/autopilot/scaffolders/test_mcp_adapter.py`:
```python
"""Tests for MCPAdapterScaffolder."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from smadp.autopilot.scaffolders.language_detector import Language
from smadp.autopilot.scaffolders.mcp_adapter import (
    MCPAdapterScaffolder,
    ScaffoldResult,
)


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _profile() -> dict:
    return json.loads((FIXTURES / "python_profile.json").read_text())


def _detector(language: Language = Language.PYTHON):
    det = MagicMock()
    det.detect = MagicMock(return_value=language)
    return det


def test_scaffold_writes_four_files(tmp_path: Path) -> None:
    sc = MCPAdapterScaffolder(detector=_detector(), commit_pin_resolver=lambda gh: "abc123")
    result = sc.scaffold(_profile(), target_dir=tmp_path / "gpt-researcher")
    assert result.success
    files = {p.name for p in result.files_written}
    assert files == {"Dockerfile", "entrypoint.sh", "mcp.json", ".scaffolded.json"}


def test_scaffold_fails_when_no_github_source(tmp_path: Path) -> None:
    profile = {"slug": "x", "name": "X", "evidence_level": "docs-only"}
    sc = MCPAdapterScaffolder(detector=_detector(), commit_pin_resolver=lambda gh: "abc")
    result = sc.scaffold(profile, target_dir=tmp_path / "x")
    assert not result.success
    assert result.reason == "no_github_source"


def test_scaffold_fails_when_unsupported_language(tmp_path: Path) -> None:
    sc = MCPAdapterScaffolder(
        detector=_detector(Language.UNSUPPORTED),
        commit_pin_resolver=lambda gh: "abc",
    )
    result = sc.scaffold(_profile(), target_dir=tmp_path / "x")
    assert not result.success
    assert result.reason == "unsupported_language"


def test_scaffold_fails_when_profile_not_enriched(tmp_path: Path) -> None:
    profile = _profile()
    profile["evidence_level"] = "unverified-profile"
    sc = MCPAdapterScaffolder(detector=_detector(), commit_pin_resolver=lambda gh: "abc")
    result = sc.scaffold(profile, target_dir=tmp_path / "x")
    assert not result.success
    assert result.reason == "profile_not_enriched"


def test_mcp_json_validates_against_existing_adapter_shape(tmp_path: Path) -> None:
    sc = MCPAdapterScaffolder(detector=_detector(), commit_pin_resolver=lambda gh: "abc123def")
    result = sc.scaffold(_profile(), target_dir=tmp_path / "gpt-researcher")
    mcp = json.loads((tmp_path / "gpt-researcher" / "mcp.json").read_text())
    for required in (
        "schema_version",
        "slug",
        "name",
        "repo_url",
        "command",
        "env_required",
        "image",
        "capabilities",
        "io_surfaces",
        "trust_floor",
        "docker_args",
    ):
        assert required in mcp, f"missing required key: {required}"
    assert mcp["scaffolded"] is True
    assert mcp["capabilities"]["network_egress"] == "broad"
    assert mcp["docker_args"]["network"] == "host"   # broad → host
    assert "OPENAI_API_KEY" in mcp["env_required"]


def test_dockerfile_pins_repo_url_and_commit(tmp_path: Path) -> None:
    sc = MCPAdapterScaffolder(detector=_detector(), commit_pin_resolver=lambda gh: "abc123")
    sc.scaffold(_profile(), target_dir=tmp_path / "gpt-researcher")
    dockerfile = (tmp_path / "gpt-researcher" / "Dockerfile").read_text()
    assert "https://github.com/assafelovic/gpt-researcher" in dockerfile
    assert "abc123" in dockerfile
    assert dockerfile.startswith("# Generated by SMADP")


def test_provenance_metadata_written(tmp_path: Path) -> None:
    sc = MCPAdapterScaffolder(detector=_detector(), commit_pin_resolver=lambda gh: "abc")
    result = sc.scaffold(_profile(), target_dir=tmp_path / "gpt-researcher")
    prov = json.loads((tmp_path / "gpt-researcher" / ".scaffolded.json").read_text())
    assert prov["slug"] == "gpt-researcher"
    assert prov["language"] == "python"
    assert prov["commit_pin"] == "abc"
    assert "scaffolded_at" in prov
```

- [ ] **Step 3: Run, expect ImportError**

```bash
.venv/bin/python -m pytest tests/autopilot/scaffolders/test_mcp_adapter.py -v
```

- [ ] **Step 4: Implement**

`smadp/autopilot/scaffolders/mcp_adapter.py`:
```python
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

# Agent CLI invocation per language. Falls back to `agent` if no convention is
# obvious. This is a heuristic, not magic — operators are expected to refine
# the entrypoint after smoke tests for stubborn agents.
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
        self._env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(_TEMPLATES_DIR)),
            autoescape=False,
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
        env_required = (
            (profile.get("permissions_requested") or {}).get("secrets_handled") or []
        )

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

        # Dockerfile
        dockerfile_template = self._env.get_template(_LANGUAGE_TO_DOCKERFILE[language])
        written.append(
            self._atomic_write(target_dir / "Dockerfile", dockerfile_template.render(**template_vars))
        )

        # entrypoint.sh
        entrypoint_template = self._env.get_template("entrypoint.sh")
        written.append(
            self._atomic_write(target_dir / "entrypoint.sh", entrypoint_template.render(**template_vars))
        )

        # mcp.json
        mcp_template = self._env.get_template("mcp.json.tmpl")
        written.append(self._atomic_write(target_dir / "mcp.json", mcp_template.render(**template_vars)))

        # .scaffolded.json provenance
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
            self._atomic_write(target_dir / ".scaffolded.json", json.dumps(provenance, indent=2) + "\n")
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
```

- [ ] **Step 5: Tests pass**

```bash
.venv/bin/python -m pytest tests/autopilot/scaffolders/test_mcp_adapter.py -v
```
Expected: 7/7 PASS.

- [ ] **Step 6: Commit**

```bash
git add smadp/autopilot/scaffolders/mcp_adapter.py tests/autopilot/scaffolders/test_mcp_adapter.py tests/autopilot/scaffolders/fixtures
git commit -m "feat(scaffolders): MCPAdapterScaffolder generates Dockerfile + mcp.json + provenance"
```

---

## Task 5: Docker build verification helper

**Files:**
- Create: `smadp/autopilot/scaffolders/docker_verify.py`
- Create: `tests/autopilot/scaffolders/test_docker_verify.py`

- [ ] **Step 1: Write the failing test**

`tests/autopilot/scaffolders/test_docker_verify.py`:
```python
"""Tests for verify_adapter_build."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from smadp.autopilot.scaffolders.docker_verify import (
    DockerVerifyResult,
    docker_available,
    verify_adapter_build,
)


def _make_adapter_dir(tmp_path: Path) -> Path:
    d = tmp_path / "myagent"
    d.mkdir()
    (d / "Dockerfile").write_text("FROM busybox\n")
    (d / "mcp.json").write_text("{}")
    return d


def test_returns_skipped_when_docker_missing(tmp_path: Path) -> None:
    adapter = _make_adapter_dir(tmp_path)
    with patch("smadp.autopilot.scaffolders.docker_verify.docker_available", return_value=False):
        result = verify_adapter_build(adapter, image_tag="smadp/agent/myagent:latest")
    assert result.skipped
    assert result.reason == "docker_unavailable"


def test_returns_success_when_docker_build_returns_zero(tmp_path: Path) -> None:
    adapter = _make_adapter_dir(tmp_path)
    fake = type("CP", (), {"returncode": 0, "stdout": b"built", "stderr": b""})()
    with patch("smadp.autopilot.scaffolders.docker_verify.docker_available", return_value=True), \
         patch("smadp.autopilot.scaffolders.docker_verify.subprocess.run", return_value=fake):
        result = verify_adapter_build(adapter, image_tag="smadp/agent/myagent:latest")
    assert result.success
    assert not result.skipped


def test_returns_failure_when_docker_build_returns_nonzero(tmp_path: Path) -> None:
    adapter = _make_adapter_dir(tmp_path)
    fake = type("CP", (), {"returncode": 1, "stdout": b"", "stderr": b"build failed"})()
    with patch("smadp.autopilot.scaffolders.docker_verify.docker_available", return_value=True), \
         patch("smadp.autopilot.scaffolders.docker_verify.subprocess.run", return_value=fake):
        result = verify_adapter_build(adapter, image_tag="smadp/agent/myagent:latest")
    assert not result.success
    assert "build failed" in result.build_log_tail
```

- [ ] **Step 2: Run, expect ImportError**

```bash
.venv/bin/python -m pytest tests/autopilot/scaffolders/test_docker_verify.py -v
```

- [ ] **Step 3: Implement**

`smadp/autopilot/scaffolders/docker_verify.py`:
```python
"""Docker build verification for scaffolded adapters."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DockerVerifyResult:
    success: bool
    skipped: bool = False
    reason: str = ""
    image_tag: str = ""
    build_log_tail: str = ""


def docker_available() -> bool:
    return shutil.which("docker") is not None


def verify_adapter_build(
    adapter_dir: Path,
    *,
    image_tag: str,
    timeout_s: int = 600,
) -> DockerVerifyResult:
    """Run `docker build` inside adapter_dir and report the outcome.

    On systems without docker installed, returns skipped=True so the smoke
    can fail-soft on dev machines without Docker.
    """
    if not docker_available():
        return DockerVerifyResult(
            success=False, skipped=True, reason="docker_unavailable", image_tag=image_tag
        )

    try:
        completed = subprocess.run(
            ["docker", "build", "-t", image_tag, str(adapter_dir)],
            capture_output=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return DockerVerifyResult(
            success=False,
            reason="build_timeout",
            image_tag=image_tag,
            build_log_tail=f"timed out after {timeout_s}s",
        )

    tail = (completed.stderr or completed.stdout or b"").decode("utf-8", errors="replace")
    tail = tail[-4000:]   # cap so .scaffolded.json doesn't bloat
    if completed.returncode != 0:
        return DockerVerifyResult(
            success=False,
            reason="build_failed",
            image_tag=image_tag,
            build_log_tail=tail,
        )
    return DockerVerifyResult(success=True, image_tag=image_tag, build_log_tail=tail)
```

- [ ] **Step 4: Tests pass**

```bash
.venv/bin/python -m pytest tests/autopilot/scaffolders/test_docker_verify.py -v
```
Expected: 3/3 PASS.

- [ ] **Step 5: Commit**

```bash
git add smadp/autopilot/scaffolders/docker_verify.py tests/autopilot/scaffolders/test_docker_verify.py
git commit -m "feat(scaffolders): docker build verification helper with fail-soft on no-docker"
```

---

## Task 6: CLI — `smadp adapters scaffold --from-profile <slug>`

**Files:**
- Modify: `smadp/cli.py` (add `adapters` group + `adapters scaffold` subcommand)

- [ ] **Step 1: Find the existing CLI group anchor**

Open `smadp/cli.py`, find the existing `autopilot` group definition (search for `def autopilot() -> None:`). The new `adapters` group will sit alongside it at the same indentation.

- [ ] **Step 2: Add the new group + scaffold command**

Append after the last `@autopilot.command(...)` block:

```python
# ----------------------------------------------------------- adapters
@cli.group()
def adapters() -> None:
    """MCP adapter scaffolding (Docker image + mcp.json generator)."""


@adapters.command("scaffold")
@click.option("--from-profile", "slug", required=True, help="Slug of an enriched profile.")
@click.option(
    "--commit-pin",
    default=None,
    help="Pin to a specific commit SHA. Defaults to HEAD of the repo's default branch.",
)
@click.option("--no-verify", is_flag=True, help="Skip docker build verification.")
@click.pass_context
def adapters_scaffold(
    ctx: click.Context, slug: str, commit_pin: str | None, no_verify: bool
) -> None:
    """Generate a Dockerfile + mcp.json adapter for an enriched profile."""
    import json
    import os
    from smadp.autopilot.scaffolders.docker_verify import verify_adapter_build
    from smadp.autopilot.scaffolders.language_detector import GithubMetadataLanguageDetector
    from smadp.autopilot.scaffolders.mcp_adapter import MCPAdapterScaffolder

    config = ctx.obj["config"]
    profile_path = config.repo_root / "catalog" / "profiles" / f"{slug}.json"
    if not profile_path.exists():
        raise click.ClickException(f"profile not found: {profile_path}")
    profile = json.loads(profile_path.read_text("utf-8"))

    token = os.environ.get("GITHUB_TOKEN")
    detector = GithubMetadataLanguageDetector(token=token)

    def resolve_pin(github_source: str) -> str:
        if commit_pin:
            return commit_pin
        # Fall back to HEAD literal — the Dockerfile's `git clone` + `git checkout`
        # will still resolve it at build time. The scaffolder records this in the
        # .scaffolded.json so operators can later pin to a real SHA via --commit-pin.
        return "HEAD"

    scaffolder = MCPAdapterScaffolder(detector=detector, commit_pin_resolver=resolve_pin)
    target_dir = config.repo_root / "adapters" / slug
    result = scaffolder.scaffold(profile, target_dir=target_dir)

    click.echo(f"scaffold: success={result.success} reason={result.reason} dir={result.target_dir}")
    if not result.success:
        raise click.ClickException(f"scaffold failed: {result.reason}")

    if no_verify:
        click.echo("skip-verify: per --no-verify flag")
        return

    verify = verify_adapter_build(
        result.target_dir, image_tag=f"smadp/agent/{slug}:scaffold"
    )
    click.echo(
        f"verify: success={verify.success} skipped={verify.skipped} reason={verify.reason}"
    )
    if not verify.success and not verify.skipped:
        # Attach the build log tail to .scaffolded.json for debugging without
        # spamming the terminal.
        prov_path = result.target_dir / ".scaffolded.json"
        prov = json.loads(prov_path.read_text("utf-8"))
        prov["verify"] = {
            "success": False,
            "reason": verify.reason,
            "build_log_tail": verify.build_log_tail,
        }
        prov_path.write_text(json.dumps(prov, indent=2) + "\n", encoding="utf-8")
        raise click.ClickException(f"docker build failed: see {prov_path}")
```

- [ ] **Step 3: Smoke the CLI wiring**

```bash
cd "/Users/connorevans/Desktop/Frontier_AI/Safe Multi-Agent Deployment Platform (SMADP)/SMADP"
.venv/bin/python -m smadp.cli adapters --help
.venv/bin/python -m smadp.cli adapters scaffold --help
```
Expected: `scaffold` subcommand listed, help text shows --from-profile, --commit-pin, --no-verify options.

- [ ] **Step 4: Commit**

```bash
git add smadp/cli.py
git commit -m "feat(cli): smadp adapters scaffold --from-profile <slug>"
```

---

## Task 7: Integration self-test (scaffold from fixture + lint mcp.json)

**Files:**
- Modify: `tests/autopilot/scaffolders/test_mcp_adapter.py` (append integration check)

- [ ] **Step 1: Append the integration test**

```python
def test_scaffolded_mcp_json_matches_existing_aider_schema(tmp_path: Path) -> None:
    """Spot-check: the keys we emit are a subset of what adapters/aider/mcp.json has."""
    sc = MCPAdapterScaffolder(detector=_detector(), commit_pin_resolver=lambda gh: "abc")
    sc.scaffold(_profile(), target_dir=tmp_path / "gpt-researcher")
    generated = json.loads((tmp_path / "gpt-researcher" / "mcp.json").read_text())

    # Required keys per the existing hand-curated aider adapter:
    required_keys = {
        "schema_version", "slug", "name", "description", "homepage", "repo_url",
        "transport", "command", "env_required", "env_optional", "image",
        "capabilities", "io_surfaces", "trust_floor",
    }
    missing = required_keys - generated.keys()
    assert not missing, f"missing keys: {missing}"
    # Scaffold-only additions are fine:
    assert "scaffolded" in generated
    assert "docker_args" in generated
    assert ".scaffolded.json" not in generated   # provenance is a sibling, not nested
```

- [ ] **Step 2: Run integration test**

```bash
.venv/bin/python -m pytest tests/autopilot/scaffolders/test_mcp_adapter.py::test_scaffolded_mcp_json_matches_existing_aider_schema -v
```
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/autopilot/scaffolders/test_mcp_adapter.py
git commit -m "test(scaffolders): mcp.json output matches existing hand-curated adapter schema"
```

---

## Task 8: 5-agent smoke (tonight's terminal deliverable)

**Files:** None — this is the manual validation gate that gates launchd activation later.

- [ ] **Step 1: Verify docker is installed**

```bash
docker --version
```
Expected: `Docker version ...`. If docker isn't installed, install Docker Desktop first (https://docs.docker.com/get-docker/) — the smoke can't proceed without it.

- [ ] **Step 2: Confirm the 5 profiles are enriched on disk**

```bash
cd "/Users/connorevans/Desktop/Frontier_AI/Safe Multi-Agent Deployment Platform (SMADP)/SMADP"
for s in gpt-researcher autogpt crewai langgraph continue-dev; do
  level=$(.venv/bin/python -c "import json; print(json.load(open('catalog/profiles/'+'$s'+'.json'))['evidence_level'])")
  printf '%-15s %s\n' "$s" "$level"
done
```
Expected: each prints `docs-only` (or higher). If any print `unverified-profile`, run `smadp autopilot docs-only-tick --batch-size 1` until it gets enriched, or hand-pick a different agent.

- [ ] **Step 3: Scaffold each agent**

```bash
set -a; source .env; set +a   # load OPENAI_API_KEY + GITHUB_TOKEN
for s in gpt-researcher autogpt crewai langgraph continue-dev; do
  echo "=== scaffolding $s ==="
  .venv/bin/python -m smadp.cli adapters scaffold --from-profile "$s" --no-verify 2>&1 | tail -3
done
```
Expected each line: `scaffold: success=True reason=ok dir=adapters/<slug>`.

If any agent fails with `unsupported_language`, that's fine — note which and move on (the spec calls for 3/5 buildable, not 5/5).

- [ ] **Step 4: Docker-build each scaffolded adapter**

```bash
for s in gpt-researcher autogpt crewai langgraph continue-dev; do
  if [ -d "adapters/$s" ]; then
    echo "=== docker build $s ==="
    docker build -t "smadp/agent/$s:scaffold" "adapters/$s" 2>&1 | tail -3
  fi
done
```
Expected at least 3/5 end with `Successfully built ...` or `Successfully tagged smadp/agent/<slug>:scaffold`. The other 2 may legitimately fail (missing dependency, unusual install script, etc.) — capture which in step 6.

- [ ] **Step 5: Validate mcp.json shape for each successful scaffold**

```bash
for s in gpt-researcher autogpt crewai langgraph continue-dev; do
  if [ -f "adapters/$s/mcp.json" ]; then
    echo "=== $s ==="
    .venv/bin/python -c "
import json
m = json.load(open('adapters/$s/mcp.json'))
needed = {'schema_version','slug','name','repo_url','command','env_required','image','capabilities','io_surfaces','trust_floor','docker_args'}
missing = needed - set(m)
print('missing:' if missing else 'all required keys present', missing or '')
print('docker_args.network:', m['docker_args']['network'])
"
  fi
done
```
Expected: each scaffolded agent prints `all required keys present`.

- [ ] **Step 6: Tally results — halt criteria**

After steps 3–5, you should have:
- Number of scaffolds that produced a complete adapter dir: ≥ 5 (one per attempted agent) OR fewer if some hit `unsupported_language`.
- Number of Docker builds that returned 0: must be ≥ 3 to clear the smoke.
- Number of mcp.json files validating against the existing-adapter shape: must equal the number of successful scaffolds.

**Halt criteria — do NOT activate scaffolder for bulk runs if any of these are true:**
- Fewer than 3 successful docker builds.
- Any scaffolded mcp.json has missing required keys.
- Any scaffolded adapter dir is missing one of: Dockerfile, entrypoint.sh, mcp.json, .scaffolded.json.

- [ ] **Step 7: Commit the 5 (or fewer) scaffolded adapter dirs**

```bash
git add adapters/gpt-researcher adapters/autogpt adapters/crewai adapters/langgraph adapters/continue-dev 2>/dev/null
git status --short adapters/
git commit -m "chore(adapters): seed scaffolded adapters from 5-agent smoke"
```

(`git add` will silently skip any dir that wasn't created if scaffold failed.)

- [ ] **Step 8: One bonus sanity check — sandbox can SEE the adapter**

```bash
for s in gpt-researcher autogpt crewai langgraph continue-dev; do
  if [ -f "adapters/$s/mcp.json" ]; then
    echo "=== load_adapter_capabilities $s ==="
    .venv/bin/python -c "
from smadp.sandbox.binding import load_adapter_capabilities
from smadp.config import Config
caps = load_adapter_capabilities('$s', config=Config())
print('execute_shell:', caps.execute_shell if hasattr(caps,'execute_shell') else 'n/a')
print('network_egress:', caps.network_egress if hasattr(caps,'network_egress') else 'n/a')
"
  fi
done
```
Expected: each successfully-scaffolded adapter loads without error. The existing sandbox runner can now in principle pair this agent with another in a sandbox scenario.

---

## Self-review

**Spec coverage:**

| Spec section | Implementing task(s) |
| --- | --- |
| `LanguageDetector` (Python/Node/Go/Rust/Unsupported) | T1 |
| `CapabilityPolicy` (caps → docker_args) | T2 |
| Dockerfile templates (4 languages) | T3 |
| `entrypoint.sh` template | T3 |
| `mcp.json.tmpl` template | T3 |
| `MCPAdapterScaffolder.scaffold` (orchestration + atomic writes + provenance) | T4 |
| Docker build verification helper | T5 |
| CLI: `smadp adapters scaffold` | T6 |
| Integration check — matches existing adapter shape | T7 |
| 5-agent smoke (acceptance gate) | T8 |
| Spec's optional Task 8 (bulk scaffold) | Deferred — not in tonight's scope per the user |

**Placeholder scan:** no TBDs. Every step has runnable code or a runnable command with expected output.

**Type consistency:**
- `Language` enum values (`PYTHON`, `NODE`, `GO`, `RUST`, `UNSUPPORTED`) used consistently in T1, T4.
- `ScaffoldResult(target_dir, files_written, language, success, reason)` returned by T4, consumed by T6.
- `DockerVerifyResult(success, skipped, reason, image_tag, build_log_tail)` returned by T5, consumed by T6.
- `CapabilityPolicy.to_docker_args(profile) -> dict[str, Any]` shape matches what T4 plugs into the mcp.json template.
- Scaffolder constructor signature `(detector, commit_pin_resolver)` matches what the CLI passes in T6.
- Template variable names in T3 (`{{slug}}`, `{{repo_url}}`, `{{commit_pin}}`, `{{capabilities_json}}`, etc.) match the dict T4 builds.

**Cost / runtime model:**
- T1–T7 are all dev work; no LLM calls; no real network unless tests mock incorrectly.
- T8 makes real GitHub API calls (5 total, well under any rate limit) + 5 real `docker build` runs (~30-90s each on first build).
- Disk: ~200-500MB per built image × 5 ≈ 1.5-2.5GB.
- T8 makes no LLM calls — capability data comes from the existing enriched profiles on disk.

No mismatches found.
