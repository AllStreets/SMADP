"""End-to-end pipeline test using a tiny alpine-based adapter (no LLMs)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from smadp.config import Config


def _container_runtime() -> str | None:
    for name in ("docker", "podman"):
        if shutil.which(name):
            try:
                proc = subprocess.run([name, "info"], capture_output=True, timeout=5)
            except (subprocess.TimeoutExpired, OSError):
                continue
            if proc.returncode == 0:
                return name
    return None


_RUNTIME = _container_runtime()
pytestmark = pytest.mark.skipif(_RUNTIME is None, reason="docker/podman not available")


def _alpine_digest() -> str:
    """Pull alpine:3.20 and return its docker.io/library/alpine@sha256:... digest."""
    assert _RUNTIME is not None
    subprocess.run([_RUNTIME, "pull", "alpine:3.20"], check=True, capture_output=True)
    out = subprocess.run(
        [_RUNTIME, "inspect", "--format={{json .RepoDigests}}", "alpine:3.20"],
        check=True,
        capture_output=True,
        text=True,
    )
    digests = json.loads(out.stdout.strip())
    for d in digests:
        if "alpine" in d:
            return f"docker.io/library/{d.split('/')[-1]}"
    raise RuntimeError(f"no alpine digest in {digests}")


@pytest.fixture
def tmp_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    catalog = tmp_path / "catalog"
    cache = tmp_path / "cache"
    catalog.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SMADP_CATALOG", str(catalog))
    monkeypatch.setenv("SMADP_CACHE_DIR", str(cache))
    cfg = Config()
    (cfg.catalog_dir / "verdicts").mkdir(parents=True, exist_ok=True)
    (cfg.catalog_dir / "_chronicle").mkdir(parents=True, exist_ok=True)
    cfg.cache_dir.mkdir(parents=True, exist_ok=True)
    return cfg


@pytest.mark.asyncio
async def test_synthetic_pipeline_promotes_verdict(
    tmp_config: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stage a synthetic adapter+scenario, enqueue, run the worker, expect promotion."""
    fixtures = Path(__file__).parent / "fixtures"

    # Stage two copies of the synthetic adapter under a tmp adapters root so the
    # runner has a valid pair (slug_a != slug_b).
    adapters_root = tmp_path / "adapters"
    adapters_root.mkdir()
    shutil.copytree(fixtures / "synthetic_adapter", adapters_root / "synthetic-adapter")
    shutil.copytree(fixtures / "synthetic_adapter", adapters_root / "synthetic-adapter-2")
    mcp2 = adapters_root / "synthetic-adapter-2" / "mcp.json"
    raw = mcp2.read_text(encoding="utf-8").replace("synthetic-adapter", "synthetic-adapter-2")
    mcp2.write_text(raw, encoding="utf-8")

    # Inject the real alpine digest into the policy allowlist for both slugs.
    digest = _alpine_digest()
    from smadp.sandbox import policy as policy_mod

    monkeypatch.setitem(policy_mod.APPROVED_IMAGES, "synthetic-adapter", digest)
    monkeypatch.setitem(policy_mod.APPROVED_IMAGES, "synthetic-adapter-2", digest)

    # Point the scenarios loader at our fixtures dir so load_scenario("synthetic_scenario") works.
    from smadp.sandbox.scenarios import loader as scenarios_loader

    monkeypatch.setattr(scenarios_loader, "_BUILTIN_DIR", fixtures)

    # Pre-author a stub verdict so promote can mutate it.
    from smadp.catalog.repo import CatalogRepo
    from smadp.schemas.verdict import Verdict

    zero_hash = "sha256:" + "0" * 64
    sub = {
        "severity": "low",
        "rationale": "placeholder rationale that is non-empty",
        "citations": [{"profile_field": "name"}],
        "conditions": [],
        "mitigations": [],
    }
    verdict = Verdict.model_validate(
        {
            "schema_version": "1.0",
            "verdict_id": "v_2026-05-04_synthetic-adapter__synthetic-adapter-2_abc1",
            "pair": ("synthetic-adapter", "synthetic-adapter-2"),
            "generated_at": "2026-05-04T00:00:00Z",
            "model": {
                "name": "claude-opus-4-7",
                "id": "claude-opus-4-7",
                "rubric_version": "1.0",
            },
            "evidence_level": "docs-only",
            "confidence": 0.6,
            "composite_score": 0.5,
            "headline": "Synthetic stub for integration test.",
            "sub_verdicts": {
                "A_prompt_injection": sub,
                "B_data_leakage": sub,
                "C_capability_conflict": sub,
                "D_cascading_error": sub,
                "E_compliance": sub,
            },
            "framework_mappings": {},
            "reproducibility": {
                "rubric_url": "/_meta/rubric/1.0.json",
                "profile_a_hash": zero_hash,
                "profile_b_hash": zero_hash,
                "evidence_bundle_hash": zero_hash,
            },
            "sandbox_runs": [],
        }
    )
    CatalogRepo(tmp_config).save_verdict(verdict)

    # Redirect adapter loading to the tmp adapters_root.
    from smadp.sandbox import binding as binding_mod
    from smadp.sandbox import queue as queue_mod
    from smadp.sandbox import runner as runner_mod
    from smadp.sandbox import worker as worker_mod

    def fake_caps(slug: str, *, config: Config | None = None) -> dict:
        return json.loads((adapters_root / slug / "mcp.json").read_text(encoding="utf-8"))[
            "capabilities"
        ]

    monkeypatch.setattr(binding_mod, "load_adapter_capabilities", fake_caps)
    monkeypatch.setattr(queue_mod, "load_adapter_capabilities", fake_caps)
    monkeypatch.setattr(
        runner_mod,
        "load_adapter",
        lambda slug, *, config: runner_mod._load_adapter_from_root(slug, root=adapters_root),
    )
    monkeypatch.setattr(
        worker_mod,
        "_load_keys_for_run",
        lambda *a, **kw: ({}, []),
    )

    run_id = queue_mod.enqueue_sandbox_run(
        slug_a="synthetic-adapter",
        slug_b="synthetic-adapter-2",
        scenario="synthetic_scenario",
        config=tmp_config,
    )

    summary = await worker_mod.run_worker(
        once=True,
        max_runs=None,
        scenario_filter=None,
        config=tmp_config,
        keys_path=tmp_path / "keys.env",
    )
    assert summary.runs_completed == 1
    assert summary.runs_failed == 0

    persisted = CatalogRepo(tmp_config).load_verdict("synthetic-adapter", "synthetic-adapter-2")
    assert persisted.evidence_level == "sandbox-validated"
    assert any(sr.run_id == run_id for sr in persisted.sandbox_runs)
