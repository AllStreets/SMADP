"""Worker `--once` happy path with mocked runner + promotion."""

from __future__ import annotations

from pathlib import Path

import pytest

from smadp.config import Config
from smadp.sandbox import promote, queue, worker
from smadp.schemas.verdict import SandboxRun
from smadp.utils.time import utcnow


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
async def test_worker_once_processes_one_run(
    tmp_config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = queue.enqueue_sandbox_run(
        slug_a="aider", slug_b="continue-dev", scenario="calendar_email", config=tmp_config
    )

    async def fake_execute_run(rid: str, *, config: Config) -> SandboxRun:
        # Simulate runner: mark completed.
        transcript = config.cache_dir / "transcripts" / rid / "transcript.jsonl"
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text("", encoding="utf-8")
        queue.mark_completed(rid, outcome="pass", transcript_path=str(transcript), config=config)
        return SandboxRun(
            run_id=rid,
            started_at=utcnow(),
            completed_at=utcnow(),
            outcome="pass",
            transcript_ref=str(transcript),
            scenario="calendar_email",
        )

    promote_calls: list[str] = []

    def fake_promote(rid: str, *, config: Config) -> promote.PromotionResult:
        promote_calls.append(rid)
        return promote.PromotionResult(
            run_id=rid, evidence_level_changed_to="sandbox-validated"
        )

    monkeypatch.setattr(worker, "_execute_run", fake_execute_run)
    monkeypatch.setattr(worker, "_promote_from_run", fake_promote)
    monkeypatch.setattr(worker, "_load_keys_for_run", lambda *a, **kw: ({}, []))

    summary = await worker.run_worker(
        once=True, max_runs=None, scenario_filter=None, config=tmp_config
    )

    assert summary.runs_completed == 1
    assert summary.runs_failed == 0
    assert promote_calls == [run_id]


@pytest.mark.asyncio
async def test_worker_once_with_empty_queue_exits_clean(
    tmp_config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(worker, "_load_keys_for_run", lambda *a, **kw: ({}, []))
    summary = await worker.run_worker(
        once=True, max_runs=None, scenario_filter=None, config=tmp_config
    )
    assert summary.runs_completed == 0
    assert summary.runs_failed == 0


@pytest.mark.asyncio
async def test_worker_marks_failed_when_required_key_missing(
    tmp_config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = queue.enqueue_sandbox_run(
        slug_a="aider", slug_b="continue-dev", scenario="calendar_email", config=tmp_config
    )
    # Simulate that one of the adapters is missing a required key.
    monkeypatch.setattr(
        worker, "_load_keys_for_run", lambda *a, **kw: ({}, ["OPENAI_API_KEY"])
    )

    summary = await worker.run_worker(
        once=True, max_runs=None, scenario_filter=None, config=tmp_config
    )
    assert summary.runs_completed == 0
    assert summary.runs_failed == 1
    rows = {r["id"]: r for r in queue._all_rows_for_test(config=tmp_config)}
    assert rows[run_id]["state"] == "failed"
    assert "missing required keys" in (rows[run_id]["error"] or "")
