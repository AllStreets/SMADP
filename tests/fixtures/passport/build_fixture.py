"""Reusable passport fixture builder for golden + corpus tests.

Generates a deterministic passport against an in-memory workspace.
Returns the rendered bytes + the canonical inputs.
"""

from __future__ import annotations

from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from smadp.config import Config
from smadp.passport.render import render_passport
from smadp.schemas.passport import SigningStrategy
from smadp.schemas.tenancy import Plan
from smadp.tenancy import keys, store


def build_fixture_passport(cache_dir: Path, *, rendered_at: str = "2026-05-03T12:00:00Z") -> bytes:
    """Build a deterministic passport using the given cache_dir as state.

    Caller must ensure SMADP_CACHE_DIR + SMADP_KEK_MASTER are set in the env
    before calling this (so config + crypto resolve cleanly).
    """
    _ = cache_dir  # accepted for API symmetry; cfg picks up SMADP_CACHE_DIR
    cfg = Config()
    ws = store.create_workspace(name="Fixture", plan=Plan.PUBLIC, config=cfg)
    priv = Ed25519PrivateKey.generate()
    keys.upload_signing_key(workspace_id=ws.id, private_key=priv, config=cfg)
    return render_passport(
        verdict={
            "verdict_id": "vdt_FIXTURE",
            "pair": ["anthropic/claude", "openai/gpt"],
            "headline": "Fixture passport",
            "composite_score": 0.42,
            "framework_mappings": {"nist_ai_rmf": ["GOVERN-1.1", "MEASURE-2.3"]},
        },
        frameworks={"nist_ai_rmf": {"name": "NIST AI RMF", "version": "1.0"}},
        evidence_index={},
        evidence_blobs={},
        signing_strategy=SigningStrategy.BYOK,
        workspace_id=ws.id,
        rendered_at=rendered_at,
        config=cfg,
    )
