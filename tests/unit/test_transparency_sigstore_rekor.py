"""Tests for real Rekor REST submission + inclusion-proof retrieval.

Network is mocked with respx — these tests run offline.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from smadp.config import Config
from smadp.transparency import journal, sigstore


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    monkeypatch.setenv("SMADP_SIGSTORE_ENABLED", "true")
    monkeypatch.setenv("SMADP_REKOR_URL", "https://rekor.example.test")
    return Config()


def _append_one(cfg: Config) -> tuple[int, Ed25519PrivateKey]:
    key = Ed25519PrivateKey.generate()
    ev = journal.append_event(event_type="x.a", payload={"k": 1}, signing_key=key, config=cfg)
    return ev.id, key


def test_submit_to_rekor_when_disabled_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    monkeypatch.setenv("SMADP_SIGSTORE_ENABLED", "false")
    cfg = Config()
    event_id, _ = _append_one(cfg)
    assert sigstore.submit_to_rekor(event_id=event_id, config=cfg) is None


@respx.mock
def test_submit_to_rekor_when_enabled_returns_uuid(cfg: Config):
    event_id, _ = _append_one(cfg)
    respx.post("https://rekor.example.test/api/v1/log/entries").mock(
        return_value=httpx.Response(
            201,
            json={
                "deadbeef-cafebabe-feed-face-1234567890ab": {
                    "logIndex": 99001,
                    "logID": "abc",
                    "integratedTime": 1714740000,
                }
            },
        )
    )
    result = sigstore.submit_to_rekor(event_id=event_id, config=cfg)
    assert result == "deadbeef-cafebabe-feed-face-1234567890ab"


@respx.mock
def test_submit_to_rekor_returns_none_on_5xx(cfg: Config):
    event_id, _ = _append_one(cfg)
    respx.post("https://rekor.example.test/api/v1/log/entries").mock(
        return_value=httpx.Response(503, text="bad")
    )
    assert sigstore.submit_to_rekor(event_id=event_id, config=cfg) is None


@respx.mock
def test_submit_signed_payload_returns_uuid_on_201(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("SMADP_REKOR_URL", "https://rekor.example.test")
    respx.post("https://rekor.example.test/api/v1/log/entries").mock(
        return_value=httpx.Response(
            201,
            json={"feed-face-uuid": {"logIndex": 12345, "integratedTime": 1714740000}},
        )
    )
    out = sigstore.submit_signed_payload(
        signing_input=b"hello",
        signature_hex="aabb",
        public_key_pem="-----BEGIN PUBLIC KEY-----\nABCD=\n-----END PUBLIC KEY-----",
    )
    assert out == "feed-face-uuid"


@respx.mock
def test_submit_signed_payload_returns_none_on_5xx(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SMADP_REKOR_URL", "https://rekor.example.test")
    respx.post("https://rekor.example.test/api/v1/log/entries").mock(
        return_value=httpx.Response(503, text="upstream down")
    )
    out = sigstore.submit_signed_payload(
        signing_input=b"hi", signature_hex="aa", public_key_pem="pem"
    )
    assert out is None


@respx.mock
def test_get_inclusion_proof_returns_proof_dict(cfg: Config):
    proof_payload = {
        "logIndex": 99001,
        "treeSize": 100000,
        "rootHash": "ab" * 32,
        "hashes": ["cd" * 32, "ef" * 32],
        "checkpoint": "rekor.example.test\n100000\n" + "ab" * 32 + "\n",
    }
    respx.get("https://rekor.example.test/api/v1/log/entries/uuid-123/proof").mock(
        return_value=httpx.Response(200, json=proof_payload)
    )
    out = sigstore.get_inclusion_proof("uuid-123", config=cfg)
    assert out == proof_payload


@respx.mock
def test_get_inclusion_proof_returns_none_on_404(cfg: Config):
    respx.get("https://rekor.example.test/api/v1/log/entries/missing/proof").mock(
        return_value=httpx.Response(404)
    )
    assert sigstore.get_inclusion_proof("missing", config=cfg) is None
