"""Tests for the transparency log (signed-event journal)."""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from smadp.config import Config
from smadp.transparency import journal


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    return Config()


@pytest.fixture
def signing_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def test_append_event_returns_event_with_id(cfg: Config, signing_key):
    ev = journal.append_event(
        event_type="verdict.created",
        payload={"verdict_id": "vdt_x"},
        signing_key=signing_key,
        config=cfg,
    )
    assert ev.id == 1
    assert ev.event_type == "verdict.created"
    assert ev.signature  # hex-encoded


def test_append_event_chain_links_prev_hash(cfg: Config, signing_key):
    a = journal.append_event(event_type="x.a", payload={}, signing_key=signing_key, config=cfg)
    b = journal.append_event(event_type="x.b", payload={}, signing_key=signing_key, config=cfg)
    assert a.prev_hash == "sha256:" + "0" * 64  # genesis
    expected = journal._hash_signature(a.signature)
    assert b.prev_hash == expected


def test_append_event_signature_verifies(cfg: Config, signing_key):
    ev = journal.append_event(
        event_type="x.a", payload={"k": 1}, signing_key=signing_key, config=cfg
    )
    pub = signing_key.public_key()
    pub.verify(
        bytes.fromhex(ev.signature),
        journal._canonical_signing_input(ev),
    )  # raises on bad signature


def test_payload_canonicalization_is_stable(cfg: Config, signing_key):
    journal.append_event(
        event_type="x", payload={"a": 1, "b": 2}, signing_key=signing_key, config=cfg
    )
    journal.append_event(
        event_type="x", payload={"b": 2, "a": 1}, signing_key=signing_key, config=cfg
    )
    assert journal._canonical_payload({"a": 1, "b": 2}) == journal._canonical_payload(
        {"b": 2, "a": 1}
    )


def test_verify_chain_passes_on_clean_log(cfg: Config, signing_key):
    journal.append_event(event_type="x.a", payload={"k": 1}, signing_key=signing_key, config=cfg)
    journal.append_event(event_type="x.b", payload={"k": 2}, signing_key=signing_key, config=cfg)
    journal.append_event(event_type="x.c", payload={"k": 3}, signing_key=signing_key, config=cfg)
    result = journal.verify_chain(public_key=signing_key.public_key(), config=cfg)
    assert result.valid is True
    assert result.first_break is None


def test_verify_chain_detects_payload_tamper(cfg: Config, signing_key):
    journal.append_event(event_type="x.a", payload={"k": 1}, signing_key=signing_key, config=cfg)
    journal.append_event(event_type="x.b", payload={"k": 2}, signing_key=signing_key, config=cfg)
    # Corrupt row 1's payload directly.
    conn = journal._connect(cfg)
    try:
        conn.execute("UPDATE signed_events SET payload = ? WHERE id = 1", ('{"k":99}',))
    finally:
        conn.close()
    result = journal.verify_chain(public_key=signing_key.public_key(), config=cfg)
    assert result.valid is False
    assert result.first_break == 1
    assert "signature" in result.reason.lower()


def test_verify_chain_detects_prev_hash_break(cfg: Config, signing_key):
    journal.append_event(event_type="x.a", payload={}, signing_key=signing_key, config=cfg)
    journal.append_event(event_type="x.b", payload={}, signing_key=signing_key, config=cfg)
    conn = journal._connect(cfg)
    try:
        conn.execute(
            "UPDATE signed_events SET prev_hash = ? WHERE id = 2",
            ("sha256:" + "f" * 64,),
        )
    finally:
        conn.close()
    result = journal.verify_chain(public_key=signing_key.public_key(), config=cfg)
    assert result.valid is False
    assert result.first_break == 2
    assert "prev_hash" in result.reason.lower()


def test_verify_chain_handles_empty_log(cfg: Config, signing_key):
    result = journal.verify_chain(public_key=signing_key.public_key(), config=cfg)
    assert result.valid is True


def test_iter_events(cfg: Config, signing_key):
    journal.append_event(event_type="x.a", payload={"k": 1}, signing_key=signing_key, config=cfg)
    journal.append_event(event_type="x.b", payload={"k": 2}, signing_key=signing_key, config=cfg)
    rows = list(journal.iter_events(config=cfg))
    assert len(rows) == 2
    assert [r.event_type for r in rows] == ["x.a", "x.b"]
