"""Promote: property floors bound LLM severities; tripwire halts are chronicled."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from smadp.catalog.chronicle import Chronicle
from smadp.config import Config
from smadp.sandbox import promote, queue
from smadp.sandbox.properties import evaluate_properties
from smadp.sandbox.scenarios import load_scenario
from smadp.sandbox.transcripts import Transcript, TranscriptEvent, TranscriptWriter

TS = datetime(2026, 6, 12, tzinfo=UTC)


@pytest.fixture
def tmp_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    catalog = tmp_path / "catalog"
    cache = tmp_path / "cache"
    catalog.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SMADP_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("SMADP_CATALOG", str(catalog))
    monkeypatch.setenv("SMADP_CACHE_DIR", str(cache))

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


def _seed_exfil_run(
    cfg: Config,
    *,
    outcome: str,
    attacker_leaks_canary: bool,
    tripwire_rule: str | None = None,
) -> tuple[str, Path]:
    """Enqueue secret_exfiltration, write a transcript + property-report sidecar."""
    run_id = queue.enqueue_sandbox_run(
        slug_a="aider", slug_b="continue-dev", scenario="secret_exfiltration", config=cfg
    )
    sc = load_scenario("secret_exfiltration")
    canary = next(iter(sc.planted_assets.values()))

    transcript_dir = cfg.cache_dir / "sandbox-runs" / run_id
    transcript_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = transcript_dir / "transcript.jsonl"
    writer = TranscriptWriter(transcript_path)
    line = canary if attacker_leaks_canary else "no secret here"
    writer.emit(
        agent=f"smadp-{run_id}-attacker",
        event_type="stdout",
        direction="agent_to_env",
        payload={"line": line},
    )
    writer.emit(
        agent=f"smadp-{run_id}-attacker",
        event_type="exit",
        direction="internal",
        payload={"code": 0},
    )
    writer.close()

    transcript = Transcript.load(run_id, transcript_path)
    report = evaluate_properties(sc, transcript)
    (transcript_dir / "property-report.json").write_text(report.to_json(), encoding="utf-8")

    queue.mark_completed(
        run_id,
        outcome=outcome,
        transcript_path=str(transcript_path),
        tripwire_rule=tripwire_rule,
        config=cfg,
    )
    return run_id, transcript_path


def test_adversarial_fail_floors_b_data_leakage(tmp_config: Config) -> None:
    run_id, _ = _seed_exfil_run(tmp_config, outcome="fail", attacker_leaks_canary=True)

    promote.promote_from_run(run_id, config=tmp_config)

    pending = tmp_config.pending_dir / "aider__continue-dev.json"
    assert pending.exists()
    from smadp.schemas.verdict import Verdict

    verdict = Verdict.model_validate_json(pending.read_text("utf-8"))
    assert verdict.sub_verdicts.B_data_leakage.severity in {"high", "critical"}
    assert verdict.sandbox_runs[-1].mode == "adversarial"


def test_halted_by_tripwire_records_chronicle_and_floors(tmp_config: Config) -> None:
    run_id, _ = _seed_exfil_run(
        tmp_config,
        outcome="halted_by_tripwire",
        attacker_leaks_canary=True,
        tripwire_rule="planted_secret_in_output",
    )

    promote.promote_from_run(run_id, config=tmp_config)

    pending = tmp_config.pending_dir / "aider__continue-dev.json"
    from smadp.schemas.verdict import Verdict

    verdict = Verdict.model_validate_json(pending.read_text("utf-8"))
    last = verdict.sandbox_runs[-1]
    assert last.outcome == "halted_by_tripwire"
    assert last.tripwire_rule == "planted_secret_in_output"
    # Floors still apply on a halt.
    assert verdict.sub_verdicts.B_data_leakage.severity in {"high", "critical"}

    halted = [
        e for e in Chronicle(tmp_config).iter_events() if e.event == "sandbox.tripwire.halted"
    ]
    assert len(halted) == 1
    assert halted[0].details["rule"] == "planted_secret_in_output"
