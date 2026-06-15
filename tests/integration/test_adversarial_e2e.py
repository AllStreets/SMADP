"""End-to-end adversarial sandbox pipeline (sandbox-marked, no LLMs).

Transplants the digest-pinned-alpine + synthetic-adapter setup from
``tests/sandbox/test_pipeline_synthetic.py`` and drives the built-in
``state_poisoning`` adversarial scenario: the containers echo the poison
marker, the deterministic property check confirms the attack
(``victim_output_contains``), the run grades ``fail``, and after promotion the
pending verdict's ``D_cascading_error`` is floored to >= high.

Skipped automatically when no usable container runtime is present.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from smadp.config import Config

pytestmark = pytest.mark.sandbox

POISON_MARKER = "synthetic-test-only-poison-marker-3c2"


def _container_runtime() -> str | None:
    if os.environ.get("GITHUB_ACTIONS") or os.environ.get("CI"):
        return None
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
_skip = pytest.mark.skipif(
    _RUNTIME is None,
    reason="container runtime not usable for full sandbox spec in this env",
)


def _alpine_digest() -> str:
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
    (cfg.catalog_dir / "pending").mkdir(parents=True, exist_ok=True)
    (cfg.catalog_dir / "_chronicle").mkdir(parents=True, exist_ok=True)
    cfg.cache_dir.mkdir(parents=True, exist_ok=True)
    return cfg


@_skip
@pytest.mark.asyncio
async def test_adversarial_state_poisoning_e2e(
    tmp_config: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from smadp.sandbox import binding as binding_mod
    from smadp.sandbox import queue as queue_mod
    from smadp.sandbox import runner as runner_mod
    from smadp.sandbox.promote import promote_from_run
    from smadp.sandbox.properties import PropertyReport
    from smadp.sandbox.runner import AdapterDescriptor, execute_run

    digest = _alpine_digest()

    # Approve the real alpine digest for both synthetic slugs (same path the
    # synthetic pipeline test uses).
    from smadp.sandbox import policy as policy_mod

    monkeypatch.setitem(policy_mod.APPROVED_IMAGES, "synthetic-adapter", digest)
    monkeypatch.setitem(policy_mod.APPROVED_IMAGES, "synthetic-adapter-2", digest)

    # Both containers echo the poison marker. The deterministic property check
    # is victim-scoped (victim_output_contains), so the victim echoing it is
    # what confirms the attack.
    echo_cmd = ("sh", "-c", f"echo {POISON_MARKER}; exit 0")

    def fake_caps(slug: str, *, config: Config | None = None) -> dict:
        return {
            "execute_shell": True,
            "read_filesystem": True,
            "write_filesystem": True,
            "network_egress": "none",
        }

    def fake_load_adapter(slug: str, *, config: Config) -> AdapterDescriptor:
        return AdapterDescriptor(
            slug=slug,
            transport="stdio",
            command=echo_cmd,
            env_required=(),
            image="alpine:3.20",
            image_digest_pinned=digest,
            capabilities={
                "execute_shell": True,
                "read_filesystem": True,
                "write_filesystem": True,
            },
            trust_floor=0.0,
        )

    monkeypatch.setattr(binding_mod, "load_adapter_capabilities", fake_caps)
    monkeypatch.setattr(queue_mod, "load_adapter_capabilities", fake_caps)
    monkeypatch.setattr(runner_mod, "load_adapter", fake_load_adapter)

    # In ``poison_shared_state`` the planted-asset value IS the marker the victim
    # must echo to confirm the attack, so with tripwires ``enabled`` the
    # planted-secret rule would halt the run before property grading declares
    # ``fail``. Run with tripwires ``log_only`` so the deterministic property
    # grade (the thing under test) stands; the tripwire is still recorded.
    from smadp.autopilot.config import AutopilotConfig

    monkeypatch.setattr(
        runner_mod,
        "load_autopilot_config",
        lambda _path: AutopilotConfig(tripwires="log_only"),
    )

    run_id = queue_mod.enqueue_sandbox_run(
        slug_a="synthetic-adapter",
        slug_b="synthetic-adapter-2",
        scenario="state_poisoning",
        config=tmp_config,
    )
    claimed = queue_mod.claim_next_pending(config=tmp_config)
    assert claimed is not None and claimed.run_id == run_id

    result = await execute_run(run_id, config=tmp_config)
    assert result.outcome == "fail"

    # The property report sidecar confirms the attack + objective.
    transcript_path = Path(queue_mod.get_raw_row(run_id, config=tmp_config)["transcript_path"])
    report = PropertyReport.from_json(
        (transcript_path.parent / "property-report.json").read_text(encoding="utf-8")
    )
    assert report.attack_succeeded is True
    assert report.objective == "poison_shared_state"

    # Promote: the floors bound the severity (poison_shared_state -> D >= high).
    promote_from_run(run_id, config=tmp_config)
    from smadp.catalog.repo import CatalogRepo

    pending = CatalogRepo(tmp_config).load_verdict(
        "synthetic-adapter", "synthetic-adapter-2", include_pending=True
    )
    assert pending.sub_verdicts.D_cascading_error.severity in {"high", "critical"}
    assert pending.sandbox_runs[-1].mode == "adversarial"
