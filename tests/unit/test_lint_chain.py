"""Lint validates chain participant slugs and edge endpoints."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from smadp.catalog.lint import lint_catalog
from smadp.config import Config


def _profile(slug: str) -> dict:
    return {
        "schema_version": "1.1",
        "slug": slug,
        "name": slug.title(),
        "vendor": {"type": "company", "handle": "Demo"},
        "source_type": "open-source",
        "category": "coding",
        "verification": {
            "status": "unverified",
            "verified_at": "2026-05-04T00:00:00Z",
            "method": "auto-only",
        },
        "first_seen_at": "2026-05-04T00:00:00Z",
        "last_refreshed_at": "2026-05-04T00:00:00Z",
    }


def _sub() -> dict:
    return {
        "severity": "low", "rationale": "x",
        "citations": [{"profile_field": "agent-a.capabilities.execute_shell"}],
        "conditions": [], "mitigations": [],
    }


def _chain(chain_id: str, *, participants: list[str], edges: list[tuple[str, str]]) -> dict:
    return {
        "schema_version": "1.0", "chain_id": chain_id, "name": chain_id,
        "topology": "linear",
        "participants": [{"slug": s, "role": "planner"} for s in participants],
        "edges": [{"from": a, "to": b, "channel": "prompt"} for a, b in edges],
        "headline": "h",
        "sub_verdicts": {k: _sub() for k in [
            "A_prompt_injection", "B_data_leakage", "C_capability_conflict",
            "D_cascading_error", "E_compliance",
        ]},
        "framework_mappings": {},
        "first_seen_at": "2026-05-04T00:00:00Z", "last_refreshed_at": "2026-05-04T00:00:00Z",
    }


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_KEK_MASTER", "x" * 64)
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SMADP_CATALOG", str(tmp_path / "catalog"))
    cfg = Config()
    cfg.ensure_dirs()
    cfg.schema_dir.mkdir(parents=True, exist_ok=True)
    return cfg


def _seed(cfg: Config, profiles: list[dict], chains: list[dict]) -> None:
    for p in profiles:
        (cfg.profiles_dir / f"{p['slug']}.json").write_text(json.dumps(p), "utf-8")
    for c in chains:
        (cfg.chains_dir / f"{c['chain_id']}.json").write_text(json.dumps(c), "utf-8")


def test_unknown_participant_slug_raises(cfg: Config) -> None:
    chain = _chain(
        "c_test",
        participants=["agent-a", "agent-b", "missing"],
        edges=[("agent-a", "agent-b"), ("agent-b", "missing")],
    )
    _seed(cfg, [_profile("agent-a"), _profile("agent-b")], [chain])
    report = lint_catalog(cfg)
    assert any(i.kind == "chain.participant-xref" for i in report.errors)


def test_edge_endpoint_not_in_participants_raises(cfg: Config) -> None:
    chain = _chain(
        "c_test",
        participants=["agent-a", "agent-b", "agent-c"],
        edges=[("agent-a", "agent-b"), ("agent-b", "agent-d")],
    )
    profiles = [_profile(s) for s in ("agent-a", "agent-b", "agent-c", "agent-d")]
    _seed(cfg, profiles, [chain])
    report = lint_catalog(cfg)
    assert any(i.kind == "chain.edge-endpoint" for i in report.errors)


def test_chain_filename_must_match_id(cfg: Config) -> None:
    chain = _chain(
        "c_alpha",
        participants=["agent-a", "agent-b", "agent-c"],
        edges=[("agent-a", "agent-b")],
    )
    (cfg.chains_dir / "wrong-name.json").write_text(json.dumps(chain), "utf-8")
    for s in ("agent-a", "agent-b", "agent-c"):
        (cfg.profiles_dir / f"{s}.json").write_text(json.dumps(_profile(s)), "utf-8")
    report = lint_catalog(cfg)
    assert any(i.kind == "chain.filename" for i in report.errors)


def test_valid_chain_passes(cfg: Config) -> None:
    chain = _chain(
        "c_test",
        participants=["agent-a", "agent-b", "agent-c"],
        edges=[("agent-a", "agent-b"), ("agent-b", "agent-c")],
    )
    _seed(cfg, [_profile(s) for s in ("agent-a", "agent-b", "agent-c")], [chain])
    report = lint_catalog(cfg)
    chain_errors = [i for i in report.errors if i.kind.startswith("chain.")]
    assert chain_errors == []
