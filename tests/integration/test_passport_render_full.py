"""Full render_passport integration: workspace + BYOK + journal + render."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from smadp.config import Config
from smadp.passport.render import render_passport
from smadp.schemas.passport import SigningStrategy
from smadp.schemas.tenancy import Plan
from smadp.tenancy import keys, store


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    monkeypatch.delenv("SMADP_SIGSTORE_ENABLED", raising=False)
    return Config()


@pytest.fixture
def workspace_with_key(cfg: Config) -> tuple[str, Ed25519PrivateKey]:
    ws = store.create_workspace(name="Acme", plan=Plan.PUBLIC, config=cfg)
    priv = Ed25519PrivateKey.generate()
    keys.upload_signing_key(workspace_id=ws.id, private_key=priv, config=cfg)
    return ws.id, priv


def _verdict():
    return {
        "verdict_id": "vdt_FULL",
        "pair": ["a/x", "b/y"],
        "headline": "Full render test",
        "composite_score": 0.5,
        "framework_mappings": {"nist_ai_rmf": ["GOVERN-1.1"]},
    }


def test_render_passport_byok_emits_signed_html(
    cfg: Config, workspace_with_key: tuple[str, Ed25519PrivateKey]
):
    ws_id, _ = workspace_with_key
    html = render_passport(
        verdict=_verdict(),
        frameworks={"nist_ai_rmf": {"name": "NIST AI RMF"}},
        evidence_index={},
        evidence_blobs={},
        signing_strategy=SigningStrategy.BYOK,
        workspace_id=ws_id,
        rendered_at="2026-05-03T12:00:00Z",
        config=cfg,
    )
    text = html.decode("utf-8")
    assert re.search(r'name="smadp-signature-hex" content="[0-9a-f]+"', text)
    assert re.search(r'name="smadp-public-key-hex" content="[0-9a-f]+"', text)
    assert 'name="smadp-signing-strategy" content="byok"' in text
    assert 'name="smadp-transparency-status" content="local"' in text
    assert re.search(r'name="smadp-transparency-event-id" content="\d+"', text)


def test_render_passport_byok_appends_transparency_event(
    cfg: Config, workspace_with_key: tuple[str, Ed25519PrivateKey]
):
    ws_id, _ = workspace_with_key
    from smadp.transparency import journal

    before = len(list(journal.iter_events(config=cfg)))
    render_passport(
        verdict=_verdict(),
        frameworks={},
        evidence_index={},
        evidence_blobs={},
        signing_strategy=SigningStrategy.BYOK,
        workspace_id=ws_id,
        rendered_at="2026-05-03T12:00:00Z",
        config=cfg,
    )
    after = list(journal.iter_events(config=cfg))
    assert len(after) == before + 1
    assert after[-1].event_type == "passport.generated"


def test_render_passport_byok_missing_key_raises(cfg: Config):
    ws = store.create_workspace(name="X", plan=Plan.PUBLIC, config=cfg)
    with pytest.raises(KeyError, match="byok_key_missing_for_workspace"):
        render_passport(
            verdict=_verdict(),
            frameworks={},
            evidence_index={},
            evidence_blobs={},
            signing_strategy=SigningStrategy.BYOK,
            workspace_id=ws.id,
            rendered_at="2026-05-03T12:00:00Z",
            config=cfg,
        )


def test_render_passport_embeds_canonical_payload_as_script_tag(
    cfg: Config, workspace_with_key: tuple[str, Ed25519PrivateKey]
):
    ws_id, _ = workspace_with_key
    html = render_passport(
        verdict=_verdict(),
        frameworks={"nist_ai_rmf": {"name": "NIST AI RMF"}},
        evidence_index={},
        evidence_blobs={},
        signing_strategy=SigningStrategy.BYOK,
        workspace_id=ws_id,
        rendered_at="2026-05-03T12:00:00Z",
        config=cfg,
    )
    text = html.decode("utf-8")
    m = re.search(
        r'<script type="application/json" id="smadp-passport-payload">(.+?)</script>',
        text,
        re.DOTALL,
    )
    assert m is not None
    payload = json.loads(m.group(1))
    assert payload["verdict"]["verdict_id"] == "vdt_FULL"
    assert payload["rendered_at"] == "2026-05-03T12:00:00Z"
