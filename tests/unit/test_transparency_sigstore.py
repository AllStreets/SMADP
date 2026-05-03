"""Tests for sigstore deferred-submission stub."""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from smadp.config import Config
from smadp.transparency import journal, sigstore


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    return Config()


@pytest.fixture
def key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def test_submit_to_rekor_stub_returns_none(cfg: Config, key):
    ev = journal.append_event(event_type="x", payload={}, signing_key=key, config=cfg)
    result = sigstore.submit_to_rekor(event_id=ev.id, config=cfg)
    assert result is None  # stub: real submission deferred


def test_pending_submissions_lists_unsubmitted(cfg: Config, key):
    ev1 = journal.append_event(event_type="x", payload={}, signing_key=key, config=cfg)
    ev2 = journal.append_event(event_type="y", payload={}, signing_key=key, config=cfg)
    pending = sigstore.list_pending_submissions(config=cfg)
    assert {p.id for p in pending} == {ev1.id, ev2.id}


def test_mark_submitted_clears_pending(cfg: Config, key):
    ev = journal.append_event(event_type="x", payload={}, signing_key=key, config=cfg)
    sigstore.mark_submitted(event_id=ev.id, rekor_uuid="rkr_test_uuid", config=cfg)
    pending = sigstore.list_pending_submissions(config=cfg)
    assert all(p.id != ev.id for p in pending)


def test_retry_pending_calls_submit_per_row(cfg: Config, key, monkeypatch):
    journal.append_event(event_type="x", payload={}, signing_key=key, config=cfg)
    journal.append_event(event_type="y", payload={}, signing_key=key, config=cfg)

    calls: list[int] = []

    def fake_submit(*, event_id: int, config=None) -> str | None:
        calls.append(event_id)
        return f"rkr_{event_id}"

    monkeypatch.setattr(sigstore, "submit_to_rekor", fake_submit)
    sigstore.retry_pending_submissions(config=cfg)
    assert sorted(calls) == [1, 2]
    assert sigstore.list_pending_submissions(config=cfg) == []
