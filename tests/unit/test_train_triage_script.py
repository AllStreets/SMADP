from __future__ import annotations

from pathlib import Path

import pytest

from smadp.analyzer.triage import TriageModel
from smadp.catalog.repo import CatalogRepo
from smadp.config import Config
from smadp.schemas import Profile, Verdict
from smadp.utils.slug import sort_pair

BASE = {
    "name": "Demo",
    "vendor": {"type": "company", "handle": "acme"},
    "source_type": "open-source",
    "category": "coding",
    "verification": {
        "status": "verified",
        "verified_at": "2026-01-01T00:00:00Z",
        "method": "manual-authoring",
    },
    "first_seen_at": "2026-01-01T00:00:00Z",
    "last_refreshed_at": "2026-01-01T00:00:00Z",
}


def _sub(sev: str = "low") -> dict:
    return {
        "severity": sev,
        "rationale": "stub",
        "citations": [{"quote": "x"}],
        "conditions": [],
        "mitigations": [],
    }


def _profile(slug: str, **caps) -> Profile:
    return Profile.model_validate({**BASE, "slug": slug, "capabilities": caps})


def _verdict(a: str, b: str, *, composite: float, sev: str) -> Verdict:
    a, b = sort_pair(a, b)
    return Verdict.model_validate(
        {
            "schema_version": "1.0",
            "participants": [a, b],
            "verdict_id": f"v_2026-01-01_{a}__{b}_abcd",
            "generated_at": "2026-01-01T00:00:00Z",
            "model": {"id": "gpt-x", "name": "gpt-x", "rubric_version": "1.0"},
            "evidence_level": "profile-verified",
            "confidence": 0.8,
            "composite_score": composite,
            "headline": "stub",
            "sub_verdicts": {
                "A_prompt_injection": _sub(sev),
                "B_data_leakage": _sub(sev),
                "C_capability_conflict": _sub(sev),
                "D_cascading_error": _sub(sev),
                "E_compliance": _sub(sev),
            },
            "reproducibility": {
                "rubric_url": "/_meta/rubric/1.0.json",
                "profile_a_hash": "sha256:" + "0" * 64,
                "profile_b_hash": "sha256:" + "0" * 64,
                "evidence_bundle_hash": "sha256:" + "0" * 64,
            },
        }
    )


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_KEK_MASTER", "x" * 64)
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SMADP_CATALOG", str(tmp_path / "catalog"))
    cfg = Config(repo_root=tmp_path)
    cfg.ensure_dirs()
    return cfg


def _seed(cfg: Config) -> None:
    repo = CatalogRepo(cfg)
    repo.save_profile(_profile("agent-aa", execute_shell=True))
    repo.save_profile(_profile("agent-bb", write_filesystem=True))
    repo.save_profile(_profile("agent-cc"))
    repo.save_profile(_profile("agent-dd", network_egress="broad"))
    repo.save_verdict(_verdict("agent-aa", "agent-bb", composite=0.7, sev="high"))
    repo.save_verdict(_verdict("agent-cc", "agent-dd", composite=0.1, sev="none"))


def test_build_corpus_nonempty(cfg: Config) -> None:
    from scripts.train_triage import build_corpus

    _seed(cfg)
    corpus = build_corpus(CatalogRepo(cfg))
    assert len(corpus) >= 2
    pa, pb, score = corpus[0]
    assert isinstance(pa, Profile)
    assert isinstance(pb, Profile)
    assert 0.0 <= score <= 1.0


def test_main_writes_loadable_artifact(cfg: Config, tmp_path: Path) -> None:
    from scripts.train_triage import main

    _seed(cfg)
    out = tmp_path / "triage" / "v1.json"
    main(["--catalog", str(cfg.catalog_dir), "--out", str(out), "--seed", "3", "--version", "v1"])
    assert out.exists()
    model = TriageModel.load(out)
    assert model.training_set_hash.startswith("sha256:")
