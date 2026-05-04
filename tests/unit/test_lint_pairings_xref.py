"""Lint enforces pairings cross-references."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from smadp.catalog.lint import lint_catalog
from smadp.config import Config


def _profile_json(slug: str, *, pairings: list[str] | None = None) -> dict:
    body = {
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
    if pairings is not None:
        body["pairings"] = pairings
    return body


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_KEK_MASTER", "x" * 64)
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SMADP_CATALOG", str(tmp_path / "catalog"))
    cfg = Config()
    cfg.ensure_dirs()
    (cfg.schema_dir).mkdir(parents=True, exist_ok=True)
    return cfg


def _seed(cfg: Config, profiles: list[dict]) -> None:
    for prof in profiles:
        path = cfg.profiles_dir / f"{prof['slug']}.json"
        path.write_text(json.dumps(prof), encoding="utf-8")


def test_pairings_orphan_raises_error(cfg: Config) -> None:
    _seed(cfg, [_profile_json("aa", pairings=["does-not-exist"])])
    report = lint_catalog(cfg)
    assert any(i.kind == "profile.pairings-xref" for i in report.errors)


def test_pairings_asymmetric_raises_error(cfg: Config) -> None:
    _seed(cfg, [
        _profile_json("aa", pairings=["bb"]),
        _profile_json("bb", pairings=[]),
    ])
    report = lint_catalog(cfg)
    assert any(i.kind == "profile.pairings-symmetric" for i in report.errors)


def test_pairings_self_reference_raises_error(cfg: Config) -> None:
    _seed(cfg, [_profile_json("aa", pairings=["aa"])])
    report = lint_catalog(cfg)
    assert any(i.kind == "profile.pairings-self" for i in report.errors)


def test_pairings_symmetric_passes(cfg: Config) -> None:
    _seed(cfg, [
        _profile_json("aa", pairings=["bb"]),
        _profile_json("bb", pairings=["aa"]),
    ])
    report = lint_catalog(cfg)
    pairings_errors = [i for i in report.errors if i.kind.startswith("profile.pairings-")]
    assert pairings_errors == []
