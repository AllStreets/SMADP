"""CatalogRepo round-trip for chains."""

from __future__ import annotations

from pathlib import Path

import pytest

from smadp.catalog.repo import CatalogRepo, NotFoundError
from smadp.config import Config
from smadp.schemas import Chain


def _chain(chain_id: str = "c_demo") -> Chain:
    sub = {
        "severity": "low",
        "rationale": "Stub.",
        "citations": [{"profile_field": "agent-a.capabilities.execute_shell"}],
        "conditions": [],
        "mitigations": [],
    }
    return Chain.model_validate({
        "schema_version": "1.0",
        "chain_id": chain_id,
        "name": chain_id,
        "topology": "linear",
        "participants": [
            {"slug": "agent-a", "role": "planner"},
            {"slug": "agent-b", "role": "executor"},
            {"slug": "agent-c", "role": "critic"},
        ],
        "edges": [
            {"from": "agent-a", "to": "agent-b", "channel": "prompt"},
            {"from": "agent-b", "to": "agent-c", "channel": "filesystem"},
        ],
        "headline": "Stub.",
        "sub_verdicts": {k: sub for k in [
            "A_prompt_injection", "B_data_leakage", "C_capability_conflict",
            "D_cascading_error", "E_compliance",
        ]},
        "framework_mappings": {},
        "first_seen_at": "2026-05-04T00:00:00Z",
        "last_refreshed_at": "2026-05-04T00:00:00Z",
    })


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_KEK_MASTER", "x" * 64)
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SMADP_CATALOG", str(tmp_path / "catalog"))
    cfg = Config()
    cfg.ensure_dirs()
    return cfg


def test_save_and_load_chain(cfg: Config) -> None:
    repo = CatalogRepo(cfg)
    chain = _chain()
    repo.save_chain(chain)
    assert repo.load_chain("c_demo").chain_id == "c_demo"


def test_list_chains(cfg: Config) -> None:
    repo = CatalogRepo(cfg)
    repo.save_chain(_chain("c_alpha"))
    repo.save_chain(_chain("c_beta"))
    listed = sorted(c.chain_id for c in repo.list_chains())
    assert listed == ["c_alpha", "c_beta"]


def test_load_unknown_chain_raises(cfg: Config) -> None:
    repo = CatalogRepo(cfg)
    with pytest.raises(NotFoundError):
        repo.load_chain("c_missing")
