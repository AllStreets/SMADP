# ONEXUS Autonomous Loop — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up an autonomous pipeline that ingests ONEXUS-Agents into SMADP profiles, generates Docs-only pair verdicts for the top-100 by composite score via `gpt-5.4-mini`, and publishes them directly to `catalog/verdicts/` — all running unattended under the existing launchd autopilot loop.

**Architecture:** Five-stage pipeline (Source → Profiler → Planner → Judge → Publisher) added as a parallel docs-only path alongside the existing sandbox tick. Existing `tick.py` and sandbox runner are untouched tonight. The docs-only tick reuses `BudgetState`, `is_paused`, `load_priority`, and the existing `LLMClient.judge_pair` LLM wrapper. Sandbox judge wrapper is created for registry uniformity but adds no behavior.

**Tech Stack:** Python 3.11+, OpenAI Python SDK 1.x (already in deps), `tenacity` for retries (already in use), `structlog` for logs, `click` for CLI. JSON on disk for queue, profiles, verdicts. Pytest with `autopilot_repo` fixture pattern.

---

## File Structure

### New files

| Path | Responsibility |
| --- | --- |
| `smadp/autopilot/work_queue.py` | `WorkItem` dataclass + JSONL queue (append, drain, dedupe) |
| `smadp/autopilot/sources/__init__.py` | Source package init |
| `smadp/autopilot/sources/onexus.py` | `OnexusSource.fetch()` → iterator of `RawOnexusAgent` |
| `smadp/autopilot/profilers/__init__.py` | Profiler package init |
| `smadp/autopilot/profilers/onexus.py` | `OnexusProfiler.normalize()` → SMADP profile dict |
| `smadp/autopilot/planners/__init__.py` | Planner package init |
| `smadp/autopilot/planners/top_n.py` | `TopNPlanner.plan()` → list of `WorkItem` |
| `smadp/autopilot/judges/__init__.py` | Judge package init |
| `smadp/autopilot/judges/docs_only.py` | `DocsOnlyJudge.evaluate()` — wraps `LLMClient.judge_pair`, marks `evidence_level="docs-only"` |
| `smadp/autopilot/publishers/__init__.py` | Publisher package init |
| `smadp/autopilot/publishers/policy.py` | `PolicyPublisher.commit()` — docs-only → `catalog/verdicts/`; sandbox → `catalog/pending/` (delegates to existing flow) |
| `smadp/autopilot/docs_only_tick.py` | `run_docs_only_tick()` — drain queue → judge → publish → update budget |
| `smadp/autopilot/bootstrap.py` | `bootstrap_onexus()` — import + plan in one shot |
| `tests/autopilot/test_work_queue.py` | |
| `tests/autopilot/sources/__init__.py` | |
| `tests/autopilot/sources/test_onexus.py` | |
| `tests/autopilot/profilers/__init__.py` | |
| `tests/autopilot/profilers/test_onexus.py` | |
| `tests/autopilot/planners/__init__.py` | |
| `tests/autopilot/planners/test_top_n.py` | |
| `tests/autopilot/judges/__init__.py` | |
| `tests/autopilot/judges/test_docs_only.py` | |
| `tests/autopilot/publishers/__init__.py` | |
| `tests/autopilot/publishers/test_policy.py` | |
| `tests/autopilot/test_docs_only_tick.py` | |
| `tests/autopilot/test_bootstrap.py` | |
| `tests/fixtures/onexus/coding/fixture-agent-a.json` | Fixture for source/profiler tests |
| `tests/fixtures/onexus/coding/fixture-agent-b.json` | Fixture for source/profiler tests |

### Modified files

| Path | Change |
| --- | --- |
| `smadp/cli.py` | Add `autopilot bootstrap-onexus` and `autopilot docs-only-tick` subcommands |
| `config/autopilot.yaml` | Add `judges:`, `sources:`, `publishers:` sections |
| `smadp/autopilot/config.py` | Parse new config keys with backwards-compat defaults |
| `tests/autopilot/conftest.py` (or create if missing) | Ensure `autopilot_repo` fixture exists for the new tests (likely already present) |

### Files explicitly NOT touched tonight

- `smadp/autopilot/tick.py` — existing sandbox flow stays as-is
- `smadp/sandbox/**` — unchanged
- `adapters/**` — unchanged
- `site/**` — verdicts render through existing `verdicts/[id].astro`

---

## Self-contained constants

These appear in multiple tasks. Define here once.

- **ONEXUS catalog root:** `~/Downloads/ONEXUS-Agents/catalog` (per memory `reference-onexus-catalog`).
- **LLM model:** `gpt-5.4-mini` (per user confirmation).
- **Verdict schema_version:** `"1.0"` (matches existing verdicts).
- **Docs-only evidence level string:** `"docs-only"` (matches existing values seen in `catalog/verdicts/aider__claude-code.json`).
- **Risk dimension keys:** `A_prompt_injection`, `B_data_leakage`, `C_capability_conflict`, `D_cascading_error`, `E_compliance` (from existing verdict shape).
- **Docs-only budget cap default:** `dollars_per_day: 20.0` soft, `dollars_per_day_hard: 30.0` hard.
- **Top-N default:** `100`.
- **Pair cap default:** `4950` (from `100C2`; covered by score-product priority).

---

## Task 1: WorkItem + JSONL work queue

**Files:**
- Create: `smadp/autopilot/work_queue.py`
- Create: `tests/autopilot/test_work_queue.py`

- [ ] **Step 1: Write the failing test**

`tests/autopilot/test_work_queue.py`:
```python
"""Tests for WorkItem dataclass and JSONL queue helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from smadp.autopilot.work_queue import (
    WorkItem,
    append_items,
    drain_items,
    read_all_items,
)


def _mk(pair: tuple[str, str], judge: str = "docs_only", priority: float = 0.5) -> WorkItem:
    return WorkItem(
        pair=pair,
        requested_judge=judge,
        judge_version="v1",
        priority=priority,
        enqueued_at="2026-06-06T00:00:00Z",
    )


def test_append_then_read_round_trip(tmp_path: Path) -> None:
    queue = tmp_path / "queue.jsonl"
    append_items(queue, [_mk(("aider", "cursor"))])
    items = read_all_items(queue)
    assert len(items) == 1
    assert items[0].pair == ("aider", "cursor")
    assert items[0].requested_judge == "docs_only"
    assert items[0].judge_version == "v1"


def test_append_dedupes_by_pair_and_judge(tmp_path: Path) -> None:
    queue = tmp_path / "queue.jsonl"
    append_items(queue, [_mk(("aider", "cursor"))])
    append_items(queue, [_mk(("aider", "cursor"))])  # dupe
    append_items(queue, [_mk(("aider", "cursor"), judge="sandbox")])  # different judge OK
    items = read_all_items(queue)
    pairs_and_judges = [(i.pair, i.requested_judge) for i in items]
    assert pairs_and_judges == [
        (("aider", "cursor"), "docs_only"),
        (("aider", "cursor"), "sandbox"),
    ]


def test_drain_removes_drained_items(tmp_path: Path) -> None:
    queue = tmp_path / "queue.jsonl"
    append_items(
        queue,
        [
            _mk(("a", "b"), priority=0.9),
            _mk(("c", "d"), priority=0.5),
            _mk(("e", "f"), priority=0.1),
        ],
    )
    drained = drain_items(queue, limit=2)
    assert [i.pair for i in drained] == [("a", "b"), ("c", "d")]  # priority order
    remaining = read_all_items(queue)
    assert [i.pair for i in remaining] == [("e", "f")]


def test_drain_on_empty_queue_returns_empty(tmp_path: Path) -> None:
    queue = tmp_path / "queue.jsonl"
    drained = drain_items(queue, limit=5)
    assert drained == []


def test_pair_is_always_sorted(tmp_path: Path) -> None:
    queue = tmp_path / "queue.jsonl"
    append_items(queue, [_mk(("zebra", "aider"))])
    items = read_all_items(queue)
    assert items[0].pair == ("aider", "zebra")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd "/Users/connorevans/Desktop/Frontier_AI/Safe Multi-Agent Deployment Platform (SMADP)/SMADP"
pytest tests/autopilot/test_work_queue.py -v
```
Expected: ImportError on `smadp.autopilot.work_queue`.

- [ ] **Step 3: Write minimal implementation**

`smadp/autopilot/work_queue.py`:
```python
"""WorkItem dataclass + JSONL work queue used by the docs-only autopilot path.

Queue file format: one JSON object per line, sorted-pair canonical form.

Idempotency: appending a (pair, requested_judge, judge_version) tuple that
already exists in the file is a no-op. This makes bootstrap re-runnable.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class WorkItem:
    pair: tuple[str, str]
    requested_judge: str
    judge_version: str
    priority: float
    enqueued_at: str

    def to_jsonable(self) -> dict:
        return {
            "pair": list(self.pair),
            "requested_judge": self.requested_judge,
            "judge_version": self.judge_version,
            "priority": self.priority,
            "enqueued_at": self.enqueued_at,
        }

    @classmethod
    def from_jsonable(cls, raw: dict) -> "WorkItem":
        pair = tuple(sorted(raw["pair"]))
        return cls(
            pair=(pair[0], pair[1]),
            requested_judge=raw["requested_judge"],
            judge_version=raw["judge_version"],
            priority=float(raw["priority"]),
            enqueued_at=raw["enqueued_at"],
        )


def _canonical(item: WorkItem) -> WorkItem:
    pair = tuple(sorted(item.pair))
    return WorkItem(
        pair=(pair[0], pair[1]),
        requested_judge=item.requested_judge,
        judge_version=item.judge_version,
        priority=item.priority,
        enqueued_at=item.enqueued_at,
    )


def read_all_items(path: Path) -> list[WorkItem]:
    if not path.exists():
        return []
    items: list[WorkItem] = []
    for line in path.read_text("utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        items.append(WorkItem.from_jsonable(json.loads(line)))
    return items


def _atomic_write_text(path: Path, content: str) -> None:
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


def append_items(path: Path, items: list[WorkItem]) -> None:
    existing = read_all_items(path)
    seen = {(i.pair, i.requested_judge, i.judge_version) for i in existing}
    additions = []
    for raw in items:
        canon = _canonical(raw)
        key = (canon.pair, canon.requested_judge, canon.judge_version)
        if key in seen:
            continue
        seen.add(key)
        additions.append(canon)
    if not additions:
        return
    lines = [json.dumps(i.to_jsonable()) for i in (existing + additions)]
    _atomic_write_text(path, "\n".join(lines) + "\n")


def drain_items(path: Path, *, limit: int) -> list[WorkItem]:
    items = read_all_items(path)
    if not items:
        return []
    items_sorted = sorted(items, key=lambda i: -i.priority)
    drained = items_sorted[:limit]
    remaining = items_sorted[limit:]
    if remaining:
        lines = [json.dumps(i.to_jsonable()) for i in remaining]
        _atomic_write_text(path, "\n".join(lines) + "\n")
    else:
        if path.exists():
            path.unlink()
    return drained
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/autopilot/test_work_queue.py -v
```
Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add smadp/autopilot/work_queue.py tests/autopilot/test_work_queue.py
git commit -m "feat(autopilot): WorkItem + JSONL work queue with dedupe + priority drain"
```

---

## Task 2: OnexusSource — read raw agents from ONEXUS catalog

**Files:**
- Create: `smadp/autopilot/sources/__init__.py` (empty)
- Create: `smadp/autopilot/sources/onexus.py`
- Create: `tests/autopilot/sources/__init__.py` (empty)
- Create: `tests/autopilot/sources/test_onexus.py`
- Create: `tests/fixtures/onexus/coding/fixture-agent-a.json`
- Create: `tests/fixtures/onexus/coding/fixture-agent-b.json`

- [ ] **Step 1: Create fixtures**

`tests/fixtures/onexus/coding/fixture-agent-a.json`:
```json
{
  "slug": "fixture-agent-a",
  "name": "Fixture Agent A",
  "tagline": "An agent for tests.",
  "category": "coding",
  "tags": ["ai-agents", "github", "cli"],
  "author": {"type": "user", "handle": "octocat", "url": "https://github.com/octocat"},
  "source": {"primary": "github", "github": "octocat/fixture-a", "homepage": null},
  "license": "MIT",
  "metrics": {"stars": 1000, "downloads_30d": null, "last_commit_at": "2026-04-01T00:00:00Z"},
  "runnable": false,
  "adapter_ref": null,
  "composite_score": 0.91,
  "rank_in_category": 1
}
```

`tests/fixtures/onexus/coding/fixture-agent-b.json`:
```json
{
  "slug": "fixture-agent-b",
  "name": "Fixture Agent B",
  "tagline": "Another agent for tests.",
  "category": "coding",
  "tags": ["ai-agents", "filesystem"],
  "author": {"type": "user", "handle": "octocat", "url": "https://github.com/octocat"},
  "source": {"primary": "github", "github": "octocat/fixture-b", "homepage": null},
  "license": "Apache-2.0",
  "metrics": {"stars": 500, "downloads_30d": null, "last_commit_at": "2026-04-01T00:00:00Z"},
  "runnable": false,
  "adapter_ref": null,
  "composite_score": 0.75,
  "rank_in_category": 2
}
```

- [ ] **Step 2: Write the failing test**

`tests/autopilot/sources/test_onexus.py`:
```python
"""Tests for OnexusSource."""

from __future__ import annotations

from pathlib import Path

import pytest

from smadp.autopilot.sources.onexus import OnexusSource, RawOnexusAgent

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "onexus"


def test_fetch_yields_all_records_from_fixture() -> None:
    source = OnexusSource(root=FIXTURE_ROOT)
    records = list(source.fetch())
    slugs = sorted(r.slug for r in records)
    assert slugs == ["fixture-agent-a", "fixture-agent-b"]


def test_fetch_yields_typed_records() -> None:
    source = OnexusSource(root=FIXTURE_ROOT)
    by_slug = {r.slug: r for r in source.fetch()}
    a = by_slug["fixture-agent-a"]
    assert isinstance(a, RawOnexusAgent)
    assert a.category == "coding"
    assert a.tags == ["ai-agents", "github", "cli"]
    assert a.composite_score == 0.91
    assert a.source_github == "octocat/fixture-a"


def test_fetch_skips_invalid_json(tmp_path: Path) -> None:
    cat = tmp_path / "broken"
    cat.mkdir()
    (cat / "bad.json").write_text("this is not json")
    (cat / "good.json").write_text(
        '{"slug":"good","name":"G","category":"broken","tags":[],'
        '"author":{"type":"user","handle":"x","url":""},'
        '"source":{"primary":"github","github":"x/g","homepage":null},'
        '"license":"MIT","metrics":{"stars":0,"downloads_30d":null,"last_commit_at":""},'
        '"runnable":false,"adapter_ref":null,"composite_score":0.1,"rank_in_category":1}'
    )
    source = OnexusSource(root=tmp_path)
    slugs = [r.slug for r in source.fetch()]
    assert slugs == ["good"]


def test_fetch_returns_empty_when_root_missing(tmp_path: Path) -> None:
    source = OnexusSource(root=tmp_path / "nope")
    assert list(source.fetch()) == []
```

- [ ] **Step 3: Run test to verify it fails**

```bash
pytest tests/autopilot/sources/test_onexus.py -v
```
Expected: ImportError on `smadp.autopilot.sources.onexus`.

- [ ] **Step 4: Write minimal implementation**

`smadp/autopilot/sources/__init__.py`: (empty file)

`smadp/autopilot/sources/onexus.py`:
```python
"""OnexusSource: yield raw agent records from the ONEXUS-Agents catalog.

Catalog layout: ``<root>/<category>/<slug>.json`` — flat per-category dirs of
agent JSON. Parse failures are logged and skipped, not raised, so a single
malformed file cannot abort an entire bootstrap run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import structlog

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class RawOnexusAgent:
    slug: str
    name: str
    category: str
    tags: list[str]
    author_handle: str
    source_github: str | None
    source_homepage: str | None
    license: str | None
    composite_score: float
    runnable: bool


class OnexusSource:
    name = "onexus"

    def __init__(self, *, root: Path) -> None:
        self.root = root

    def fetch(self) -> Iterator[RawOnexusAgent]:
        if not self.root.exists():
            return
        for category_dir in sorted(self.root.iterdir()):
            if not category_dir.is_dir():
                continue
            if category_dir.name.startswith("_"):
                # ONEXUS uses underscore-prefixed dirs for metadata only.
                continue
            for json_path in sorted(category_dir.glob("*.json")):
                try:
                    raw = json.loads(json_path.read_text("utf-8"))
                    yield self._normalize(raw)
                except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                    log.warning(
                        "onexus.source.parse_skip",
                        path=str(json_path),
                        error=repr(exc),
                    )
                    continue

    @staticmethod
    def _normalize(raw: dict) -> RawOnexusAgent:
        source = raw.get("source") or {}
        author = raw.get("author") or {}
        return RawOnexusAgent(
            slug=str(raw["slug"]),
            name=str(raw.get("name", raw["slug"])),
            category=str(raw.get("category", "uncategorized")),
            tags=list(raw.get("tags") or []),
            author_handle=str(author.get("handle", "")),
            source_github=source.get("github"),
            source_homepage=source.get("homepage"),
            license=raw.get("license"),
            composite_score=float(raw.get("composite_score", 0.0)),
            runnable=bool(raw.get("runnable", False)),
        )
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/autopilot/sources/test_onexus.py -v
```
Expected: all 4 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add smadp/autopilot/sources tests/autopilot/sources tests/fixtures/onexus
git commit -m "feat(autopilot): OnexusSource yields RawOnexusAgent from catalog dir"
```

---

## Task 3: OnexusProfiler — RawOnexusAgent → SMADP profile JSON

**Files:**
- Create: `smadp/autopilot/profilers/__init__.py` (empty)
- Create: `smadp/autopilot/profilers/onexus.py`
- Create: `tests/autopilot/profilers/__init__.py` (empty)
- Create: `tests/autopilot/profilers/test_onexus.py`

- [ ] **Step 1: Write the failing test**

`tests/autopilot/profilers/test_onexus.py`:
```python
"""Tests for OnexusProfiler."""

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


def test_normalize_produces_required_keys() -> None:
    profile = OnexusProfiler().normalize(_raw())
    assert profile["slug"] == "aider"
    assert profile["name"] == "Aider"
    assert profile["category"] == "coding"
    assert profile["evidence_level"] == "docs-only"
    assert profile["composite_score"] == 0.87
    assert profile["onexus"]["source_github"] == "paul-gauthier/aider"


def test_normalize_infers_capabilities_from_tags() -> None:
    profile = OnexusProfiler().normalize(_raw(tags=["shell", "filesystem", "network"]))
    caps = profile["capabilities"]
    assert caps["execute_shell"] is True
    assert caps["read_filesystem"] is True
    assert caps["write_filesystem"] is True
    assert caps["network_egress"] in ("broad", "narrow", "none")


def test_normalize_capabilities_default_to_unknown_when_no_signal() -> None:
    profile = OnexusProfiler().normalize(_raw(tags=["mystery-tag"]))
    caps = profile["capabilities"]
    # absent signals -> conservative defaults (False, "none")
    assert caps["execute_shell"] is False
    assert caps["network_egress"] == "none"


def test_normalize_includes_docs_evidence_ref() -> None:
    profile = OnexusProfiler().normalize(_raw())
    refs = profile["evidence_refs"]
    assert len(refs) >= 1
    # evidence refs are sha256-prefixed strings
    assert all(r.startswith("sha256:") for r in refs)


def test_normalize_preserves_docs_urls() -> None:
    profile = OnexusProfiler().normalize(_raw())
    assert "https://aider.chat/" in profile["docs_urls"]
    assert any("github.com/paul-gauthier/aider" in u for u in profile["docs_urls"])
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/autopilot/profilers/test_onexus.py -v
```
Expected: ImportError on `smadp.autopilot.profilers.onexus`.

- [ ] **Step 3: Write minimal implementation**

`smadp/autopilot/profilers/__init__.py`: (empty file)

`smadp/autopilot/profilers/onexus.py`:
```python
"""OnexusProfiler: turn a RawOnexusAgent into an SMADP profile dict.

Capability inference is a deliberately conservative tag-based heuristic.
Anything we can't infer defaults to "unknown" (False / "none"). Operators can
override by editing the profile JSON and adding ``"manual": true`` so future
bootstrap runs skip the file (see ``bootstrap.py`` for the policy).
"""

from __future__ import annotations

import hashlib
from typing import Any

from smadp.autopilot.sources.onexus import RawOnexusAgent

_SHELL_TAGS = {"shell", "cli", "terminal", "bash", "zsh"}
_FS_READ_TAGS = {"filesystem", "files", "file-system", "fs", "code-search"}
_FS_WRITE_TAGS = {"filesystem", "files", "file-system", "fs", "code-edit", "code-editor"}
_NETWORK_BROAD = {"web-browsing", "browser", "web", "internet", "scraping"}
_NETWORK_NARROW = {"api", "rest", "http"}
_MCP_TAGS = {"mcp", "model-context-protocol"}


def _sha(s: str) -> str:
    return "sha256:" + hashlib.sha256(s.encode("utf-8")).hexdigest()


class OnexusProfiler:
    name = "onexus"
    accepts_source = "onexus"

    def normalize(self, raw: RawOnexusAgent) -> dict[str, Any]:
        tags_lc = {t.lower() for t in raw.tags}
        docs_urls: list[str] = []
        if raw.source_homepage:
            docs_urls.append(raw.source_homepage)
        if raw.source_github:
            docs_urls.append(f"https://github.com/{raw.source_github}")
        evidence_refs = [_sha(f"onexus:{raw.slug}:{u}") for u in docs_urls]

        capabilities = {
            "execute_shell": bool(tags_lc & _SHELL_TAGS),
            "install_packages": False,
            "modify_git_state": False,
            "network_egress": (
                "broad"
                if tags_lc & _NETWORK_BROAD
                else "narrow"
                if tags_lc & _NETWORK_NARROW
                else "none"
            ),
            "read_filesystem": bool(tags_lc & _FS_READ_TAGS),
            "run_browsers": bool({"browser", "web-browsing"} & tags_lc),
            "spawn_subprocesses": bool(tags_lc & _SHELL_TAGS),
            "use_mcp": bool(tags_lc & _MCP_TAGS),
            "write_filesystem": bool(tags_lc & _FS_WRITE_TAGS),
        }
        return {
            "slug": raw.slug,
            "name": raw.name,
            "category": raw.category,
            "evidence_level": "docs-only",
            "docs_urls": docs_urls,
            "evidence_refs": evidence_refs,
            "capabilities": capabilities,
            "data_classes_touched": [],
            "concurrency_model": {
                "session_scope": "unknown",
                "shared_state_with_other_instances": "unknown",
                "supports_multiple_instances": False,
            },
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

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/autopilot/profilers/test_onexus.py -v
```
Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add smadp/autopilot/profilers tests/autopilot/profilers
git commit -m "feat(autopilot): OnexusProfiler normalizes RawOnexusAgent into SMADP profile"
```

---

## Task 4: DocsOnlyJudge — wrap LLMClient.judge_pair, mark docs-only

**Files:**
- Create: `smadp/autopilot/judges/__init__.py` (empty)
- Create: `smadp/autopilot/judges/docs_only.py`
- Create: `tests/autopilot/judges/__init__.py` (empty)
- Create: `tests/autopilot/judges/test_docs_only.py`

- [ ] **Step 1: Write the failing test**

`tests/autopilot/judges/test_docs_only.py`:
```python
"""Tests for DocsOnlyJudge."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from smadp.autopilot.judges.docs_only import DocsOnlyJudge, JudgeResult
from smadp.autopilot.work_queue import WorkItem


def _wi() -> WorkItem:
    return WorkItem(
        pair=("aider", "cursor"),
        requested_judge="docs_only",
        judge_version="v1",
        priority=0.9,
        enqueued_at="2026-06-06T00:00:00Z",
    )


@pytest.fixture
def fake_judge_pair_response() -> dict:
    return {
        "headline": "Both auto-edit; modest capability conflict.",
        "composite_score": 0.45,
        "confidence": 0.7,
        "sub_verdicts": {
            "A_prompt_injection": {"severity": "low", "rationale": "r", "citations": [], "conditions": [], "mitigations": []},
            "B_data_leakage": {"severity": "low", "rationale": "r", "citations": [], "conditions": [], "mitigations": []},
            "C_capability_conflict": {"severity": "medium", "rationale": "r", "citations": [], "conditions": [], "mitigations": []},
            "D_cascading_error": {"severity": "low", "rationale": "r", "citations": [], "conditions": [], "mitigations": []},
            "E_compliance": {"severity": "low", "rationale": "r", "citations": [], "conditions": [], "mitigations": []},
        },
        "framework_mappings": {},
    }


def test_judge_returns_docs_only_verdict(fake_judge_pair_response, tmp_path: Path) -> None:
    profiles = {
        "aider": {"slug": "aider", "name": "Aider", "capabilities": {}, "evidence_level": "docs-only", "docs_urls": []},
        "cursor": {"slug": "cursor", "name": "Cursor", "capabilities": {}, "evidence_level": "docs-only", "docs_urls": []},
    }
    fake_client = MagicMock()
    fake_client.judge_pair = AsyncMock(return_value=fake_judge_pair_response)

    judge = DocsOnlyJudge(client=fake_client, model="gpt-5.4-mini")
    result: JudgeResult = judge.evaluate(_wi(), profiles=profiles)

    verdict = result.verdict
    assert verdict["pair"] == ["aider", "cursor"]
    assert verdict["evidence_level"] == "docs-only"
    assert verdict["schema_version"] == "1.0"
    assert verdict["model"]["name"] == "gpt-5.4-mini"
    assert verdict["composite_score"] == 0.45
    assert "verdict_id" in verdict
    # all 5 dimensions present
    assert set(verdict["sub_verdicts"].keys()) == {
        "A_prompt_injection",
        "B_data_leakage",
        "C_capability_conflict",
        "D_cascading_error",
        "E_compliance",
    }


def test_judge_cost_is_recorded(fake_judge_pair_response) -> None:
    profiles = {"aider": {"slug": "aider"}, "cursor": {"slug": "cursor"}}
    fake_client = MagicMock()
    fake_client.judge_pair = AsyncMock(return_value=fake_judge_pair_response)

    judge = DocsOnlyJudge(client=fake_client, model="gpt-5.4-mini")
    result = judge.evaluate(_wi(), profiles=profiles)
    assert result.cost_usd > 0
    assert result.cost_usd <= judge.cost_per_call_usd * 2  # safety bound


def test_judge_verdict_id_is_deterministic(fake_judge_pair_response) -> None:
    profiles = {"aider": {"slug": "aider"}, "cursor": {"slug": "cursor"}}
    fake_client = MagicMock()
    fake_client.judge_pair = AsyncMock(return_value=fake_judge_pair_response)
    judge = DocsOnlyJudge(client=fake_client, model="gpt-5.4-mini")

    a = judge.evaluate(_wi(), profiles=profiles).verdict["verdict_id"]
    b = judge.evaluate(_wi(), profiles=profiles).verdict["verdict_id"]
    assert a == b


def test_judge_missing_profile_raises() -> None:
    judge = DocsOnlyJudge(client=MagicMock(), model="gpt-5.4-mini")
    with pytest.raises(KeyError):
        judge.evaluate(_wi(), profiles={"aider": {}})  # cursor missing
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/autopilot/judges/test_docs_only.py -v
```
Expected: ImportError on `smadp.autopilot.judges.docs_only`.

- [ ] **Step 3: Write minimal implementation**

`smadp/autopilot/judges/__init__.py`: (empty file)

`smadp/autopilot/judges/docs_only.py`:
```python
"""DocsOnlyJudge: produce a Docs-only pair verdict from profile metadata.

Wraps ``LLMClient.judge_pair`` (already wired against OpenAI tool-calling). The
verdict gets ``evidence_level: "docs-only"`` and the same risk-dimension shape as
existing sandbox verdicts so the site renders it without changes.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import structlog

from smadp.autopilot.work_queue import WorkItem

log = structlog.get_logger(__name__)

_DIMENSION_KEYS = (
    "A_prompt_injection",
    "B_data_leakage",
    "C_capability_conflict",
    "D_cascading_error",
    "E_compliance",
)


@dataclass(frozen=True)
class JudgeResult:
    verdict: dict[str, Any]
    cost_usd: float


class DocsOnlyJudge:
    name = "docs_only"
    version = "v1"
    evidence_level = "docs-only"
    # Calibrated against gpt-5.4-mini for ~3k in + ~800 out tokens.
    cost_per_call_usd = 0.04

    def __init__(self, *, client, model: str) -> None:
        self.client = client
        self.model = model

    def evaluate(self, work: WorkItem, *, profiles: dict[str, dict]) -> JudgeResult:
        slug_a, slug_b = work.pair
        profile_a = profiles[slug_a]
        profile_b = profiles[slug_b]

        raw = asyncio.run(self.client.judge_pair(
            model=self.model,
            profile_a=profile_a,
            profile_b=profile_b,
        ))

        verdict = self._wrap(raw, slug_a=slug_a, slug_b=slug_b)
        return JudgeResult(verdict=verdict, cost_usd=self.cost_per_call_usd)

    def _wrap(self, raw: dict, *, slug_a: str, slug_b: str) -> dict:
        sub_verdicts = raw.get("sub_verdicts") or {}
        missing = [k for k in _DIMENSION_KEYS if k not in sub_verdicts]
        if missing:
            raise ValueError(f"DocsOnlyJudge: missing risk dimensions {missing}")
        verdict_id = self._verdict_id(slug_a, slug_b)
        return {
            "schema_version": "1.0",
            "pair": [slug_a, slug_b],
            "verdict_id": verdict_id,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "model": {
                "name": self.model,
                "id": self.model,
                "rubric_version": "1.0",
            },
            "evidence_level": "docs-only",
            "confidence": float(raw.get("confidence", 0.5)),
            "composite_score": float(raw["composite_score"]),
            "headline": str(raw.get("headline", "")),
            "sub_verdicts": sub_verdicts,
            "framework_mappings": raw.get("framework_mappings") or {},
        }

    def _verdict_id(self, slug_a: str, slug_b: str) -> str:
        canon = ":".join(sorted([slug_a, slug_b])) + ":" + self.name + ":" + self.version
        digest = hashlib.sha1(canon.encode("utf-8")).hexdigest()[:6]
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        a, b = sorted([slug_a, slug_b])
        return f"v_{today}_{a}__{b}_{digest}"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/autopilot/judges/test_docs_only.py -v
```
Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add smadp/autopilot/judges tests/autopilot/judges
git commit -m "feat(autopilot): DocsOnlyJudge wraps LLMClient.judge_pair, emits docs-only verdict"
```

---

## Task 5: PolicyPublisher — auto-pub docs-only, queue sandbox

**Files:**
- Create: `smadp/autopilot/publishers/__init__.py` (empty)
- Create: `smadp/autopilot/publishers/policy.py`
- Create: `tests/autopilot/publishers/__init__.py` (empty)
- Create: `tests/autopilot/publishers/test_policy.py`

- [ ] **Step 1: Write the failing test**

`tests/autopilot/publishers/test_policy.py`:
```python
"""Tests for PolicyPublisher."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from smadp.autopilot.publishers.policy import PolicyPublisher


def _verdict(evidence_level: str) -> dict:
    return {
        "schema_version": "1.0",
        "verdict_id": f"v_test_{evidence_level}",
        "pair": ["aider", "cursor"],
        "evidence_level": evidence_level,
        "composite_score": 0.3,
        "model": {"name": "gpt-5.4-mini", "id": "gpt-5.4-mini", "rubric_version": "1.0"},
        "headline": "h",
        "sub_verdicts": {},
        "framework_mappings": {},
        "confidence": 0.7,
        "generated_at": "2026-06-06T00:00:00Z",
    }


def test_docs_only_writes_to_verdicts(tmp_path: Path) -> None:
    pub = PolicyPublisher(
        catalog_root=tmp_path / "catalog",
        auto_publish={"docs-only": True, "profile-verified": True, "sandbox-run": False},
    )
    path = pub.commit(_verdict("docs-only"))
    assert path.parent.name == "verdicts"
    assert json.loads(path.read_text())["evidence_level"] == "docs-only"


def test_sandbox_writes_to_pending_when_auto_disabled(tmp_path: Path) -> None:
    pub = PolicyPublisher(
        catalog_root=tmp_path / "catalog",
        auto_publish={"docs-only": True, "profile-verified": True, "sandbox-run": False},
    )
    path = pub.commit(_verdict("sandbox-run"))
    assert path.parent.name == "pending"


def test_commit_is_atomic_and_overwrites(tmp_path: Path) -> None:
    pub = PolicyPublisher(
        catalog_root=tmp_path / "catalog",
        auto_publish={"docs-only": True, "profile-verified": True, "sandbox-run": True},
    )
    v = _verdict("docs-only")
    path_first = pub.commit(v)
    v2 = {**v, "composite_score": 0.99}
    path_second = pub.commit(v2)
    assert path_first == path_second
    assert json.loads(path_second.read_text())["composite_score"] == 0.99


def test_commit_creates_parent_dirs(tmp_path: Path) -> None:
    pub = PolicyPublisher(
        catalog_root=tmp_path / "fresh-catalog",
        auto_publish={"docs-only": True, "profile-verified": True, "sandbox-run": False},
    )
    path = pub.commit(_verdict("docs-only"))
    assert path.exists()
    assert path.parent.exists()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/autopilot/publishers/test_policy.py -v
```
Expected: ImportError on `smadp.autopilot.publishers.policy`.

- [ ] **Step 3: Write minimal implementation**

`smadp/autopilot/publishers/__init__.py`: (empty file)

`smadp/autopilot/publishers/policy.py`:
```python
"""PolicyPublisher: route verdicts to verdicts/ or pending/ by evidence tier."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


class PolicyPublisher:
    def __init__(self, *, catalog_root: Path, auto_publish: dict[str, bool]) -> None:
        self.catalog_root = catalog_root
        self.auto_publish = auto_publish

    def commit(self, verdict: dict) -> Path:
        tier = verdict.get("evidence_level", "docs-only")
        publish = self.auto_publish.get(tier, False)
        target_dir = self.catalog_root / ("verdicts" if publish else "pending")
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{verdict['verdict_id']}.json"

        fd, tmp_name = tempfile.mkstemp(prefix=target.name + ".", dir=target_dir)
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(verdict, f, indent=2)
                f.write("\n")
            os.replace(tmp, target)
        except Exception:
            if tmp.exists():
                tmp.unlink()
            raise
        return target
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/autopilot/publishers/test_policy.py -v
```
Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add smadp/autopilot/publishers tests/autopilot/publishers
git commit -m "feat(autopilot): PolicyPublisher routes verdicts by evidence tier"
```

---

## Task 6: TopNPlanner — emit WorkItems for top-N union, capped at 4,950

**Files:**
- Create: `smadp/autopilot/planners/__init__.py` (empty)
- Create: `smadp/autopilot/planners/top_n.py`
- Create: `tests/autopilot/planners/__init__.py` (empty)
- Create: `tests/autopilot/planners/test_top_n.py`

- [ ] **Step 1: Write the failing test**

`tests/autopilot/planners/test_top_n.py`:
```python
"""Tests for TopNPlanner."""

from __future__ import annotations

from smadp.autopilot.planners.top_n import TopNPlanner


def _profile(slug: str, score: float) -> dict:
    return {"slug": slug, "composite_score": score, "evidence_level": "docs-only"}


def test_emits_all_pairs_for_small_set() -> None:
    profiles = [
        _profile("a", 0.9),
        _profile("b", 0.8),
        _profile("c", 0.7),
    ]
    planner = TopNPlanner(top_n=10, pair_cap=10, judge_name="docs_only", judge_version="v1")
    items = planner.plan(profiles=profiles, now_iso="2026-06-06T00:00:00Z")

    pairs = {tuple(i.pair) for i in items}
    assert pairs == {("a", "b"), ("a", "c"), ("b", "c")}


def test_pairs_sorted_canonically() -> None:
    profiles = [_profile("zebra", 0.9), _profile("aider", 0.8)]
    planner = TopNPlanner(top_n=10, pair_cap=10, judge_name="docs_only", judge_version="v1")
    items = planner.plan(profiles=profiles, now_iso="2026-06-06T00:00:00Z")
    assert items[0].pair == ("aider", "zebra")


def test_top_n_filters_lowest_scores() -> None:
    profiles = [_profile(s, score) for s, score in [
        ("a", 0.9), ("b", 0.8), ("c", 0.7), ("d", 0.1)
    ]]
    planner = TopNPlanner(top_n=3, pair_cap=10, judge_name="docs_only", judge_version="v1")
    items = planner.plan(profiles=profiles, now_iso="2026-06-06T00:00:00Z")
    slugs_in_pairs = {s for i in items for s in i.pair}
    assert "d" not in slugs_in_pairs


def test_pair_cap_honored_by_priority() -> None:
    profiles = [_profile(s, s_score) for s, s_score in zip("abcdef", [0.9, 0.8, 0.7, 0.6, 0.5, 0.4])]
    # 6C2 = 15 possible pairs
    planner = TopNPlanner(top_n=6, pair_cap=5, judge_name="docs_only", judge_version="v1")
    items = planner.plan(profiles=profiles, now_iso="2026-06-06T00:00:00Z")
    assert len(items) == 5
    # highest-priority pair should be (a,b) — product 0.72
    assert items[0].pair == ("a", "b")
    # priorities must be descending
    priorities = [i.priority for i in items]
    assert priorities == sorted(priorities, reverse=True)


def test_priority_is_score_product() -> None:
    profiles = [_profile("a", 0.9), _profile("b", 0.5)]
    planner = TopNPlanner(top_n=10, pair_cap=10, judge_name="docs_only", judge_version="v1")
    items = planner.plan(profiles=profiles, now_iso="2026-06-06T00:00:00Z")
    assert items[0].priority == pytest.approx(0.45)


# Allow `pytest.approx` above
import pytest  # noqa: E402
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/autopilot/planners/test_top_n.py -v
```
Expected: ImportError on `smadp.autopilot.planners.top_n`.

- [ ] **Step 3: Write minimal implementation**

`smadp/autopilot/planners/__init__.py`: (empty file)

`smadp/autopilot/planners/top_n.py`:
```python
"""TopNPlanner: pick top-N profiles by composite_score, emit all-pair WorkItems."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from smadp.autopilot.work_queue import WorkItem


@dataclass(frozen=True)
class TopNPlanner:
    top_n: int
    pair_cap: int
    judge_name: str
    judge_version: str

    def plan(self, *, profiles: list[dict], now_iso: str) -> list[WorkItem]:
        scored = sorted(
            profiles,
            key=lambda p: float(p.get("composite_score", 0.0)),
            reverse=True,
        )[: self.top_n]

        items: list[WorkItem] = []
        for p1, p2 in combinations(scored, 2):
            slugs = tuple(sorted([p1["slug"], p2["slug"]]))
            priority = float(p1["composite_score"]) * float(p2["composite_score"])
            items.append(
                WorkItem(
                    pair=(slugs[0], slugs[1]),
                    requested_judge=self.judge_name,
                    judge_version=self.judge_version,
                    priority=priority,
                    enqueued_at=now_iso,
                )
            )
        items.sort(key=lambda i: -i.priority)
        return items[: self.pair_cap]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/autopilot/planners/test_top_n.py -v
```
Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add smadp/autopilot/planners tests/autopilot/planners
git commit -m "feat(autopilot): TopNPlanner emits priority-sorted all-pair WorkItems"
```

---

## Task 7: docs_only_tick — orchestrate drain → judge → publish

**Files:**
- Create: `smadp/autopilot/docs_only_tick.py`
- Create: `tests/autopilot/test_docs_only_tick.py`

- [ ] **Step 1: Write the failing test**

`tests/autopilot/test_docs_only_tick.py`:
```python
"""Tests for run_docs_only_tick."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from smadp.autopilot.docs_only_tick import DocsOnlyTickSummary, run_docs_only_tick
from smadp.autopilot.judges.docs_only import JudgeResult
from smadp.autopilot.work_queue import WorkItem, append_items


def _seed_profiles(repo: Path, slugs: list[str]) -> None:
    (repo / "catalog" / "profiles").mkdir(parents=True, exist_ok=True)
    for slug in slugs:
        (repo / "catalog" / "profiles" / f"{slug}.json").write_text(
            json.dumps(
                {
                    "slug": slug,
                    "name": slug.title(),
                    "category": "coding",
                    "evidence_level": "docs-only",
                    "capabilities": {},
                    "docs_urls": [],
                }
            )
        )


def _seed_queue(repo: Path, items: list[WorkItem]) -> None:
    queue = repo / "state" / "docs_only_queue.jsonl"
    append_items(queue, items)


def _seed_autopilot_config(repo: Path, *, runs_per_day: int, dollars_per_day: float) -> None:
    (repo / "config").mkdir(parents=True, exist_ok=True)
    (repo / "config" / "autopilot.yaml").write_text(
        f"runs_per_day: {runs_per_day}\ndollars_per_day: {dollars_per_day}\n"
    )


def _fake_verdict(slug_a: str, slug_b: str) -> dict:
    a, b = sorted([slug_a, slug_b])
    return {
        "schema_version": "1.0",
        "verdict_id": f"v_test_{a}__{b}",
        "pair": [a, b],
        "evidence_level": "docs-only",
        "composite_score": 0.4,
        "model": {"name": "gpt-5.4-mini", "id": "gpt-5.4-mini", "rubric_version": "1.0"},
        "headline": "h",
        "sub_verdicts": {},
        "framework_mappings": {},
        "confidence": 0.7,
        "generated_at": "2026-06-06T00:00:00Z",
    }


def _judge_factory(verdicts: list[dict]):
    fake = MagicMock()
    def evaluate(work, *, profiles):
        return JudgeResult(verdict=verdicts.pop(0), cost_usd=0.04)
    fake.evaluate = evaluate
    fake.cost_per_call_usd = 0.04
    fake.name = "docs_only"
    return fake


def test_tick_drains_and_publishes(tmp_path: Path) -> None:
    repo = tmp_path
    _seed_autopilot_config(repo, runs_per_day=10, dollars_per_day=5.0)
    _seed_profiles(repo, ["aider", "cursor"])
    _seed_queue(
        repo,
        [
            WorkItem(
                pair=("aider", "cursor"),
                requested_judge="docs_only",
                judge_version="v1",
                priority=0.9,
                enqueued_at="2026-06-06T00:00:00Z",
            )
        ],
    )
    judge = _judge_factory([_fake_verdict("aider", "cursor")])

    summary = run_docs_only_tick(
        repo_root=repo,
        judge=judge,
        batch_size=10,
    )
    assert isinstance(summary, DocsOnlyTickSummary)
    assert summary.published == 1
    assert summary.reason == "ok"
    assert list((repo / "catalog" / "verdicts").glob("*.json"))


def test_tick_respects_budget(tmp_path: Path) -> None:
    repo = tmp_path
    _seed_autopilot_config(repo, runs_per_day=1, dollars_per_day=5.0)
    _seed_profiles(repo, ["aider", "cursor", "claude-code"])
    _seed_queue(
        repo,
        [
            WorkItem(("aider", "cursor"), "docs_only", "v1", 0.9, "2026-06-06T00:00:00Z"),
            WorkItem(("aider", "claude-code"), "docs_only", "v1", 0.8, "2026-06-06T00:00:00Z"),
        ],
    )
    judge = _judge_factory([_fake_verdict("aider", "cursor"), _fake_verdict("aider", "claude-code")])

    summary = run_docs_only_tick(repo_root=repo, judge=judge, batch_size=10)
    assert summary.published == 1  # only one run allowed today


def test_tick_returns_no_work_when_queue_empty(tmp_path: Path) -> None:
    _seed_autopilot_config(tmp_path, runs_per_day=10, dollars_per_day=5.0)
    summary = run_docs_only_tick(
        repo_root=tmp_path,
        judge=_judge_factory([]),
        batch_size=10,
    )
    assert summary.reason == "no_work"
    assert summary.published == 0


def test_tick_pause_short_circuits(tmp_path: Path) -> None:
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "PAUSED").touch()
    summary = run_docs_only_tick(
        repo_root=tmp_path,
        judge=_judge_factory([]),
        batch_size=10,
    )
    assert summary.reason == "paused"


def test_tick_logs_failure_and_continues(tmp_path: Path) -> None:
    """A judge raising on one item should not poison the rest of the batch."""
    repo = tmp_path
    _seed_autopilot_config(repo, runs_per_day=10, dollars_per_day=5.0)
    _seed_profiles(repo, ["a", "b", "c", "d"])
    _seed_queue(
        repo,
        [
            WorkItem(("a", "b"), "docs_only", "v1", 0.9, "2026-06-06T00:00:00Z"),
            WorkItem(("c", "d"), "docs_only", "v1", 0.8, "2026-06-06T00:00:00Z"),
        ],
    )

    calls = [0]
    def evaluate(work, *, profiles):
        calls[0] += 1
        if calls[0] == 1:
            raise RuntimeError("boom")
        return JudgeResult(verdict=_fake_verdict(*work.pair), cost_usd=0.04)
    judge = MagicMock(name="docs_only", cost_per_call_usd=0.04)
    judge.evaluate = evaluate

    summary = run_docs_only_tick(repo_root=repo, judge=judge, batch_size=10)
    assert summary.published == 1
    assert summary.failed == 1
    assert (repo / "state" / "judge_errors.jsonl").exists()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/autopilot/test_docs_only_tick.py -v
```
Expected: ImportError on `smadp.autopilot.docs_only_tick`.

- [ ] **Step 3: Write minimal implementation**

`smadp/autopilot/docs_only_tick.py`:
```python
"""Docs-only tick: drain work queue → judge → publish → update budget.

Mirrors the existing sandbox ``tick.py`` but operates against the docs-only
work queue and a Python judge instead of the sandbox runner. Reuses
``BudgetState`` so daily caps are shared with the sandbox path.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from smadp.autopilot.budget import (
    BudgetState,
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


def _log_failure(state_dir: Path, *, pair: tuple[str, str], judge_name: str, error: str) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    row = {
        "pair": list(pair),
        "judge": judge_name,
        "error": error,
        "attempted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    with (state_dir / "judge_errors.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def run_docs_only_tick(
    *,
    repo_root: Path,
    judge,
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

    cost_per_call = float(getattr(judge, "cost_per_call_usd", 0.04))
    cap_by_runs = cfg.runs_per_day - budget.runs_today
    cap_by_dollars = int(max(0, (cfg.dollars_per_day - budget.dollars_today) // cost_per_call))
    effective = max(0, min(batch_size, cap_by_runs, cap_by_dollars))

    drained = drain_items(queue_path, limit=effective)
    published = 0
    failed = 0
    for work in drained:
        if not can_enqueue(load_budget(budget_path), cfg, expected_cost=cost_per_call):
            # Budget moved while we were running — bank what we did and stop.
            break
        try:
            result = judge.evaluate(work, profiles=profiles)
            publisher.commit(result.verdict)
            record_run_actual(budget_path, dollars=float(result.cost_usd))
            published += 1
        except Exception as exc:    # narrow catch deferred; log and move on
            failed += 1
            _log_failure(
                state_dir,
                pair=work.pair,
                judge_name=getattr(judge, "name", "docs_only"),
                error=repr(exc),
            )
            log.warning("docs_only_tick.judge_failed", pair=work.pair, error=repr(exc))
    if published == 0 and failed == 0:
        return DocsOnlyTickSummary(published=0, failed=0, reason="no_work")
    return DocsOnlyTickSummary(published=published, failed=failed, reason="ok")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/autopilot/test_docs_only_tick.py -v
```
Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add smadp/autopilot/docs_only_tick.py tests/autopilot/test_docs_only_tick.py
git commit -m "feat(autopilot): docs_only tick drains queue, judges, publishes; respects budget+pause"
```

---

## Task 8: bootstrap_onexus + CLI commands

**Files:**
- Create: `smadp/autopilot/bootstrap.py`
- Modify: `smadp/cli.py` (add 2 subcommands)
- Create: `tests/autopilot/test_bootstrap.py`

- [ ] **Step 1: Write the failing test**

`tests/autopilot/test_bootstrap.py`:
```python
"""Tests for bootstrap_onexus."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from smadp.autopilot.bootstrap import BootstrapSummary, bootstrap_onexus

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures-bootstrap"


@pytest.fixture
def fixture_catalog(tmp_path: Path) -> Path:
    root = tmp_path / "onexus-fixture" / "coding"
    root.mkdir(parents=True)
    for slug, score in [("alpha", 0.91), ("beta", 0.82), ("gamma", 0.73)]:
        (root / f"{slug}.json").write_text(json.dumps({
            "slug": slug,
            "name": slug.title(),
            "category": "coding",
            "tags": ["coding"],
            "author": {"type": "user", "handle": "x", "url": ""},
            "source": {"primary": "github", "github": f"x/{slug}", "homepage": None},
            "license": "MIT",
            "metrics": {"stars": 1, "downloads_30d": None, "last_commit_at": ""},
            "runnable": False,
            "adapter_ref": None,
            "composite_score": score,
            "rank_in_category": 1,
        }))
    return tmp_path / "onexus-fixture"


def test_bootstrap_writes_profiles_and_queue(fixture_catalog: Path, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    summary = bootstrap_onexus(
        repo_root=repo,
        onexus_root=fixture_catalog,
        top_n=10,
        pair_cap=10,
    )
    assert isinstance(summary, BootstrapSummary)
    assert summary.profiles_written == 3
    assert summary.pairs_queued == 3
    profiles_dir = repo / "catalog" / "profiles"
    assert {p.stem for p in profiles_dir.glob("*.json")} == {"alpha", "beta", "gamma"}
    queue_path = repo / "state" / "docs_only_queue.jsonl"
    assert queue_path.exists()
    lines = queue_path.read_text("utf-8").strip().splitlines()
    assert len(lines) == 3


def test_bootstrap_skips_manual_profiles(fixture_catalog: Path, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "catalog" / "profiles").mkdir(parents=True)
    (repo / "catalog" / "profiles" / "alpha.json").write_text(json.dumps({
        "slug": "alpha", "manual": True, "name": "Hand-written"
    }))
    summary = bootstrap_onexus(
        repo_root=repo,
        onexus_root=fixture_catalog,
        top_n=10,
        pair_cap=10,
    )
    # alpha must not be overwritten
    preserved = json.loads((repo / "catalog" / "profiles" / "alpha.json").read_text())
    assert preserved == {"slug": "alpha", "manual": True, "name": "Hand-written"}
    assert summary.profiles_skipped == 1
    assert summary.profiles_written == 2


def test_bootstrap_is_idempotent(fixture_catalog: Path, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    first = bootstrap_onexus(
        repo_root=repo, onexus_root=fixture_catalog, top_n=10, pair_cap=10,
    )
    second = bootstrap_onexus(
        repo_root=repo, onexus_root=fixture_catalog, top_n=10, pair_cap=10,
    )
    queue_lines = (repo / "state" / "docs_only_queue.jsonl").read_text("utf-8").strip().splitlines()
    assert len(queue_lines) == first.pairs_queued == second.pairs_queued
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/autopilot/test_bootstrap.py -v
```
Expected: ImportError on `smadp.autopilot.bootstrap`.

- [ ] **Step 3: Write minimal implementation**

`smadp/autopilot/bootstrap.py`:
```python
"""bootstrap_onexus: one-shot importer + planner.

Reads the ONEXUS catalog, normalizes each record into an SMADP profile, writes
the profile JSON (skipping any file containing ``"manual": true``), then runs
TopNPlanner against the resulting profile set and appends WorkItems into
``state/docs_only_queue.jsonl``.

Also folds in pre-existing SMADP profiles on disk so the top-N union covers
hand-curated agents (aider, cursor, etc.) that may have lower ONEXUS scores.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import structlog

from smadp.autopilot.planners.top_n import TopNPlanner
from smadp.autopilot.profilers.onexus import OnexusProfiler
from smadp.autopilot.sources.onexus import OnexusSource
from smadp.autopilot.work_queue import append_items

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class BootstrapSummary:
    profiles_written: int
    profiles_skipped: int
    pairs_queued: int


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise


def _existing_profile_has_manual_flag(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        return bool(json.loads(path.read_text("utf-8")).get("manual"))
    except (OSError, json.JSONDecodeError):
        return False


def _load_existing_profiles(profiles_dir: Path) -> list[dict]:
    if not profiles_dir.exists():
        return []
    out: list[dict] = []
    for path in profiles_dir.glob("*.json"):
        try:
            out.append(json.loads(path.read_text("utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return out


def bootstrap_onexus(
    *,
    repo_root: Path,
    onexus_root: Path,
    top_n: int,
    pair_cap: int,
) -> BootstrapSummary:
    source = OnexusSource(root=onexus_root)
    profiler = OnexusProfiler()
    profiles_dir = repo_root / "catalog" / "profiles"

    written = 0
    skipped = 0
    new_profiles: list[dict] = []
    for raw in source.fetch():
        path = profiles_dir / f"{raw.slug}.json"
        if _existing_profile_has_manual_flag(path):
            skipped += 1
            log.info("bootstrap.skip_manual", slug=raw.slug)
            continue
        profile = profiler.normalize(raw)
        _atomic_write(path, profile)
        new_profiles.append(profile)
        written += 1

    # Union with existing profiles for TopN — preserves hand-curated agents.
    union: dict[str, dict] = {}
    for p in _load_existing_profiles(profiles_dir):
        if not p.get("slug"):
            continue
        union[p["slug"]] = p
    # Slot in the freshly-written ones (in case a hand-curated one had no score):
    for p in new_profiles:
        union.setdefault(p["slug"], p)

    planner = TopNPlanner(
        top_n=top_n,
        pair_cap=pair_cap,
        judge_name="docs_only",
        judge_version="v1",
    )
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    items = planner.plan(profiles=list(union.values()), now_iso=now)
    queue_path = repo_root / "state" / "docs_only_queue.jsonl"
    append_items(queue_path, items)

    return BootstrapSummary(
        profiles_written=written,
        profiles_skipped=skipped,
        pairs_queued=len(items),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/autopilot/test_bootstrap.py -v
```
Expected: all 3 tests PASS.

- [ ] **Step 5: Wire CLI commands**

Modify `smadp/cli.py`. After the existing `autopilot_approve` function (around line 783), add:

```python
@autopilot.command("bootstrap-onexus")
@click.option(
    "--onexus-root",
    default=str(Path.home() / "Downloads" / "ONEXUS-Agents" / "catalog"),
    help="Path to the ONEXUS-Agents catalog directory.",
)
@click.option("--top-n", default=100, type=int, help="Number of top-scored agents to include.")
@click.option("--pair-cap", default=4950, type=int, help="Maximum pairs to enqueue.")
@click.pass_context
def autopilot_bootstrap_onexus(ctx: click.Context, onexus_root: str, top_n: int, pair_cap: int) -> None:
    """Import ONEXUS agents and queue Docs-only pair work."""
    from smadp.autopilot.bootstrap import bootstrap_onexus

    config = ctx.obj["config"]
    summary = bootstrap_onexus(
        repo_root=config.repo_root,
        onexus_root=Path(onexus_root).expanduser(),
        top_n=top_n,
        pair_cap=pair_cap,
    )
    click.echo(
        f"profiles_written={summary.profiles_written} "
        f"profiles_skipped={summary.profiles_skipped} "
        f"pairs_queued={summary.pairs_queued}"
    )


@autopilot.command("docs-only-tick")
@click.option("--batch-size", default=10, type=int)
@click.pass_context
def autopilot_docs_only_tick(ctx: click.Context, batch_size: int) -> None:
    """Drain the docs-only queue, judge with gpt-5.4-mini, publish verdicts."""
    from smadp.autopilot.docs_only_tick import run_docs_only_tick
    from smadp.autopilot.judges.docs_only import DocsOnlyJudge
    from smadp.llm.client import LLMClient

    config = ctx.obj["config"]
    client = LLMClient(config=config)
    judge = DocsOnlyJudge(client=client, model="gpt-5.4-mini")
    summary = run_docs_only_tick(
        repo_root=config.repo_root,
        judge=judge,
        batch_size=batch_size,
    )
    click.echo(
        f"published={summary.published} failed={summary.failed} reason={summary.reason}"
    )
```

If `from pathlib import Path` is not already imported at the top of `smadp/cli.py`, add it.

- [ ] **Step 6: Smoke the CLI wiring (no LLM calls)**

```bash
cd "/Users/connorevans/Desktop/Frontier_AI/Safe Multi-Agent Deployment Platform (SMADP)/SMADP"
python -m smadp.cli autopilot --help
```
Expected: output lists `bootstrap-onexus` and `docs-only-tick` alongside existing subcommands.

- [ ] **Step 7: Commit**

```bash
git add smadp/autopilot/bootstrap.py smadp/cli.py tests/autopilot/test_bootstrap.py
git commit -m "feat(autopilot): bootstrap-onexus + docs-only-tick CLI commands"
```

---

## Task 9: 5-pair smoke validation (the deliverable for tonight)

**Files:** None — this is the manual validation gate.

- [ ] **Step 1: Confirm canonical ONEXUS catalog is reachable**

```bash
ls "$HOME/Downloads/ONEXUS-Agents/catalog" | head
find "$HOME/Downloads/ONEXUS-Agents/catalog" -name '*.json' | wc -l
```
Expected: a directory listing of ~41 categories and ~3,200 JSON records.

- [ ] **Step 2: Bootstrap a tiny subset**

```bash
cd "/Users/connorevans/Desktop/Frontier_AI/Safe Multi-Agent Deployment Platform (SMADP)/SMADP"
python -m smadp.cli autopilot bootstrap-onexus --top-n 5 --pair-cap 10
```
Expected console:
```
profiles_written=<≤5> profiles_skipped=<may be >0 if existing> pairs_queued=<≤10>
```
Verify:
```bash
ls catalog/profiles | head
wc -l state/docs_only_queue.jsonl
```

- [ ] **Step 3: Confirm OpenAI key is loaded**

```bash
echo "OPENAI_API_KEY set? $([ -n "$OPENAI_API_KEY" ] && echo yes || echo no)"
```
If `no`: source the env file the project already uses (typically `.env` or `direnv`). DO NOT print the key value.

- [ ] **Step 4: Run 5 real docs-only ticks**

```bash
for i in 1 2 3 4 5; do
  python -m smadp.cli autopilot docs-only-tick --batch-size 1
done
```
Expected each run: `published=1 failed=0 reason=ok`. If any failure: read the row from `state/judge_errors.jsonl` and stop — do not advance until the failure is understood.

- [ ] **Step 5: Eyeball the verdicts**

```bash
ls -t catalog/verdicts | head -5
cat catalog/verdicts/$(ls -t catalog/verdicts | head -1) | jq .headline,.composite_score,.confidence,.sub_verdicts.A_prompt_injection.severity
```
**Halt criteria — do NOT activate the loop if any of these are true:**
- `headline` reads like nonsense or contradicts the pair (e.g. talks about agents not in the pair).
- `composite_score` is identical across all 5 verdicts (model collapsed).
- Any `sub_verdicts.X.severity` is missing or returns `null`.
- `evidence_level` is anything other than `"docs-only"`.

- [ ] **Step 6: Rebuild site and verify pages render**

```bash
cd site
pnpm build:html 2>&1 | tail -5
```
Expected: 5 new pages under `/verdicts/<verdict_id>/` show up in the build output (page count increases by 5 versus the prior build).

- [ ] **Step 7: Commit the smoke artifacts**

```bash
cd ..
git add catalog/profiles catalog/verdicts state/docs_only_queue.jsonl state/budget.json
git commit -m "chore(catalog): seed Docs-only verdicts from 5-pair ONEXUS smoke"
```

- [ ] **Step 8: Launchd activation gate**

After the 5-pair smoke is committed and the user has reviewed the verdicts on the site:
- Add `python -m smadp.cli autopilot docs-only-tick --batch-size 5` as a second line in `scripts/autopilot-loop.sh` (right after the existing sandbox tick line).
- The existing launchd plist already invokes `autopilot-loop.sh` every 300 s — no plist edits required.

```bash
cat scripts/autopilot-loop.sh
```
Inspect; add the line; then:
```bash
git add scripts/autopilot-loop.sh
git commit -m "feat(autopilot): launchd loop also drains docs-only queue"
```

---

## Self-review

**Spec coverage:**

| Spec section | Implementing task(s) |
| --- | --- |
| Five-stage modular pipeline | T1–T8 collectively |
| Source (OnexusSource) | T2 |
| Profiler (OnexusProfiler) | T3 |
| Planner (TopNPlanner) | T6 |
| Judge (DocsOnlyJudge) | T4 |
| Publisher (PolicyPublisher) | T5 |
| Registry mechanism | Deferred — current plan uses direct injection; explicit registry can land in a follow-up without breaking these interfaces |
| Bootstrap CLI | T8 |
| Steady-state tick | T7 (`docs_only_tick`) |
| Budget integration | T7 reuses `BudgetState`, `can_enqueue`, `record_run_actual` |
| Auto-publish docs-only / queue sandbox | T5 with config |
| Manual profile preservation (`manual: true`) | T8 (`bootstrap` checks the flag) |
| `verdict_id` idempotency | T4 (`DocsOnlyJudge._verdict_id`) + T5 atomic write |
| Error handling (per-item failure → jsonl, continue) | T7 |
| Budget exhaustion | T7 |
| Pause respected | T7 |
| Atomic disk writes | T1, T5, T8 |
| 5-pair smoke validation | T9 |
| Launchd activation gate | T9 step 8 |
| gpt-5.4-mini hardcoded for tonight | T8 CLI command and T9 |

Deferred from spec (call-outs):
- The Registry/ABC layer is implicit (judge passed by name from CLI). Adding `Registry.get_judge("docs_only")` is a small follow-up; nothing in T1–T9 blocks it.
- `SandboxJudge` wrapper is not built tonight — the sandbox path still runs via the existing `tick.py` unchanged. The spec called for a wrapper "for registry uniformity"; deferring it costs nothing tonight.

**Placeholder scan:** no TBDs, no "TODO" hand-offs, every task has runnable code.

**Type consistency:**
- `WorkItem.pair: tuple[str, str]` — used identically in T1, T4, T6, T7.
- `JudgeResult.verdict: dict[str, Any]` — emitted by T4, consumed by T5/T7.
- `PolicyPublisher.commit(verdict: dict) -> Path` — same shape across T5, T7.
- `BootstrapSummary(profiles_written, profiles_skipped, pairs_queued)` — referenced in T8 tests and CLI summary line.
- `DocsOnlyTickSummary(published, failed, reason)` — used by T7 + T8 CLI summary line.
- Judge interface contract used by `run_docs_only_tick`: `judge.evaluate(work, *, profiles) -> JudgeResult`, `judge.cost_per_call_usd: float`, `judge.name: str`. Matches `DocsOnlyJudge` exactly.

No mismatches found.
