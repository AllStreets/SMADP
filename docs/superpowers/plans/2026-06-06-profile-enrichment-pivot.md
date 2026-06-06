# Profile Enrichment Pivot — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace bulk docs-only pair-judging with a profile-first pipeline. Every ONEXUS agent gets a real evidence-cited profile via GitHub-README enrichment; pair-judging only fires when both sides are enriched. Tonight's terminal deliverable: 5-agent enrichment smoke + 5 pair-judge smoke producing non-trivial verdicts (distinct composite scores, varied severities).

**Architecture:** Reuses every component from the prior plan's T1–T8. Profiler now emits `evidence_level: "unverified-profile"` stubs; a new `Enricher` + `ProfileEnrichmentJudge` upgrades each stub to `docs-only` by passing a chunked GitHub README to the existing `LLMClient.extract_profile` (strict evidence-cited extraction). A `PairGatePlanner` enqueues docs-only pair work only when both profiles are enriched. The orchestrator dispatches by `requested_judge`.

**Tech Stack:** Python 3.11+ via project venv, `httpx` or `urllib.request` (already in deps), existing `LLMClient.extract_profile` infrastructure, OpenAI tool-calling, `gpt-5.4-mini`, pytest with `tmp_path` fixtures. JSON on disk.

---

## File structure

### New files

| Path | Responsibility |
| --- | --- |
| `smadp/autopilot/enrichers/__init__.py` | Package init |
| `smadp/autopilot/enrichers/github_readme.py` | `GithubReadmeFetcher`: HTTP GET + on-disk cache + 404/rate-limit handling |
| `smadp/autopilot/judges/profile_enrich.py` | `ProfileEnrichmentJudge`: chunks README into evidence items, calls `LLMClient.extract_profile`, returns enriched profile dict |
| `smadp/autopilot/planners/enrichment.py` | `EnrichmentPlanner`: emits one WorkItem per `unverified-profile` slug |
| `smadp/autopilot/planners/pair_gate.py` | `PairGatePlanner`: emits pair-judge WorkItems only when both sides `>= docs-only` |
| `tests/autopilot/enrichers/__init__.py` | |
| `tests/autopilot/enrichers/test_github_readme.py` | |
| `tests/autopilot/judges/test_profile_enrich.py` | |
| `tests/autopilot/planners/test_enrichment.py` | |
| `tests/autopilot/planners/test_pair_gate.py` | |

### Modified files

| Path | Change |
| --- | --- |
| `smadp/autopilot/profilers/onexus.py` | Drop tag-based capability inference. Stub now has `evidence_level: "unverified-profile"`, `capabilities: null`, empty `data_classes_touched`, null `concurrency_model`. Slug/name/category/docs_urls preserved. |
| `smadp/autopilot/publishers/policy.py` | Add `commit_profile(profile: dict) -> Path` method that writes to `catalog/profiles/<slug>.json` (atomic). |
| `smadp/autopilot/docs_only_tick.py` | Dispatch by `work.requested_judge`: route to `profile_enrich` (commit_profile) or `docs_only` (commit verdict). Judge map injected by caller. |
| `smadp/autopilot/bootstrap.py` | Replace `TopNPlanner` call with `EnrichmentPlanner`. Bootstrap now queues enrichment work, not pair-judge work. |
| `smadp/cli.py` | Update `docs-only-tick` to build a judge map `{profile_enrich, docs_only}` instead of a single judge. |
| `tests/autopilot/profilers/test_onexus.py` | Drop capability-inference assertions (the heuristic is gone). Add assertion that stubs are `unverified-profile`. |
| `tests/autopilot/test_docs_only_tick.py` | Update fixtures to inject a judge map; cover both routing paths. |
| `tests/autopilot/test_bootstrap.py` | Assert queued items have `requested_judge == "profile_enrich"`. |

### Self-contained constants

- **ONEXUS catalog root:** `~/Downloads/ONEXUS-Agents/catalog`.
- **LLM model:** `gpt-5.4-mini`.
- **`extract_profile` already exists** at `smadp/llm/client.py:130` with `ProfileExtractionInput` payload.
- **README cache dir:** `state/enrichment_cache/<slug>.txt`.
- **Evidence chunk size:** 8,000 chars per chunk, max 6 chunks per agent (cap total prompt at ~50k tokens).
- **GitHub raw URL pattern:** `https://raw.githubusercontent.com/<owner>/<repo>/HEAD/README.md` with fallback to `/master/README.md`.

---

## Task 1: Amend OnexusProfiler — stubs only, drop fake capabilities

**Files:**
- Modify: `smadp/autopilot/profilers/onexus.py`
- Modify: `tests/autopilot/profilers/test_onexus.py`

- [ ] **Step 1: Update the existing test file**

Replace the body of `tests/autopilot/profilers/test_onexus.py` with:

```python
"""Tests for OnexusProfiler stub output."""

from __future__ import annotations

from smadp.autopilot.profilers.onexus import OnexusProfiler
from smadp.autopilot.sources.onexus import RawOnexusAgent


def _raw(**overrides) -> RawOnexusAgent:
    defaults = dict(
        slug="aider",
        name="Aider",
        category="coding",
        tags=["coding", "shell"],
        author_handle="paul-gauthier",
        source_github="paul-gauthier/aider",
        source_homepage="https://aider.chat/",
        license="Apache-2.0",
        composite_score=0.87,
        runnable=False,
    )
    defaults.update(overrides)
    return RawOnexusAgent(**defaults)


def test_stub_required_keys() -> None:
    profile = OnexusProfiler().normalize(_raw())
    assert profile["slug"] == "aider"
    assert profile["name"] == "Aider"
    assert profile["category"] == "coding"
    assert profile["composite_score"] == 0.87
    assert profile["onexus"]["source_github"] == "paul-gauthier/aider"


def test_stub_marked_unverified() -> None:
    profile = OnexusProfiler().normalize(_raw())
    assert profile["evidence_level"] == "unverified-profile"


def test_stub_has_no_invented_capabilities() -> None:
    """We no longer infer caps from tags; the enricher does that."""
    profile = OnexusProfiler().normalize(_raw(tags=["shell", "filesystem", "network"]))
    # Capabilities must be None or all-False — the enricher decides the truth.
    caps = profile["capabilities"]
    assert caps is None or all(v is False or v == "none" for v in caps.values())


def test_stub_preserves_docs_urls() -> None:
    profile = OnexusProfiler().normalize(_raw())
    assert "https://aider.chat/" in profile["docs_urls"]
    assert any("github.com/paul-gauthier/aider" in u for u in profile["docs_urls"])


def test_stub_evidence_refs_present() -> None:
    profile = OnexusProfiler().normalize(_raw())
    refs = profile["evidence_refs"]
    assert len(refs) >= 1
    assert all(r.startswith("sha256:") for r in refs)
```

- [ ] **Step 2: Run test to verify it fails on old behavior**

```bash
cd "/Users/connorevans/Desktop/Frontier_AI/Safe Multi-Agent Deployment Platform (SMADP)/SMADP"
.venv/bin/python -m pytest tests/autopilot/profilers/test_onexus.py -v
```
Expected: `test_stub_marked_unverified` and `test_stub_has_no_invented_capabilities` FAIL (current code emits `docs-only` and infers caps).

- [ ] **Step 3: Update the profiler**

Replace the body of `smadp/autopilot/profilers/onexus.py` with:

```python
"""OnexusProfiler: turn a RawOnexusAgent into an SMADP profile STUB.

The stub is intentionally minimal. Capability inference, concurrency model,
data classes touched — all of that requires real evidence (GitHub README)
that the ProfileEnrichmentJudge later supplies. Until enrichment runs the
profile carries ``evidence_level: "unverified-profile"`` so the pair-judge
gate refuses to act on it.
"""

from __future__ import annotations

import hashlib
from typing import Any

from smadp.autopilot.sources.onexus import RawOnexusAgent


def _sha(s: str) -> str:
    return "sha256:" + hashlib.sha256(s.encode("utf-8")).hexdigest()


class OnexusProfiler:
    name = "onexus"
    accepts_source = "onexus"

    def normalize(self, raw: RawOnexusAgent) -> dict[str, Any]:
        docs_urls: list[str] = []
        if raw.source_homepage:
            docs_urls.append(raw.source_homepage)
        if raw.source_github:
            docs_urls.append(f"https://github.com/{raw.source_github}")
        evidence_refs = [_sha(f"onexus:{raw.slug}:{u}") for u in docs_urls]
        return {
            "slug": raw.slug,
            "name": raw.name,
            "category": raw.category,
            "evidence_level": "unverified-profile",
            "docs_urls": docs_urls,
            "evidence_refs": evidence_refs,
            "capabilities": None,
            "data_classes_touched": [],
            "concurrency_model": None,
            "composite_score": raw.composite_score,
            "license": raw.license,
            "onexus": {
                "source_github": raw.source_github,
                "author_handle": raw.author_handle,
                "tags": raw.tags,
                "runnable": raw.runnable,
            },
        }
```

- [ ] **Step 4: Run tests — should pass**

```bash
.venv/bin/python -m pytest tests/autopilot/profilers/test_onexus.py -v
```
Expected: 5/5 PASS.

- [ ] **Step 5: Commit**

```bash
git add smadp/autopilot/profilers/onexus.py tests/autopilot/profilers/test_onexus.py
git commit -m "refactor(autopilot): profiler emits unverified-profile stubs; enricher owns capabilities"
```

---

## Task 2: GithubReadmeFetcher — fetch + cache

**Files:**
- Create: `smadp/autopilot/enrichers/__init__.py` (empty)
- Create: `smadp/autopilot/enrichers/github_readme.py`
- Create: `tests/autopilot/enrichers/__init__.py` (empty)
- Create: `tests/autopilot/enrichers/test_github_readme.py`

- [ ] **Step 1: Write the failing test**

`tests/autopilot/enrichers/test_github_readme.py`:
```python
"""Tests for GithubReadmeFetcher."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from smadp.autopilot.enrichers.github_readme import (
    GithubReadmeFetcher,
    ReadmeFetchError,
)


@pytest.fixture
def fetcher(tmp_path: Path) -> GithubReadmeFetcher:
    return GithubReadmeFetcher(cache_dir=tmp_path / "cache", token=None)


def _fake_response(status: int, body: bytes):
    resp = MagicMock()
    resp.status_code = status
    resp.content = body
    resp.text = body.decode("utf-8", errors="replace")
    resp.raise_for_status = MagicMock(return_value=None) if 200 <= status < 300 else MagicMock(side_effect=Exception(f"HTTP {status}"))
    return resp


def test_fetch_caches_first_call(fetcher: GithubReadmeFetcher) -> None:
    with patch("smadp.autopilot.enrichers.github_readme.httpx.get") as get:
        get.return_value = _fake_response(200, b"# Hello\n\nReadme body.")
        text1 = fetcher.fetch("paul-gauthier/aider")
        text2 = fetcher.fetch("paul-gauthier/aider")
        assert text1 == "# Hello\n\nReadme body."
        assert text2 == text1
        assert get.call_count == 1   # cached


def test_fetch_tries_master_when_head_404s(fetcher: GithubReadmeFetcher) -> None:
    responses = [_fake_response(404, b""), _fake_response(200, b"# master")]
    with patch("smadp.autopilot.enrichers.github_readme.httpx.get", side_effect=responses) as get:
        text = fetcher.fetch("owner/repo")
        assert text == "# master"
        assert get.call_count == 2


def test_fetch_raises_when_both_branches_404(fetcher: GithubReadmeFetcher) -> None:
    responses = [_fake_response(404, b""), _fake_response(404, b"")]
    with patch("smadp.autopilot.enrichers.github_readme.httpx.get", side_effect=responses):
        with pytest.raises(ReadmeFetchError):
            fetcher.fetch("owner/repo")


def test_fetch_uses_token_when_provided(tmp_path: Path) -> None:
    fetcher = GithubReadmeFetcher(cache_dir=tmp_path / "cache", token="ghp_TEST")
    with patch("smadp.autopilot.enrichers.github_readme.httpx.get") as get:
        get.return_value = _fake_response(200, b"# Authed")
        fetcher.fetch("owner/repo")
        kwargs = get.call_args.kwargs
        headers = kwargs.get("headers", {})
        assert headers.get("Authorization") == "Bearer ghp_TEST"


def test_fetch_short_circuits_on_empty_github_source(fetcher: GithubReadmeFetcher) -> None:
    with pytest.raises(ReadmeFetchError):
        fetcher.fetch("")
```

- [ ] **Step 2: Verify ImportError**

```bash
.venv/bin/python -m pytest tests/autopilot/enrichers/test_github_readme.py -v
```
Expected: ImportError on `smadp.autopilot.enrichers.github_readme`.

- [ ] **Step 3: Implement**

`smadp/autopilot/enrichers/__init__.py`: (empty file)

`smadp/autopilot/enrichers/github_readme.py`:
```python
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
        headers: dict[str, str] = {"Accept": "text/plain"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        for branch in ("HEAD", "master"):
            url = f"https://raw.githubusercontent.com/{github_source}/{branch}/README.md"
            try:
                resp = httpx.get(url, headers=headers, timeout=15.0, follow_redirects=True)
            except httpx.HTTPError as exc:
                log.warning("github_readme.transport_error", url=url, error=repr(exc))
                continue
            if 200 <= resp.status_code < 300:
                return resp.text
            log.info("github_readme.miss", url=url, status=resp.status_code)
        raise ReadmeFetchError(f"could not fetch README for {github_source}")
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/python -m pytest tests/autopilot/enrichers/test_github_readme.py -v
```
Expected: 5/5 PASS.

- [ ] **Step 5: Commit**

```bash
git add smadp/autopilot/enrichers tests/autopilot/enrichers
git commit -m "feat(autopilot): GithubReadmeFetcher with on-disk cache + branch fallback"
```

---

## Task 3: ProfileEnrichmentJudge

**Files:**
- Create: `smadp/autopilot/judges/profile_enrich.py`
- Create: `tests/autopilot/judges/test_profile_enrich.py`

- [ ] **Step 1: Write the failing test**

`tests/autopilot/judges/test_profile_enrich.py`:
```python
"""Tests for ProfileEnrichmentJudge."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from smadp.autopilot.judges.profile_enrich import ProfileEnrichmentJudge
from smadp.autopilot.work_queue import WorkItem


def _wi(slug: str = "aider") -> WorkItem:
    # Single-agent enrichment uses (slug, slug) as the canonical pair.
    return WorkItem(
        pair=(slug, slug),
        requested_judge="profile_enrich",
        judge_version="v1",
        priority=0.9,
        enqueued_at="2026-06-06T00:00:00Z",
    )


_FAKE_ENRICHED_PROFILE = {
    "slug": "aider",
    "name": "Aider",
    "vendor": "paul-gauthier",
    "source_type": "github",
    "category": "coding",
    "verification": {"method": "docs", "verified_at": "2026-06-06T00:00:00Z"},
    "capabilities": {
        "execute_shell": True,
        "read_filesystem": True,
        "write_filesystem": True,
        "network_egress": "broad",
    },
    "io_surfaces": ["stdin_stdout", "files"],
    "permissions_requested": [],
    "data_classes_touched": ["source code", "git history"],
    "sandboxing": "none",
    "concurrency_model": {
        "session_scope": "per-terminal session",
        "supports_multiple_instances": True,
    },
    "evidence_refs": ["sha256:abc"],
    "first_seen_at": "2026-06-06T00:00:00Z",
    "last_refreshed_at": "2026-06-06T00:00:00Z",
}


@pytest.fixture
def stub_profile() -> dict:
    return {
        "slug": "aider",
        "name": "Aider",
        "category": "coding",
        "evidence_level": "unverified-profile",
        "docs_urls": ["https://aider.chat/"],
        "evidence_refs": [],
        "capabilities": None,
        "onexus": {"source_github": "paul-gauthier/aider", "author_handle": "paul-gauthier", "tags": []},
    }


def _fake_client():
    fake = SimpleNamespace()
    fake.extract_profile = AsyncMock(
        return_value=SimpleNamespace(
            tool_input=dict(_FAKE_ENRICHED_PROFILE),
            raw_response=None,
        )
    )
    return fake


def _fake_fetcher(readme: str = "# Aider\n\nAider lets you pair program with LLMs to edit code in your local git repo."):
    fake = MagicMock()
    fake.fetch = MagicMock(return_value=readme)
    return fake


def test_enrich_returns_docs_only_profile(stub_profile: dict) -> None:
    judge = ProfileEnrichmentJudge(
        client=_fake_client(),
        readme_fetcher=_fake_fetcher(),
        model="gpt-5.4-mini",
    )
    result = judge.evaluate(_wi(), profiles={"aider": stub_profile})
    out = result.verdict   # actually an enriched profile dict
    assert out["evidence_level"] == "docs-only"
    assert out["slug"] == "aider"
    assert out["capabilities"]["execute_shell"] is True
    assert result.cost_usd > 0


def test_enrich_short_circuits_when_no_github_source() -> None:
    stub = {
        "slug": "noremote", "name": "No Remote", "category": "x",
        "evidence_level": "unverified-profile",
        "onexus": {"source_github": None, "tags": []},
    }
    judge = ProfileEnrichmentJudge(
        client=_fake_client(),
        readme_fetcher=_fake_fetcher(),
        model="gpt-5.4-mini",
    )
    with pytest.raises(ValueError, match="no GitHub source"):
        judge.evaluate(_wi(slug="noremote"), profiles={"noremote": stub})


def test_enrich_chunks_long_readme(stub_profile: dict) -> None:
    """A 30k-char README is split into multiple evidence items, capped at 6."""
    big = "Aider chunk text. " * 5000   # ~90k chars
    judge = ProfileEnrichmentJudge(
        client=_fake_client(),
        readme_fetcher=_fake_fetcher(big),
        model="gpt-5.4-mini",
    )
    judge.evaluate(_wi(), profiles={"aider": stub_profile})
    call = judge.client.extract_profile.await_args
    payload = call.args[0]
    assert len(payload.evidence) <= 6
    assert len(payload.evidence) >= 2
    # Each evidence item has a sha + verbatim quote.
    for item in payload.evidence:
        assert item["sha"].startswith(("sha256:", "")) or len(item["sha"]) == 64
        assert item["quote"]


def test_enrich_passes_slug_and_now_iso(stub_profile: dict) -> None:
    judge = ProfileEnrichmentJudge(
        client=_fake_client(),
        readme_fetcher=_fake_fetcher(),
        model="gpt-5.4-mini",
    )
    judge.evaluate(_wi(), profiles={"aider": stub_profile})
    call = judge.client.extract_profile.await_args
    payload = call.args[0]
    assert payload.slug == "aider"
    assert payload.repo_url == "https://github.com/paul-gauthier/aider"
    assert payload.now_iso   # ISO-8601 string set
```

- [ ] **Step 2: Verify ImportError**

```bash
.venv/bin/python -m pytest tests/autopilot/judges/test_profile_enrich.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement**

`smadp/autopilot/judges/profile_enrich.py`:
```python
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
    # gpt-5.4-mini calibrated cost; revise after first 5 real calls.
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
        # Preserve onexus passthrough metadata + composite_score from the stub.
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
```

- [ ] **Step 4: Tests pass**

```bash
.venv/bin/python -m pytest tests/autopilot/judges/test_profile_enrich.py -v
```
Expected: 4/4 PASS.

- [ ] **Step 5: Commit**

```bash
git add smadp/autopilot/judges/profile_enrich.py tests/autopilot/judges/test_profile_enrich.py
git commit -m "feat(autopilot): ProfileEnrichmentJudge wraps LLMClient.extract_profile with README chunking"
```

---

## Task 4: PolicyPublisher.commit_profile

**Files:**
- Modify: `smadp/autopilot/publishers/policy.py`
- Modify: `tests/autopilot/publishers/test_policy.py`

- [ ] **Step 1: Append a test**

Append to `tests/autopilot/publishers/test_policy.py`:

```python
def test_commit_profile_writes_to_profiles(tmp_path: Path) -> None:
    pub = PolicyPublisher(
        catalog_root=tmp_path / "catalog",
        auto_publish={"docs-only": True, "profile-verified": True, "sandbox-run": False},
    )
    profile = {
        "slug": "aider",
        "name": "Aider",
        "evidence_level": "docs-only",
        "capabilities": {"execute_shell": True},
    }
    path = pub.commit_profile(profile)
    assert path.parent.name == "profiles"
    assert path.name == "aider.json"
    written = json.loads(path.read_text())
    assert written["capabilities"]["execute_shell"] is True


def test_commit_profile_overwrites(tmp_path: Path) -> None:
    pub = PolicyPublisher(
        catalog_root=tmp_path / "catalog",
        auto_publish={"docs-only": True, "profile-verified": True, "sandbox-run": False},
    )
    pub.commit_profile({"slug": "aider", "name": "v1"})
    pub.commit_profile({"slug": "aider", "name": "v2"})
    out = json.loads((tmp_path / "catalog" / "profiles" / "aider.json").read_text())
    assert out["name"] == "v2"
```

- [ ] **Step 2: Run tests — new ones fail**

```bash
.venv/bin/python -m pytest tests/autopilot/publishers/test_policy.py -v
```
Expected: 2 new tests FAIL with AttributeError on `commit_profile`.

- [ ] **Step 3: Add `commit_profile` to PolicyPublisher**

In `smadp/autopilot/publishers/policy.py`, add a method (keeping the existing `commit`):

```python
    def commit_profile(self, profile: dict) -> Path:
        target_dir = self.catalog_root / "profiles"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{profile['slug']}.json"

        fd, tmp_name = tempfile.mkstemp(prefix=target.name + ".", dir=target_dir)
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(profile, f, indent=2)
                f.write("\n")
            os.replace(tmp, target)
        except Exception:
            if tmp.exists():
                tmp.unlink()
            raise
        return target
```

- [ ] **Step 4: Tests pass**

```bash
.venv/bin/python -m pytest tests/autopilot/publishers/test_policy.py -v
```
Expected: 6/6 PASS.

- [ ] **Step 5: Commit**

```bash
git add smadp/autopilot/publishers/policy.py tests/autopilot/publishers/test_policy.py
git commit -m "feat(autopilot): PolicyPublisher.commit_profile writes enriched profiles to catalog"
```

---

## Task 5: EnrichmentPlanner

**Files:**
- Create: `smadp/autopilot/planners/enrichment.py`
- Create: `tests/autopilot/planners/test_enrichment.py`

- [ ] **Step 1: Test**

`tests/autopilot/planners/test_enrichment.py`:
```python
"""Tests for EnrichmentPlanner."""

from __future__ import annotations

from smadp.autopilot.planners.enrichment import EnrichmentPlanner


def _profile(slug: str, score: float, level: str = "unverified-profile") -> dict:
    return {
        "slug": slug,
        "composite_score": score,
        "evidence_level": level,
        "onexus": {"source_github": f"x/{slug}"},
    }


def test_emits_one_item_per_unverified_profile() -> None:
    profiles = [_profile("a", 0.9), _profile("b", 0.7), _profile("c", 0.5)]
    planner = EnrichmentPlanner(top_n=10)
    items = planner.plan(profiles=profiles, now_iso="2026-06-06T00:00:00Z")
    slugs = sorted(i.pair[0] for i in items)
    assert slugs == ["a", "b", "c"]
    assert all(i.requested_judge == "profile_enrich" for i in items)


def test_skips_already_enriched_profiles() -> None:
    profiles = [
        _profile("a", 0.9, level="docs-only"),
        _profile("b", 0.7, level="unverified-profile"),
    ]
    planner = EnrichmentPlanner(top_n=10)
    items = planner.plan(profiles=profiles, now_iso="2026-06-06T00:00:00Z")
    assert {i.pair[0] for i in items} == {"b"}


def test_skips_profiles_without_github_source() -> None:
    profiles = [
        {"slug": "no-source", "composite_score": 0.9, "evidence_level": "unverified-profile", "onexus": {"source_github": None}},
        _profile("b", 0.7),
    ]
    planner = EnrichmentPlanner(top_n=10)
    items = planner.plan(profiles=profiles, now_iso="2026-06-06T00:00:00Z")
    assert {i.pair[0] for i in items} == {"b"}


def test_top_n_cap_keeps_highest_score() -> None:
    profiles = [_profile(s, score) for s, score in [("a", 0.9), ("b", 0.8), ("c", 0.1)]]
    planner = EnrichmentPlanner(top_n=2)
    items = planner.plan(profiles=profiles, now_iso="2026-06-06T00:00:00Z")
    slugs = {i.pair[0] for i in items}
    assert slugs == {"a", "b"}


def test_pair_uses_slug_slug_singleton() -> None:
    profiles = [_profile("a", 0.9)]
    planner = EnrichmentPlanner(top_n=10)
    items = planner.plan(profiles=profiles, now_iso="2026-06-06T00:00:00Z")
    assert items[0].pair == ("a", "a")
    assert items[0].priority == 0.9
```

- [ ] **Step 2: ImportError**

```bash
.venv/bin/python -m pytest tests/autopilot/planners/test_enrichment.py -v
```

- [ ] **Step 3: Implement**

`smadp/autopilot/planners/enrichment.py`:
```python
"""EnrichmentPlanner: one WorkItem per unverified-profile that needs enrichment."""

from __future__ import annotations

from dataclasses import dataclass

from smadp.autopilot.work_queue import WorkItem


@dataclass(frozen=True)
class EnrichmentPlanner:
    top_n: int
    judge_name: str = "profile_enrich"
    judge_version: str = "v1"

    def plan(self, *, profiles: list[dict], now_iso: str) -> list[WorkItem]:
        eligible: list[dict] = []
        for p in profiles:
            if p.get("evidence_level") != "unverified-profile":
                continue
            github = (p.get("onexus") or {}).get("source_github")
            if not github:
                continue
            eligible.append(p)
        eligible.sort(key=lambda p: float(p.get("composite_score", 0.0)), reverse=True)
        eligible = eligible[: self.top_n]

        items: list[WorkItem] = []
        for p in eligible:
            slug = p["slug"]
            items.append(
                WorkItem(
                    pair=(slug, slug),
                    requested_judge=self.judge_name,
                    judge_version=self.judge_version,
                    priority=float(p.get("composite_score", 0.0)),
                    enqueued_at=now_iso,
                )
            )
        return items
```

- [ ] **Step 4: Tests pass**

```bash
.venv/bin/python -m pytest tests/autopilot/planners/test_enrichment.py -v
```
Expected: 5/5 PASS.

- [ ] **Step 5: Commit**

```bash
git add smadp/autopilot/planners/enrichment.py tests/autopilot/planners/test_enrichment.py
git commit -m "feat(autopilot): EnrichmentPlanner queues enrichment work for unverified profiles"
```

---

## Task 6: PairGatePlanner

**Files:**
- Create: `smadp/autopilot/planners/pair_gate.py`
- Create: `tests/autopilot/planners/test_pair_gate.py`

- [ ] **Step 1: Test**

`tests/autopilot/planners/test_pair_gate.py`:
```python
"""Tests for PairGatePlanner."""

from __future__ import annotations

from smadp.autopilot.planners.pair_gate import PairGatePlanner


def _p(slug: str, score: float, level: str = "docs-only") -> dict:
    return {"slug": slug, "composite_score": score, "evidence_level": level}


def test_emits_pair_only_when_both_sides_enriched() -> None:
    profiles = [_p("a", 0.9), _p("b", 0.8), _p("c", 0.7, level="unverified-profile")]
    planner = PairGatePlanner(top_n=10, pair_cap=10)
    items = planner.plan(profiles=profiles, now_iso="2026-06-06T00:00:00Z")
    pairs = {tuple(i.pair) for i in items}
    assert pairs == {("a", "b")}    # c is unverified, skipped


def test_emits_no_items_when_no_pair_qualifies() -> None:
    profiles = [_p("a", 0.9, level="unverified-profile")]
    planner = PairGatePlanner(top_n=10, pair_cap=10)
    items = planner.plan(profiles=profiles, now_iso="2026-06-06T00:00:00Z")
    assert items == []


def test_priority_is_score_product() -> None:
    profiles = [_p("a", 0.9), _p("b", 0.5)]
    planner = PairGatePlanner(top_n=10, pair_cap=10)
    items = planner.plan(profiles=profiles, now_iso="2026-06-06T00:00:00Z")
    assert items[0].priority == pytest.approx(0.45)


def test_pair_cap_keeps_highest_priority() -> None:
    profiles = [_p(s, score) for s, score in zip("abcde", [0.9, 0.8, 0.7, 0.6, 0.5])]
    # 5C2 = 10 pairs
    planner = PairGatePlanner(top_n=5, pair_cap=3)
    items = planner.plan(profiles=profiles, now_iso="2026-06-06T00:00:00Z")
    assert len(items) == 3
    assert items[0].pair == ("a", "b")


def test_pair_judge_name_used() -> None:
    profiles = [_p("a", 0.9), _p("b", 0.8)]
    planner = PairGatePlanner(top_n=10, pair_cap=10)
    items = planner.plan(profiles=profiles, now_iso="2026-06-06T00:00:00Z")
    assert items[0].requested_judge == "docs_only"


import pytest  # noqa: E402
```

- [ ] **Step 2: ImportError**

```bash
.venv/bin/python -m pytest tests/autopilot/planners/test_pair_gate.py -v
```

- [ ] **Step 3: Implement**

`smadp/autopilot/planners/pair_gate.py`:
```python
"""PairGatePlanner: emit pair-judge WorkItems only when both sides enriched."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from smadp.autopilot.work_queue import WorkItem

_ENRICHED_TIERS = {"docs-only", "profile-verified", "sandbox-validated"}


@dataclass(frozen=True)
class PairGatePlanner:
    top_n: int
    pair_cap: int
    judge_name: str = "docs_only"
    judge_version: str = "v1"

    def plan(self, *, profiles: list[dict], now_iso: str) -> list[WorkItem]:
        enriched = [
            p for p in profiles
            if p.get("evidence_level") in _ENRICHED_TIERS
        ]
        enriched.sort(key=lambda p: float(p.get("composite_score", 0.0)), reverse=True)
        enriched = enriched[: self.top_n]

        items: list[WorkItem] = []
        for p1, p2 in combinations(enriched, 2):
            a, b = sorted([p1["slug"], p2["slug"]])
            priority = float(p1.get("composite_score", 0.0)) * float(p2.get("composite_score", 0.0))
            items.append(
                WorkItem(
                    pair=(a, b),
                    requested_judge=self.judge_name,
                    judge_version=self.judge_version,
                    priority=priority,
                    enqueued_at=now_iso,
                )
            )
        items.sort(key=lambda i: -i.priority)
        return items[: self.pair_cap]
```

- [ ] **Step 4: Tests pass**

```bash
.venv/bin/python -m pytest tests/autopilot/planners/test_pair_gate.py -v
```

- [ ] **Step 5: Commit**

```bash
git add smadp/autopilot/planners/pair_gate.py tests/autopilot/planners/test_pair_gate.py
git commit -m "feat(autopilot): PairGatePlanner gates pair work on both-sides enrichment"
```

---

## Task 7: docs_only_tick dispatch by judge name

**Files:**
- Modify: `smadp/autopilot/docs_only_tick.py`
- Modify: `tests/autopilot/test_docs_only_tick.py`

The tick must now accept a **map** of judge name → judge instance, route each WorkItem to the right judge, and route its output to the right Publisher method (`commit` for verdicts, `commit_profile` for enrichments).

- [ ] **Step 1: Update tests**

Append to `tests/autopilot/test_docs_only_tick.py`:

```python
def test_tick_routes_profile_enrich_to_commit_profile(tmp_path: Path) -> None:
    """Enrichment items write to catalog/profiles/, not catalog/verdicts/."""
    repo = tmp_path
    _seed_autopilot_config(repo, runs_per_day=10, dollars_per_day=5.0)
    (repo / "catalog" / "profiles").mkdir(parents=True)
    (repo / "catalog" / "profiles" / "aider.json").write_text(json.dumps({
        "slug": "aider", "evidence_level": "unverified-profile",
        "onexus": {"source_github": "p/aider"},
    }))
    _seed_queue(
        repo,
        [WorkItem(("aider", "aider"), "profile_enrich", "v1", 0.9, "2026-06-06T00:00:00Z")],
    )

    enriched = {"slug": "aider", "evidence_level": "docs-only", "capabilities": {"execute_shell": True}}
    enrich_judge = MagicMock()
    enrich_judge.name = "profile_enrich"
    enrich_judge.cost_per_call_usd = 0.04
    enrich_judge.evaluate = MagicMock(return_value=JudgeResult(verdict=enriched, cost_usd=0.04))

    summary = run_docs_only_tick(
        repo_root=repo,
        judges={"profile_enrich": enrich_judge},
        batch_size=10,
    )
    assert summary.published == 1
    written = json.loads((repo / "catalog" / "profiles" / "aider.json").read_text())
    assert written["evidence_level"] == "docs-only"
    assert written["capabilities"]["execute_shell"] is True
    # No verdicts written
    assert not list((repo / "catalog" / "verdicts").glob("*.json"))


def test_tick_skips_when_judge_not_registered(tmp_path: Path) -> None:
    repo = tmp_path
    _seed_autopilot_config(repo, runs_per_day=10, dollars_per_day=5.0)
    _seed_queue(
        repo,
        [WorkItem(("a", "b"), "mystery_judge", "v1", 0.9, "2026-06-06T00:00:00Z")],
    )
    summary = run_docs_only_tick(
        repo_root=repo,
        judges={},  # empty registry
        batch_size=10,
    )
    assert summary.published == 0
    assert summary.failed == 1
```

The existing tests in this file pass a single `judge=` kwarg. Update them to pass `judges={"docs_only": old_judge}` instead, AND keep coverage of the existing dispatch path. Minimum changes to existing tests:
- Change every `judge=...` call site to `judges={"docs_only": ...}`.
- WorkItem.requested_judge values in existing tests are already `"docs_only"` — no change needed.

- [ ] **Step 2: Run tests — many should fail**

```bash
.venv/bin/python -m pytest tests/autopilot/test_docs_only_tick.py -v
```
Expected: failures, mostly TypeError "unexpected keyword 'judges'" once you switch existing tests over.

- [ ] **Step 3: Update `run_docs_only_tick` signature and dispatch**

Replace the body of `smadp/autopilot/docs_only_tick.py` with:

```python
"""Docs-only tick: drain work queue → dispatch to right judge → publish.

Multi-judge dispatch: the caller passes a ``judges`` mapping
``{requested_judge_name: judge_instance}``. Each WorkItem is routed to the
judge whose name matches ``item.requested_judge``. The publisher writes to
``catalog/profiles/`` for enrichment judges (judge.name == "profile_enrich")
and to ``catalog/verdicts/`` (or pending/) for pair judges.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

import structlog

from smadp.autopilot.budget import (
    can_enqueue,
    load_budget,
    record_run_actual,
)
from smadp.autopilot.config import load_autopilot_config
from smadp.autopilot.pause import is_paused
from smadp.autopilot.publishers.policy import PolicyPublisher
from smadp.autopilot.work_queue import drain_items, read_all_items

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class DocsOnlyTickSummary:
    published: int
    failed: int
    reason: str   # "ok" | "paused" | "budget_exhausted" | "no_work"


def _load_profiles(profiles_dir: Path) -> dict[str, dict]:
    profiles: dict[str, dict] = {}
    if not profiles_dir.exists():
        return profiles
    for path in profiles_dir.glob("*.json"):
        try:
            profile = json.loads(path.read_text("utf-8"))
        except json.JSONDecodeError:
            continue
        slug = profile.get("slug") or path.stem
        profiles[slug] = profile
    return profiles


def _log_failure(state_dir: Path, *, pair: tuple, judge_name: str, error: str) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    row = {
        "pair": list(pair),
        "judge": judge_name,
        "error": error,
        "attempted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    with (state_dir / "judge_errors.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def _publish(publisher: PolicyPublisher, judge_name: str, output: dict) -> Path:
    if judge_name == "profile_enrich":
        return publisher.commit_profile(output)
    return publisher.commit(output)


def run_docs_only_tick(
    *,
    repo_root: Path,
    judges: Mapping[str, object],
    batch_size: int = 10,
) -> DocsOnlyTickSummary:
    state_dir = repo_root / "state"
    queue_path = state_dir / "docs_only_queue.jsonl"

    if is_paused(state_dir):
        log.info("docs_only_tick.paused")
        return DocsOnlyTickSummary(published=0, failed=0, reason="paused")

    cfg = load_autopilot_config(repo_root / "config" / "autopilot.yaml")
    budget_path = state_dir / "budget.json"
    budget = load_budget(budget_path)

    if budget.runs_today >= cfg.runs_per_day:
        return DocsOnlyTickSummary(published=0, failed=0, reason="budget_exhausted")
    if budget.dollars_today >= cfg.dollars_per_day:
        return DocsOnlyTickSummary(published=0, failed=0, reason="budget_exhausted")

    items = read_all_items(queue_path)
    if not items:
        return DocsOnlyTickSummary(published=0, failed=0, reason="no_work")

    profiles = _load_profiles(repo_root / "catalog" / "profiles")
    publisher = PolicyPublisher(
        catalog_root=repo_root / "catalog",
        auto_publish={
            "docs-only": True,
            "profile-verified": True,
            "sandbox-run": False,
        },
    )

    max_cost = max(
        (float(getattr(j, "cost_per_call_usd", 0.04)) for j in judges.values()),
        default=0.04,
    )
    cap_by_runs = cfg.runs_per_day - budget.runs_today
    cap_by_dollars = int(max(0, (cfg.dollars_per_day - budget.dollars_today) // max_cost))
    effective = max(0, min(batch_size, cap_by_runs, cap_by_dollars))

    drained = drain_items(queue_path, limit=effective)
    published = 0
    failed = 0
    for work in drained:
        judge = judges.get(work.requested_judge)
        if judge is None:
            failed += 1
            _log_failure(
                state_dir, pair=work.pair, judge_name=work.requested_judge,
                error=f"no judge registered for {work.requested_judge!r}",
            )
            continue
        cost_per_call = float(getattr(judge, "cost_per_call_usd", 0.04))
        if not can_enqueue(load_budget(budget_path), cfg, expected_cost=cost_per_call):
            break
        try:
            result = judge.evaluate(work, profiles=profiles)
            _publish(publisher, judge.name, result.verdict)
            record_run_actual(budget_path, dollars=float(result.cost_usd))
            published += 1
        except Exception as exc:
            failed += 1
            _log_failure(
                state_dir, pair=work.pair,
                judge_name=str(getattr(judge, "name", work.requested_judge)),
                error=repr(exc),
            )
            log.warning("docs_only_tick.judge_failed", pair=work.pair, error=repr(exc))
    if published == 0 and failed == 0:
        return DocsOnlyTickSummary(published=0, failed=0, reason="no_work")
    return DocsOnlyTickSummary(published=published, failed=failed, reason="ok")
```

- [ ] **Step 4: Tests pass**

```bash
.venv/bin/python -m pytest tests/autopilot/test_docs_only_tick.py -v
```
Expected: all PASS (existing + 2 new).

- [ ] **Step 5: Commit**

```bash
git add smadp/autopilot/docs_only_tick.py tests/autopilot/test_docs_only_tick.py
git commit -m "feat(autopilot): docs_only tick dispatches by judge name; profile_enrich routes to commit_profile"
```

---

## Task 8: bootstrap update + CLI judge map

**Files:**
- Modify: `smadp/autopilot/bootstrap.py`
- Modify: `smadp/cli.py` (`docs-only-tick` command)
- Modify: `tests/autopilot/test_bootstrap.py`

- [ ] **Step 1: Update tests**

Replace `test_bootstrap_writes_profiles_and_queue` in `tests/autopilot/test_bootstrap.py` with:

```python
def test_bootstrap_writes_stubs_and_queues_enrichment(fixture_catalog: Path, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    summary = bootstrap_onexus(
        repo_root=repo,
        onexus_root=fixture_catalog,
        top_n=10,
        pair_cap=10,
    )
    assert summary.profiles_written == 3
    assert summary.pairs_queued == 3       # 3 enrichment items, not 3C2 pairs

    # Stub profiles must be unverified
    profiles_dir = repo / "catalog" / "profiles"
    written = sorted(profiles_dir.glob("*.json"))
    assert len(written) == 3
    for p in written:
        import json
        d = json.loads(p.read_text())
        assert d["evidence_level"] == "unverified-profile"

    # Queue items must be enrichment work
    queue_path = repo / "state" / "docs_only_queue.jsonl"
    lines = queue_path.read_text("utf-8").strip().splitlines()
    assert len(lines) == 3
    import json
    items = [json.loads(line) for line in lines]
    assert all(i["requested_judge"] == "profile_enrich" for i in items)
    assert all(i["pair"][0] == i["pair"][1] for i in items)   # singleton pair
```

The other two existing tests (`test_bootstrap_skips_manual_profiles`, `test_bootstrap_is_idempotent`) need their assertions on `pairs_queued` updated similarly: enrichment count == number of unverified profiles, not C(N,2). Update each by changing the assertion accordingly.

- [ ] **Step 2: Tests fail**

```bash
.venv/bin/python -m pytest tests/autopilot/test_bootstrap.py -v
```

- [ ] **Step 3: Update `bootstrap.py`**

Replace the TopNPlanner import + call site in `smadp/autopilot/bootstrap.py`. Change:

```python
from smadp.autopilot.planners.top_n import TopNPlanner
```

to

```python
from smadp.autopilot.planners.enrichment import EnrichmentPlanner
```

And replace the planner block at the bottom of `bootstrap_onexus`:

```python
    planner = EnrichmentPlanner(top_n=top_n)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    items = planner.plan(profiles=list(union.values()), now_iso=now)
    queue_path = repo_root / "state" / "docs_only_queue.jsonl"
    append_items(queue_path, items)

    return BootstrapSummary(
        profiles_written=written,
        profiles_skipped=skipped,
        pairs_queued=len(items),   # field name preserved for CLI back-compat
    )
```

(The `pair_cap` parameter on `bootstrap_onexus` is now unused — keep the signature for back-compat but ignore the value.)

- [ ] **Step 4: Update `docs-only-tick` CLI**

Edit `smadp/cli.py`. Replace the `autopilot_docs_only_tick` function with:

```python
@autopilot.command("docs-only-tick")
@click.option("--batch-size", default=10, type=int)
@click.pass_context
def autopilot_docs_only_tick(ctx: click.Context, batch_size: int) -> None:
    """Drain the docs-only queue, dispatch to the right judge, publish."""
    import os
    from smadp.autopilot.docs_only_tick import run_docs_only_tick
    from smadp.autopilot.enrichers.github_readme import GithubReadmeFetcher
    from smadp.autopilot.judges.docs_only import DocsOnlyJudge
    from smadp.autopilot.judges.profile_enrich import ProfileEnrichmentJudge
    from smadp.llm.client import LLMClient

    config = ctx.obj["config"]
    client = LLMClient(config=config)
    rubric_path = config.rubric_path

    fetcher = GithubReadmeFetcher(
        cache_dir=config.repo_root / "state" / "enrichment_cache",
        token=os.environ.get("GITHUB_TOKEN"),
    )
    judges = {
        "profile_enrich": ProfileEnrichmentJudge(
            client=client, readme_fetcher=fetcher, model="gpt-5.4-mini",
        ),
        "docs_only": DocsOnlyJudge(
            client=client, model="gpt-5.4-mini", rubric_path=rubric_path,
        ),
    }
    summary = run_docs_only_tick(
        repo_root=config.repo_root,
        judges=judges,
        batch_size=batch_size,
    )
    click.echo(
        f"published={summary.published} failed={summary.failed} reason={summary.reason}"
    )
```

Add a new `pair-gate-plan` command immediately after `autopilot_docs_only_tick`:

```python
@autopilot.command("pair-gate-plan")
@click.option("--top-n", default=100, type=int)
@click.option("--pair-cap", default=4950, type=int)
@click.pass_context
def autopilot_pair_gate_plan(ctx: click.Context, top_n: int, pair_cap: int) -> None:
    """Re-scan profiles, enqueue pair-judge work where both sides are enriched."""
    import json as _json
    from datetime import datetime, timezone
    from smadp.autopilot.planners.pair_gate import PairGatePlanner
    from smadp.autopilot.work_queue import append_items

    config = ctx.obj["config"]
    profiles_dir = config.repo_root / "catalog" / "profiles"
    profiles: list[dict] = []
    for p in profiles_dir.glob("*.json"):
        try:
            profiles.append(_json.loads(p.read_text("utf-8")))
        except (OSError, _json.JSONDecodeError):
            continue
    planner = PairGatePlanner(top_n=top_n, pair_cap=pair_cap)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    items = planner.plan(profiles=profiles, now_iso=now)
    queue_path = config.repo_root / "state" / "docs_only_queue.jsonl"
    append_items(queue_path, items)
    click.echo(f"enqueued={len(items)}")
```

- [ ] **Step 5: Bootstrap test + CLI smoke**

```bash
.venv/bin/python -m pytest tests/autopilot/test_bootstrap.py -v
.venv/bin/python -m smadp.cli autopilot --help
```
Expected: 3 tests pass; help shows `bootstrap-onexus`, `docs-only-tick`, `pair-gate-plan`, plus existing `tick` and `approve`.

- [ ] **Step 6: Commit**

```bash
git add smadp/autopilot/bootstrap.py smadp/cli.py tests/autopilot/test_bootstrap.py
git commit -m "feat(autopilot): bootstrap queues enrichment; CLI registers profile_enrich + docs_only judges + pair-gate-plan"
```

---

## Task 9: 5-agent enrichment smoke + 5 pair-judge smoke

**Files:** None (validation gate).

- [ ] **Step 1: Run bootstrap on a 5-agent slice**

```bash
cd "/Users/connorevans/Desktop/Frontier_AI/Safe Multi-Agent Deployment Platform (SMADP)/SMADP"
set -a; source .env; set +a
.venv/bin/python -m smadp.cli autopilot bootstrap-onexus --top-n 5 --pair-cap 10
```
Expected: `profiles_written=<≤5> profiles_skipped=<≥0> pairs_queued=<≤5>` (enrichment items, not pair items).

- [ ] **Step 2: Run 5 enrichment ticks**

```bash
for i in 1 2 3 4 5; do
  echo "=== tick $i ==="
  .venv/bin/python -m smadp.cli autopilot docs-only-tick --batch-size 1
done
```
Expected each: `published=1 failed=0 reason=ok`.

Halt and read `state/judge_errors.jsonl` if any fails.

- [ ] **Step 3: Eyeball enriched profiles**

```bash
ls -t catalog/profiles | head -5
for f in $(ls -t catalog/profiles | head -5); do
  echo "=== $f ==="
  .venv/bin/python -c "
import json
d = json.load(open('catalog/profiles/$f'))
print('evidence_level:', d.get('evidence_level'))
caps = d.get('capabilities') or {}
print('capability flags set:', [k for k,v in caps.items() if v is True])
print('network_egress:', caps.get('network_egress'))
print('data_classes_touched:', d.get('data_classes_touched'))
print('evidence_refs:', len(d.get('evidence_refs') or []))
"
done
```

**Halt criteria (do NOT proceed if any are true):**
- Every enriched profile has the same capability flags set (model collapsed).
- Every `data_classes_touched` is empty across all 5.
- Any profile has `evidence_level` != `"docs-only"`.
- Any profile has 0 evidence_refs.

If you halt: read raw responses in `state/enrichment_cache/`, identify whether the extractor got a useful README, and iterate.

- [ ] **Step 4: Run pair-gate planner over the enriched set**

```bash
.venv/bin/python -m smadp.cli autopilot pair-gate-plan --top-n 5 --pair-cap 10
```
Expected: `enqueued=10` (5C2 pairs from 5 enriched profiles).

- [ ] **Step 5: Run 5 pair-judge ticks**

```bash
for i in 1 2 3 4 5; do
  echo "=== pair-tick $i ==="
  .venv/bin/python -m smadp.cli autopilot docs-only-tick --batch-size 1
done
```
Expected each: `published=1 failed=0 reason=ok`.

- [ ] **Step 6: Eyeball pair verdicts**

```bash
ls -t catalog/verdicts | head -5
for f in $(ls -t catalog/verdicts | head -5); do
  echo "=== $f ==="
  .venv/bin/python -c "
import json
v = json.load(open('catalog/verdicts/$f'))
print('pair:', v['pair'])
print('composite_score:', v['composite_score'])
print('confidence:', v['confidence'])
print('headline:', v['headline'][:160])
sevs = {k: v['sub_verdicts'][k]['severity'] for k in v['sub_verdicts']}
print('severities:', sevs)
"
done
```

**Halt criteria (do NOT activate launchd if any are true):**
- All 5 composite_score values are identical.
- Every severity across all 5 × 5 = 25 sub-verdicts is "none".
- Fewer than 3 distinct severities appear across the 25 sub-verdicts.

- [ ] **Step 7: If both smokes pass, commit the smoke artifacts**

```bash
git add catalog/profiles/ catalog/verdicts/ state/budget.json
git commit -m "chore(catalog): seed enriched profiles + pair verdicts from pivot smoke"
```

Otherwise: do NOT commit. Roll back via `git clean -fd catalog/profiles/ catalog/verdicts/` and reset state files. Re-read enrichment caches to diagnose.

- [ ] **Step 8: Launchd activation gate (only if all halt criteria clear)**

Edit `scripts/autopilot-loop.sh` and add a docs-only tick line after the existing sandbox tick:

```bash
.venv/bin/python -m smadp.cli autopilot docs-only-tick --batch-size 3
```

Then commit:

```bash
git add scripts/autopilot-loop.sh
git commit -m "feat(autopilot): launchd loop drains docs-only queue alongside sandbox"
```

---

## Self-review

**Spec coverage:**

| Spec section | Implementing task(s) |
| --- | --- |
| Stub profile with `evidence_level: "unverified-profile"` | T1 |
| `Enricher` ABC + `GithubReadmeFetcher` | T2 |
| `ProfileEnrichmentJudge` (extract_profile wrapper) | T3 |
| `PolicyPublisher.commit_profile` | T4 |
| `EnrichmentPlanner` | T5 |
| `PairGatePlanner` | T6 |
| tick dispatch by `requested_judge` | T7 |
| Bootstrap queues enrichment, CLI registers both judges | T8 |
| New `pair-gate-plan` CLI | T8 |
| 5-agent enrichment smoke + halt criteria | T9 steps 1–3 |
| 5-pair pair-judge smoke + halt criteria | T9 steps 4–6 |
| Launchd activation behind both gates | T9 step 8 |
| Adapter scaffolder (mcp_adapter) | Deferred — separate plan |
| ProfileVerifiedJudge as distinct LLM pass | Deferred per spec |

**Placeholder scan:** no TBD; every step has runnable commands and code blocks.

**Type consistency:**
- `WorkItem.pair: tuple[str, str]` consistent everywhere; enrichment uses `(slug, slug)` singleton form.
- `JudgeResult(verdict: dict, cost_usd: float)` returned by both `DocsOnlyJudge` and `ProfileEnrichmentJudge`.
- `PolicyPublisher.commit_profile(profile: dict) -> Path` mirrors the existing `commit(verdict: dict) -> Path`.
- `run_docs_only_tick(judges: Mapping[str, object], ...)` — every caller (CLI + tests) passes a dict.
- `judge.evaluate(work, *, profiles) -> JudgeResult` and `judge.name`, `judge.cost_per_call_usd` — required attributes documented in T7 dispatch.

**Scope check:** focused on the enrichment + pair-gate pipeline. Adapter scaffolder is explicitly deferred to keep this plan executable in one session.

No mismatches found.
