"""Tests for ProfileEnrichmentJudge."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from smadp.autopilot.judges.profile_enrich import ProfileEnrichmentJudge
from smadp.autopilot.work_queue import WorkItem


def _wi(slug: str = "aider") -> WorkItem:
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
        "onexus": {
            "source_github": "paul-gauthier/aider",
            "author_handle": "paul-gauthier",
            "tags": [],
        },
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


def _fake_fetcher(
    readme: str = "# Aider\n\nAider lets you pair program with LLMs to edit code in your local git repo.",
):
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
    out = result.verdict
    assert out["evidence_level"] == "docs-only"
    assert out["slug"] == "aider"
    assert out["capabilities"]["execute_shell"] is True
    assert result.cost_usd > 0


def test_enrich_short_circuits_when_no_github_source() -> None:
    stub = {
        "slug": "noremote",
        "name": "No Remote",
        "category": "x",
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
    """A 90k-char README is split into multiple evidence items, capped at 6."""
    big = "Aider chunk text. " * 5000
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
    for item in payload.evidence:
        assert item["sha"]
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
    assert payload.now_iso
