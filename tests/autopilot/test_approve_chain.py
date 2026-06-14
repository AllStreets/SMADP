"""Operator approve-chain promotion (pending/chains -> catalog/chains)."""

from __future__ import annotations

from pathlib import Path

import pytest

from smadp.autopilot.approve import ApproveError, approve_chain
from smadp.catalog.chronicle import Chronicle
from smadp.catalog.repo import CatalogRepo
from smadp.config import Config
from smadp.schemas import Chain


def _chain(chain_id: str = "c_xyz") -> Chain:
    sub = {
        "severity": "low",
        "rationale": "Stub.",
        "citations": [{"quote": "stub"}],
        "conditions": [],
        "mitigations": [],
    }
    return Chain.model_validate(
        {
            "schema_version": "1.1",
            "chain_id": chain_id,
            "name": chain_id,
            "topology": "linear",
            "participants": [
                {"slug": "agent-a", "role": "planner"},
                {"slug": "agent-b", "role": "executor"},
                {"slug": "agent-c", "role": "critic"},
            ],
            "edges": [],
            "headline": "stub.",
            "sub_verdicts": dict.fromkeys(
                [
                    "A_prompt_injection",
                    "B_data_leakage",
                    "C_capability_conflict",
                    "D_cascading_error",
                    "E_compliance",
                ],
                sub,
            ),
            "framework_mappings": {},
            "first_seen_at": "2026-05-04T00:00:00Z",
            "last_refreshed_at": "2026-05-04T00:00:00Z",
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


def test_approve_chain_promotes(cfg: Config) -> None:
    repo = CatalogRepo(cfg)
    pending_path = repo.save_pending_chain(_chain("c_xyz"))
    assert pending_path.exists()

    approve_chain(repo_root=cfg.repo_root, chain_id="c_xyz")

    assert repo.load_chain("c_xyz").chain_id == "c_xyz"
    assert not pending_path.exists()

    events = [e for e in Chronicle(cfg).iter_events() if e.event == "chain.created"]
    assert any(e.by == "operator" for e in events)


def test_approve_missing_chain_raises(cfg: Config) -> None:
    with pytest.raises(ApproveError):
        approve_chain(repo_root=cfg.repo_root, chain_id="c_missing-id")
