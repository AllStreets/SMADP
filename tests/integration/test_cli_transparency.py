"""Integration tests for the smadp transparency CLI."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from smadp.cli import cli
from smadp.config import Config
from smadp.transparency import journal


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    return Config()


def _write_pubkey(tmp_path: Path, key: Ed25519PrivateKey) -> Path:
    p = tmp_path / "pub.hex"
    pub_bytes = key.public_key().public_bytes(encoding=Encoding.Raw, format=PublicFormat.Raw)
    p.write_text(pub_bytes.hex())
    return p


def test_verify_command_passes_clean_log(tmp_path: Path, cfg: Config):
    key = Ed25519PrivateKey.generate()
    journal.append_event(event_type="x.a", payload={}, signing_key=key, config=cfg)
    journal.append_event(event_type="x.b", payload={}, signing_key=key, config=cfg)
    pub = _write_pubkey(tmp_path, key)

    runner = CliRunner()
    result = runner.invoke(cli, ["transparency", "verify", "--public-key", str(pub)])
    assert result.exit_code == 0
    assert "OK" in result.output


def test_verify_command_fails_tampered_log(tmp_path: Path, cfg: Config, monkeypatch):
    key = Ed25519PrivateKey.generate()
    journal.append_event(event_type="x.a", payload={}, signing_key=key, config=cfg)
    # Tamper:
    conn = journal._connect(cfg)
    try:
        conn.execute("UPDATE signed_events SET payload = ? WHERE id = 1", ('{"x":1}',))
        conn.commit()
    finally:
        conn.close()

    pub = _write_pubkey(tmp_path, key)
    runner = CliRunner()
    result = runner.invoke(cli, ["transparency", "verify", "--public-key", str(pub)])
    assert result.exit_code != 0
    assert "BREAK" in result.output or "invalid" in result.output.lower()


def test_verify_command_empty_log_passes(tmp_path: Path, cfg: Config):
    key = Ed25519PrivateKey.generate()
    pub = _write_pubkey(tmp_path, key)
    runner = CliRunner()
    result = runner.invoke(cli, ["transparency", "verify", "--public-key", str(pub)])
    assert result.exit_code == 0
