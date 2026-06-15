"""API: /{a}/{b}/causality computed at read from the risk-causality DAG."""
from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from smadp.api.server import create_app
from smadp.catalog.repo import CatalogRepo
from smadp.config import Config
from smadp.schemas.verdict import (
    Citation,
    Reproducibility,
    SubVerdict,
    SubVerdicts,
    Verdict,
    VerdictModel,
)

TS = datetime(2026, 6, 12, tzinfo=UTC)


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    catalog = tmp_path / "catalog"
    seed = Path(__file__).resolve().parents[2] / "catalog"
    shutil.copytree(seed, catalog)
    monkeypatch.setenv("SMADP_CATALOG", str(catalog))
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return Config()


def _sv(sev: str) -> SubVerdict:
    return SubVerdict(severity=sev, rationale="r", citations=[Citation(quote="q")])


def _save_verdict(cfg: Config) -> None:
    verdict = Verdict(
        participants=["aider", "continue-dev"],
        verdict_id="v_2026-06-12_aider__continue-dev_abcd",
        generated_at=TS,
        model=VerdictModel(name="m", id="m", rubric_version="1.0"),
        evidence_level="sandbox-validated",
        confidence=0.5,
        composite_score=0.3,
        headline="h",
        sub_verdicts=SubVerdicts(
            A_prompt_injection=_sv("high"),
            B_data_leakage=_sv("medium"),
            C_capability_conflict=_sv("none"),
            D_cascading_error=_sv("low"),
            E_compliance=_sv("none"),
        ),
        reproducibility=Reproducibility(
            rubric_url="https://example.com",
            profile_a_hash="sha256:" + "0" * 64,
            profile_b_hash="sha256:" + "0" * 64,
            evidence_bundle_hash="sha256:" + "0" * 64,
        ),
    )
    CatalogRepo(cfg).save_verdict(verdict)


def test_causality_endpoint_returns_computed_leverage(env: Config) -> None:
    cfg = env
    _save_verdict(cfg)
    client = TestClient(create_app(cfg))
    r = client.get("/api/verdicts/aider/continue-dev/causality")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["verdict_id"] == "v_2026-06-12_aider__continue-dev_abcd"
    assert body["best_mitigation"] == "A_prompt_injection"
    assert body["leverage"]["A_prompt_injection"] == 1.5

    # Computed at read: the verdict on disk has NO causality key.
    path = cfg.catalog_dir / "verdicts" / "aider__continue-dev.json"
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert "causality" not in on_disk


def test_causality_unknown_pair_404(env: Config) -> None:
    client = TestClient(create_app(env))
    r = client.get("/api/verdicts/aider/no-such-agent-xyz/causality")
    assert r.status_code == 404
