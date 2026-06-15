"""Recording sessions content-address redacted messages and honor the kill switch."""

from __future__ import annotations

from pathlib import Path

from smadp.proxy.recorder import RecordingSession


def _messages_blob(rec_path: Path) -> dict:
    import json

    return json.loads(rec_path.read_text("utf-8"))


def test_observe_then_finalize_writes_content_addressed_evidence(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "_evidence"
    session = RecordingSession(slug="acme-agent", evidence_dir=evidence_dir)
    session.observe(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        direction="c2s",
    )
    session.observe(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "http_get",
                "arguments": {"token": "sk-ABCDEFGHIJKLMNOPQRSTUV"},
            },
        },
        direction="c2s",
    )
    rec = session.finalize()

    assert rec.message_count == 2
    assert rec.path.exists()
    assert rec.path.name == f"sha256-{rec.sha256}.json"

    blob = _messages_blob(rec.path)
    assert blob["kind"] == "mcp-recording"
    assert blob["slug"] == "acme-agent"
    # secret redacted, not persisted
    serialized = rec.path.read_text("utf-8")
    assert "sk-ABCDEFGHIJKLMNOPQRSTUV" not in serialized
    assert "***REDACTED***" in serialized
    # content-stable hash
    assert rec.sha256 == RecordingSession.sha_for(blob["messages"])


def test_is_disabled_reflects_kill_switch(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    assert RecordingSession.is_disabled(state_dir=state_dir) is False
    (state_dir / "PROXY_DISABLED").write_text("", encoding="utf-8")
    assert RecordingSession.is_disabled(state_dir=state_dir) is True
