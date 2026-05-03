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
    a = journal.append_event(
        event_type="x.a", payload={}, signing_key=signing_key, config=cfg
    )
    b = journal.append_event(
        event_type="x.b", payload={}, signing_key=signing_key, config=cfg
    )
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
    ev_a = journal.append_event(
        event_type="x", payload={"a": 1, "b": 2}, signing_key=signing_key, config=cfg
    )
    ev_b = journal.append_event(
        event_type="x", payload={"b": 2, "a": 1}, signing_key=signing_key, config=cfg
    )
    sig_input_a = journal._canonical_signing_input(ev_a)
    sig_input_b = journal._canonical_signing_input(ev_b)
    assert journal._canonical_payload({"a": 1, "b": 2}) == journal._canonical_payload(
        {"b": 2, "a": 1}
    )
