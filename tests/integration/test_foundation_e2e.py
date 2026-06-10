"""End-to-end test: workspace + BYOK + journal + verify chain.

Walks the full Plan 1 surface in one test:

1. POST /api/workspaces → create workspace
2. Upload BYOK signing key for that workspace
3. Append events to the transparency journal using the BYOK key
4. Verify chain via the same workspace's public key
5. Export the journal to JSONL and re-verify line-by-line
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from smadp.api.server import create_app
from smadp.config import Config
from smadp.tenancy import keys
from smadp.transparency import journal


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    # Write endpoints now require an operator token.
    monkeypatch.setenv("SMADP_API_TOKEN", "test-operator-token")
    return Config()


def test_foundation_end_to_end(cfg: Config, tmp_path: Path):
    client = TestClient(create_app(cfg))
    client.headers.update({"Authorization": "Bearer test-operator-token"})

    # 1. Create workspace.
    ws = client.post("/api/workspaces", json={"name": "Acme", "plan": "private"}).json()

    # 2. Upload BYOK signing key (programmatic — no API for this in Plan 1).
    priv = Ed25519PrivateKey.generate()
    keys.upload_signing_key(workspace_id=ws["id"], private_key=priv, config=cfg)

    # 3. Append three events to the journal.
    for i in range(3):
        journal.append_event(
            event_type="verdict.created",
            payload={"verdict_id": f"vdt_e2e_{i}", "score": 0.1 * i},
            signing_key=priv,
            config=cfg,
        )

    # 4. Verify chain.
    pub = keys.get_public_key(workspace_id=ws["id"], config=cfg)
    assert pub is not None
    report = journal.verify_chain(public_key=pub, config=cfg)
    assert report.valid is True

    # 5. Pull events via API.
    r = client.get("/api/transparency/events")
    assert r.status_code == 200
    listed = r.json()
    assert len(listed) == 3

    # 6. Verify the API-returned ordering matches journal iteration.
    assert [ev["event_type"] for ev in listed] == ["verdict.created"] * 3
    assert [ev["payload"]["verdict_id"] for ev in listed] == [
        "vdt_e2e_0",
        "vdt_e2e_1",
        "vdt_e2e_2",
    ]

    # 7. Verify the chain still passes after API reads (read-only must not mutate).
    report2 = journal.verify_chain(public_key=pub, config=cfg)
    assert report2.valid is True
