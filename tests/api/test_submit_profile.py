"""POST /api/submit/profile — federated, signature-gated, lands in _unverified/."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi.testclient import TestClient

from smadp.api.server import create_app
from smadp.config import Config

_TOKEN = "operator-secret-token"


def _profile_body(slug: str = "fed-agent") -> bytes:
    profile = {
        "schema_version": "1.2",
        "slug": slug,
        "name": "Federated Agent",
        "vendor": {"type": "org", "handle": slug},
        "source_type": "closed-source",
        "category": "federated",
        "verification": {
            "status": "unverified",
            "verified_at": "2026-06-12T00:00:00Z",
            "method": "auto-only",
        },
        "evidence_level": "profile-verified",
        "first_seen_at": "2026-06-12T00:00:00Z",
        "last_refreshed_at": "2026-06-12T00:00:00Z",
    }
    return json.dumps(profile).encode("utf-8")


def _pub_hex(key: Ed25519PrivateKey) -> str:
    return key.public_key().public_bytes(
        encoding=Encoding.Raw, format=PublicFormat.Raw
    ).hex()


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SMADP_KEK_MASTER", "x" * 64)
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SMADP_CATALOG", str(tmp_path / "catalog"))
    monkeypatch.setenv("SMADP_API_TOKEN", _TOKEN)
    cfg = Config(repo_root=tmp_path)
    cfg.ensure_dirs()
    cfg.unverified_profiles_dir.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "registered_keys.json").write_text(
        json.dumps({"k1": {"enabled": True, "public_key_hex": _pub_hex(key)}}),
        encoding="utf-8",
    )
    client = TestClient(create_app(cfg))
    return client, cfg, key, tmp_path


def test_valid_signed_submission_lands_in_unverified(setup) -> None:
    client, cfg, key, _tmp_path = setup
    body = _profile_body("fed-agent")
    sig = key.sign(body).hex()
    resp = client.post(
        "/api/submit/profile",
        content=body,
        headers={
            "Authorization": f"Bearer {_TOKEN}",
            "X-SMADP-Key-Id": "k1",
            "X-SMADP-Signature": sig,
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 202, resp.text
    staged = cfg.unverified_profiles_dir / "fed-agent.json"
    assert staged.exists()
    data = json.loads(staged.read_text("utf-8"))
    # submitter cannot self-assert a higher rung
    assert data["evidence_level"] == "unverified-profile"
    # never published directly
    assert not (cfg.profiles_dir / "fed-agent.json").exists()


def test_unregistered_key_is_403(setup) -> None:
    client, _cfg, key, _tmp_path = setup
    body = _profile_body("fed-agent")
    sig = key.sign(body).hex()
    resp = client.post(
        "/api/submit/profile",
        content=body,
        headers={
            "Authorization": f"Bearer {_TOKEN}",
            "X-SMADP-Key-Id": "unknown",
            "X-SMADP-Signature": sig,
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 403, resp.text


def test_missing_operator_token_is_401(setup) -> None:
    client, _cfg, key, _tmp_path = setup
    body = _profile_body("fed-agent")
    sig = key.sign(body).hex()
    resp = client.post(
        "/api/submit/profile",
        content=body,
        headers={
            "X-SMADP-Key-Id": "k1",
            "X-SMADP-Signature": sig,
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 401, resp.text


def test_federation_disabled_kill_switch_is_503(setup) -> None:
    client, _cfg, key, tmp_path = setup
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "FEDERATION_DISABLED").write_text("", encoding="utf-8")
    body = _profile_body("fed-agent")
    sig = key.sign(body).hex()
    resp = client.post(
        "/api/submit/profile",
        content=body,
        headers={
            "Authorization": f"Bearer {_TOKEN}",
            "X-SMADP-Key-Id": "k1",
            "X-SMADP-Signature": sig,
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 503, resp.text
