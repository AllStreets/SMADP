"""Verdict promotion: turn a completed sandbox run into a verdict mutation."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from smadp.catalog.repo import CatalogRepo
from smadp.config import Config
from smadp.sandbox import promote, queue
from smadp.schemas.verdict import Verdict
from smadp.utils.time import utcnow


@pytest.fixture
def tmp_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    catalog = tmp_path / "catalog"
    cache = tmp_path / "cache"
    catalog.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SMADP_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("SMADP_CATALOG", str(catalog))
    monkeypatch.setenv("SMADP_CACHE_DIR", str(cache))

    # Copy adapter mcp.json files so the capability-based binder in
    # queue.enqueue_sandbox_run can resolve adapter capabilities from
    # the (isolated) repo_root.
    real_repo = Path(__file__).resolve().parents[2]
    (tmp_path / "adapters").mkdir(exist_ok=True)
    for slug in ("aider", "continue-dev"):
        src = real_repo / "adapters" / slug / "mcp.json"
        if src.exists():
            dst_dir = tmp_path / "adapters" / slug
            dst_dir.mkdir(exist_ok=True)
            (dst_dir / "mcp.json").write_text(src.read_text())

    cfg = Config()
    (cfg.catalog_dir / "verdicts").mkdir(parents=True, exist_ok=True)
    (cfg.catalog_dir / "_chronicle").mkdir(parents=True, exist_ok=True)
    cfg.cache_dir.mkdir(parents=True, exist_ok=True)
    return cfg


_ZERO_HASH = "sha256:" + "0" * 64


def _stub_subverdict(severity: str = "low") -> dict:
    return {
        "severity": severity,
        "rationale": "placeholder rationale that is non-empty",
        "citations": [{"profile_field": "name"}],
        "conditions": [],
        "mitigations": [],
    }


def _stub_verdict(slug_a: str = "aider", slug_b: str = "continue-dev") -> Verdict:
    return Verdict.model_validate(
        {
            "schema_version": "1.0",
            "verdict_id": f"v_2026-05-04_{slug_a}__{slug_b}_abc1",
            "pair": (slug_a, slug_b),
            "generated_at": "2026-05-04T00:00:00Z",
            "model": {
                "name": "claude-opus-4-7",
                "id": "claude-opus-4-7",
                "rubric_version": "1.0",
            },
            "evidence_level": "docs-only",
            "confidence": 0.6,
            "composite_score": 0.5,
            "headline": "Compatible for read-only handoff.",
            "sub_verdicts": {
                "A_prompt_injection": _stub_subverdict("low"),
                "B_data_leakage": _stub_subverdict("low"),
                "C_capability_conflict": _stub_subverdict("none"),
                "D_cascading_error": _stub_subverdict("low"),
                "E_compliance": _stub_subverdict("none"),
            },
            "framework_mappings": {},
            "reproducibility": {
                "rubric_url": "/_meta/rubric/1.0.json",
                "profile_a_hash": _ZERO_HASH,
                "profile_b_hash": _ZERO_HASH,
                "evidence_bundle_hash": _ZERO_HASH,
            },
            "sandbox_runs": [],
        }
    )


def _seed_completed_run(
    cfg: Config,
    *,
    outcome: str,
    transcript_events: list[dict] | None = None,
    slug_a: str = "aider",
    slug_b: str = "continue-dev",
) -> tuple[str, Path]:
    run_id = queue.enqueue_sandbox_run(
        slug_a=slug_a, slug_b=slug_b, scenario="calendar_email", config=cfg
    )
    transcript_dir = cfg.cache_dir / "transcripts" / run_id
    transcript_dir.mkdir(parents=True, exist_ok=True)
    transcript = transcript_dir / "transcript.jsonl"
    lines = [json.dumps(ev) for ev in (transcript_events or [])]
    transcript.write_text(("\n".join(lines) + "\n") if lines else "", encoding="utf-8")
    queue.mark_completed(run_id, outcome=outcome, transcript_path=str(transcript), config=cfg)
    return run_id, transcript


def _seed_completed_nary_run(
    cfg: Config,
    *,
    run_id: str,
    participants: list[dict[str, str]],
    outcome: str,
    scenario: str,
    transcript_events: list[dict] | None = None,
) -> Path:
    """Seed a completed N-ary queue row directly via SQLite.

    Bypasses ``enqueue_sandbox_run`` because that function validates the
    scenario against the built-in registry and enforces 2-agent pair
    canonicalization. For tests covering first-time N-ary verdict routing we
    need to short-circuit both: the spec exercises a scenario that does not
    yet exist on disk (Task 5 will add ``code_review_chain``) and three
    participating agents.
    """
    cfg.cache_dir.mkdir(parents=True, exist_ok=True)
    transcript_dir = cfg.cache_dir / "transcripts" / run_id
    transcript_dir.mkdir(parents=True, exist_ok=True)
    transcript = transcript_dir / "transcript.jsonl"
    lines = [json.dumps(ev) for ev in (transcript_events or [])]
    transcript.write_text(("\n".join(lines) + "\n") if lines else "", encoding="utf-8")

    sorted_p = sorted(participants, key=lambda p: p["slug"])
    slug_a = sorted_p[0]["slug"]
    slug_b = sorted_p[1]["slug"] if len(sorted_p) > 1 else sorted_p[0]["slug"]
    role_a = sorted_p[0]["role"]
    role_b = sorted_p[1]["role"] if len(sorted_p) > 1 else sorted_p[0]["role"]
    participants_json = json.dumps(sorted_p, separators=(",", ":"))
    now_iso = utcnow().isoformat(timespec="seconds").replace("+00:00", "Z")

    db_path = cfg.cache_dir / "sandbox-queue.db"
    conn = sqlite3.connect(db_path, isolation_level=None, timeout=30)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                slug_a TEXT NOT NULL,
                slug_b TEXT NOT NULL,
                scenario TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('pending','running','completed','failed')),
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                transcript_path TEXT,
                outcome TEXT,
                error TEXT,
                role_a TEXT,
                role_b TEXT,
                participants_json TEXT
            );
            """
        )
        # Tolerate older table layouts in case a previous test created the DB.
        cur = conn.execute("PRAGMA table_info(runs)")
        existing_cols = {row[1] for row in cur.fetchall()}
        for col in ("role_a", "role_b", "participants_json"):
            if col not in existing_cols:
                conn.execute(f"ALTER TABLE runs ADD COLUMN {col} TEXT")
        conn.execute(
            "INSERT INTO runs(id, slug_a, slug_b, scenario, state, created_at, "
            "started_at, completed_at, transcript_path, outcome, role_a, role_b, "
            "participants_json) VALUES (?, ?, ?, ?, 'completed', ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                slug_a,
                slug_b,
                scenario,
                now_iso,
                now_iso,
                now_iso,
                str(transcript),
                outcome,
                role_a,
                role_b,
                participants_json,
            ),
        )
    finally:
        conn.close()
    return transcript


def _seed_existing_verdict_nary(cfg: Config, *, participants: list[str]) -> Verdict:
    """Persist a published verdict for an N-ary combination via the repo."""
    sorted_p = sorted(participants)
    payload = {
        "schema_version": "1.0",
        "verdict_id": f"v_2026-05-04_{sorted_p[0]}__{sorted_p[-1]}_dead",
        "participants": sorted_p,
        "generated_at": "2026-05-04T00:00:00Z",
        "model": {
            "name": "claude-opus-4-7",
            "id": "claude-opus-4-7",
            "rubric_version": "1.0",
        },
        "evidence_level": "docs-only",
        "confidence": 0.6,
        "composite_score": 0.5,
        "headline": "Existing N-ary verdict for regression test.",
        "sub_verdicts": {
            "A_prompt_injection": _stub_subverdict("low"),
            "B_data_leakage": _stub_subverdict("low"),
            "C_capability_conflict": _stub_subverdict("none"),
            "D_cascading_error": _stub_subverdict("low"),
            "E_compliance": _stub_subverdict("none"),
        },
        "framework_mappings": {},
        "reproducibility": {
            "rubric_url": "/_meta/rubric/1.0.json",
            "profile_a_hash": _ZERO_HASH,
            "profile_b_hash": _ZERO_HASH,
            "evidence_bundle_hash": _ZERO_HASH,
        },
        "sandbox_runs": [],
    }
    verdict = Verdict.model_validate(payload)
    CatalogRepo(cfg).save_verdict(verdict)
    return verdict


def test_pass_promotes_evidence_level(tmp_config: Config) -> None:
    repo = CatalogRepo(tmp_config)
    verdict = _stub_verdict()
    repo.save_verdict(verdict)
    run_id, _ = _seed_completed_run(tmp_config, outcome="pass")

    result = promote.promote_from_run(run_id, config=tmp_config)

    assert result.evidence_level_changed_to == "sandbox-validated"
    assert result.severity_bumps == {}
    persisted = repo.load_verdict("aider", "continue-dev")
    assert persisted.evidence_level == "sandbox-validated"
    assert len(persisted.sandbox_runs) == 1
    assert persisted.sandbox_runs[0].run_id == run_id
    assert persisted.sandbox_runs[0].outcome == "pass"


def test_promote_resigns_mutated_verdict(
    tmp_config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Promotion mutates the published verdict, so its detached BYOK signature
    must be refreshed to match the new content."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from smadp.autopilot.pending import PUBLISHER_WORKSPACE_ID, ensure_publisher_workspace
    from smadp.passport.publish_sign import verify_verdict_signature
    from smadp.tenancy import keys

    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    ensure_publisher_workspace(config=tmp_config)
    keys.upload_signing_key(
        workspace_id=PUBLISHER_WORKSPACE_ID,
        private_key=Ed25519PrivateKey.generate(),
        config=tmp_config,
    )
    repo = CatalogRepo(tmp_config)
    repo.save_verdict(_stub_verdict())
    run_id, _ = _seed_completed_run(tmp_config, outcome="pass")

    promote.promote_from_run(run_id, config=tmp_config)

    saved = repo.verdict_path("aider", "continue-dev")
    sidecar = saved.with_name(saved.stem + ".sig.json")
    assert sidecar.exists(), "promotion must write/refresh the signature sidecar"
    verdict_doc = json.loads(saved.read_text("utf-8"))
    sidecar_doc = json.loads(sidecar.read_text("utf-8"))
    assert verify_verdict_signature(verdict_doc, sidecar_doc)


def test_pass_does_not_downgrade_existing_validated_level(tmp_config: Config) -> None:
    repo = CatalogRepo(tmp_config)
    verdict = _stub_verdict()
    verdict = verdict.model_copy(update={"evidence_level": "sandbox-validated"})
    repo.save_verdict(verdict)
    run_id, _ = _seed_completed_run(tmp_config, outcome="pass")

    result = promote.promote_from_run(run_id, config=tmp_config)
    assert result.evidence_level_changed_to is None  # already at top of ladder


def test_fail_with_egress_violation_bumps_b(tmp_config: Config) -> None:
    repo = CatalogRepo(tmp_config)
    repo.save_verdict(_stub_verdict())
    events = [
        {
            "agent": "runner",
            "event_type": "policy_violation",
            "payload": {"kind": "egress_outside_allowlist", "detail": "evil.com"},
        },
    ]
    run_id, transcript = _seed_completed_run(tmp_config, outcome="fail", transcript_events=events)

    result = promote.promote_from_run(run_id, config=tmp_config)
    persisted = repo.load_verdict("aider", "continue-dev")

    assert result.evidence_level_changed_to is None
    assert result.severity_bumps == {"B_data_leakage": ("low", "medium")}
    assert persisted.sub_verdicts.B_data_leakage.severity == "medium"
    # A new citation was appended whose evidence_ref is the sha256 of the transcript.
    sha = hashlib.sha256(transcript.read_bytes()).hexdigest()
    new_citations = [
        c
        for c in persisted.sub_verdicts.B_data_leakage.citations
        if c.evidence_ref == f"sha256:{sha}"
    ]
    assert len(new_citations) == 1
    assert run_id in (new_citations[0].quote or "")
    assert "egress_outside_allowlist" in (new_citations[0].quote or "")


def test_fail_with_cross_role_write_bumps_c(tmp_config: Config) -> None:
    repo = CatalogRepo(tmp_config)
    repo.save_verdict(_stub_verdict())
    events = [
        {
            "agent": "runner",
            "event_type": "policy_violation",
            "payload": {
                "kind": "cross_role_filesystem_write",
                "detail": "/work/notes/x",
            },
        },
    ]
    run_id, _ = _seed_completed_run(tmp_config, outcome="fail", transcript_events=events)

    result = promote.promote_from_run(run_id, config=tmp_config)
    assert result.severity_bumps == {"C_capability_conflict": ("none", "low")}


def test_fail_caps_at_critical(tmp_config: Config) -> None:
    repo = CatalogRepo(tmp_config)
    v = _stub_verdict()
    bumped = v.sub_verdicts.B_data_leakage.model_copy(update={"severity": "critical"})
    new_subs = v.sub_verdicts.model_copy(update={"B_data_leakage": bumped})
    repo.save_verdict(v.model_copy(update={"sub_verdicts": new_subs}))
    events = [
        {
            "agent": "runner",
            "event_type": "policy_violation",
            "payload": {"kind": "egress_outside_allowlist", "detail": "evil.com"},
        },
    ]
    run_id, _ = _seed_completed_run(tmp_config, outcome="fail", transcript_events=events)

    result = promote.promote_from_run(run_id, config=tmp_config)
    assert result.severity_bumps == {}  # already at critical


def test_inconclusive_records_run_and_does_nothing_else(tmp_config: Config) -> None:
    repo = CatalogRepo(tmp_config)
    repo.save_verdict(_stub_verdict())
    run_id, _ = _seed_completed_run(tmp_config, outcome="inconclusive")

    result = promote.promote_from_run(run_id, config=tmp_config)
    persisted = repo.load_verdict("aider", "continue-dev")

    assert result.evidence_level_changed_to is None
    assert result.severity_bumps == {}
    assert len(persisted.sandbox_runs) == 1


def test_missing_verdict_lands_in_pending(tmp_config: Config) -> None:
    """First-time pair (no existing verdict file) seeds into catalog/pending/.

    Previously this raised ``VerdictMissingError``; under the autonomous-growth
    routing change (Task 4) we instead create a placeholder verdict and route
    it to pending/ for human review.
    """
    run_id, _ = _seed_completed_run(tmp_config, outcome="pass")

    result = promote.promote_from_run(run_id, config=tmp_config)

    pending = tmp_config.pending_dir / "aider__continue-dev.json"
    verdicts = tmp_config.verdicts_dir / "aider__continue-dev.json"
    assert pending.exists(), "first-time verdict should land in pending/"
    assert not verdicts.exists(), "first-time verdict should NOT land in verdicts/"
    assert result.sandbox_run_appended is True


def test_non_completed_run_refused(tmp_config: Config) -> None:
    run_id = queue.enqueue_sandbox_run(
        slug_a="aider",
        slug_b="continue-dev",
        scenario="calendar_email",
        config=tmp_config,
    )
    with pytest.raises(promote.RunNotCompletedError):
        promote.promote_from_run(run_id, config=tmp_config)


# ---------------------------------------------------------------------------
# Autopilot Task 4: first-time routing to catalog/pending/.
# ---------------------------------------------------------------------------


def test_promote_first_time_writes_pending(tmp_config: Config) -> None:
    """When no verdict file exists for the participants, first run lands in pending/."""
    _seed_completed_nary_run(
        tmp_config,
        run_id="run-first-time-3",
        participants=[
            {"role": "planner", "slug": "alice"},
            {"role": "executor", "slug": "bob"},
            {"role": "reviewer", "slug": "carol"},
        ],
        outcome="pass",
        scenario="code_review_chain",
    )

    result = promote.promote_from_run("run-first-time-3", config=tmp_config)

    pending = tmp_config.pending_dir / "alice__bob__carol.json"
    verdicts = tmp_config.verdicts_dir / "alice__bob__carol.json"
    assert pending.exists(), "first-time verdict should land in pending/"
    assert not verdicts.exists(), "first-time verdict should NOT land in verdicts/"
    assert result.sandbox_run_appended is True

    # The seeded skeleton starts at unverified-profile; a passing run should
    # have promoted it up the ladder to sandbox-validated.
    persisted = Verdict.model_validate_json(pending.read_text("utf-8"))
    assert persisted.evidence_level == "sandbox-validated"
    assert persisted.participants == ["alice", "bob", "carol"]
    assert len(persisted.sandbox_runs) == 1


def test_promote_re_run_mutates_existing_verdict(tmp_config: Config) -> None:
    """When verdicts/<key>.json already exists, subsequent runs mutate it."""
    _seed_existing_verdict_nary(tmp_config, participants=["alice", "bob", "carol"])
    _seed_completed_nary_run(
        tmp_config,
        run_id="run-second",
        participants=[
            {"role": "planner", "slug": "alice"},
            {"role": "executor", "slug": "bob"},
            {"role": "reviewer", "slug": "carol"},
        ],
        outcome="pass",
        scenario="code_review_chain",
    )

    result = promote.promote_from_run("run-second", config=tmp_config)

    verdicts = tmp_config.verdicts_dir / "alice__bob__carol.json"
    pending = tmp_config.pending_dir / "alice__bob__carol.json"
    assert verdicts.exists()
    assert not pending.exists()
    assert result.sandbox_run_appended is True


def test_promote_pending_rerun_mutates_pending(tmp_config: Config) -> None:
    """A second run on a still-pending verdict keeps mutating the pending file."""
    # First run: seeds the pending verdict.
    _seed_completed_nary_run(
        tmp_config,
        run_id="run-first",
        participants=[
            {"role": "planner", "slug": "alice"},
            {"role": "executor", "slug": "bob"},
            {"role": "reviewer", "slug": "carol"},
        ],
        outcome="pass",
        scenario="code_review_chain",
    )
    promote.promote_from_run("run-first", config=tmp_config)
    pending_path = tmp_config.pending_dir / "alice__bob__carol.json"
    assert pending_path.exists()

    # Second run: pending exists, verdicts/ still does not — should mutate pending.
    _seed_completed_nary_run(
        tmp_config,
        run_id="run-second-pending",
        participants=[
            {"role": "planner", "slug": "alice"},
            {"role": "executor", "slug": "bob"},
            {"role": "reviewer", "slug": "carol"},
        ],
        outcome="pass",
        scenario="code_review_chain",
    )
    promote.promote_from_run("run-second-pending", config=tmp_config)

    persisted = Verdict.model_validate_json(pending_path.read_text("utf-8"))
    assert len(persisted.sandbox_runs) == 2
    assert not (tmp_config.verdicts_dir / "alice__bob__carol.json").exists()


def test_promote_to_published_touches_rebuild_sentinel(
    tmp_config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A mutation that lands in catalog/verdicts/ calls _touch_rebuild_request.

    We intercept the helper to avoid writing into the dev tree's ``report/``
    directory during tests; the contract under test is that promote.py calls
    it for published-verdict writes.
    """
    calls: list[Config] = []
    monkeypatch.setattr(promote, "_touch_rebuild_request", lambda cfg: calls.append(cfg))

    repo = CatalogRepo(tmp_config)
    repo.save_verdict(_stub_verdict())
    run_id, _ = _seed_completed_run(tmp_config, outcome="pass")

    promote.promote_from_run(run_id, config=tmp_config)

    assert len(calls) == 1, "publishing into verdicts/ must touch the rebuild sentinel"
    assert calls[0] is tmp_config


def test_promote_to_pending_does_not_touch_rebuild_sentinel(
    tmp_config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """First-time routing to pending/ must NOT trigger a site rebuild."""
    calls: list[Config] = []
    monkeypatch.setattr(promote, "_touch_rebuild_request", lambda cfg: calls.append(cfg))

    run_id, _ = _seed_completed_run(tmp_config, outcome="pass")
    promote.promote_from_run(run_id, config=tmp_config)

    assert calls == [], "writes to pending/ must NOT touch the rebuild sentinel"
    assert (tmp_config.pending_dir / "aider__continue-dev.json").exists()
