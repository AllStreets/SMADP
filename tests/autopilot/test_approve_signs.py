"""approve_one signs published verdicts best-effort with a detached BYOK sidecar."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from smadp.autopilot.pending import (
    PUBLISHER_WORKSPACE_ID,
    approve_one,
    ensure_publisher_workspace,
)
from smadp.config import Config
from smadp.passport.publish_sign import verify_verdict_signature
from smadp.tenancy import keys

_VERDICT = {
    "verdict_id": "v_2026-06-12_a__b_abcd1234",
    "evidence_level": "docs-only",
    "headline": "ok",
}


def _stage_pending(repo: Path) -> str:
    key = "v_2026-06-12_a__b_abcd1234"
    pending = repo / "catalog" / "pending"
    pending.mkdir(parents=True)
    (pending / f"{key}.json").write_text(json.dumps(_VERDICT), encoding="utf-8")
    return key


def test_approve_signs_when_publisher_key_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SMADP_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    cfg = Config(repo_root=tmp_path)

    ensure_publisher_workspace(config=cfg)
    keys.upload_signing_key(
        workspace_id=PUBLISHER_WORKSPACE_ID,
        private_key=Ed25519PrivateKey.generate(),
        config=cfg,
    )

    key = _stage_pending(tmp_path)
    verdict_path = approve_one(key=key, repo_root=tmp_path)

    sidecar_path = verdict_path.with_name(f"{key}.sig.json")
    assert sidecar_path.exists()
    sidecar = json.loads(sidecar_path.read_text("utf-8"))
    assert sidecar["signing_strategy"] == "byok"
    verdict = json.loads(verdict_path.read_text("utf-8"))
    assert verify_verdict_signature(verdict, sidecar) is True


def test_approve_unsigned_when_no_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMADP_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)

    key = _stage_pending(tmp_path)
    verdict_path = approve_one(key=key, repo_root=tmp_path)

    assert verdict_path.exists()
    assert not verdict_path.with_name(f"{key}.sig.json").exists()
