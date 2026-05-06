"""Single-process sandbox worker loop.

The worker is the *only* code that reads keys.env and the *only* code that
calls both the runner and the promotion module. It owns the lifecycle of one
run at a time: claim, exec, promote, log. Concurrency = 1.

The worker exits cleanly on SIGINT / SIGTERM after the in-flight run finishes.
"""

from __future__ import annotations

import asyncio
import json
import signal
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

from smadp.config import Config, load_config
from smadp.sandbox import keys, promote, queue
from smadp.sandbox.runner import execute_run as _runner_execute_run

log = structlog.get_logger(__name__)


# Wrapped so tests can monkeypatch them at module level.
async def _execute_run(
    run_id: str,
    *,
    config: Config,
    env_passthrough: Mapping[str, str] | None = None,
) -> Any:
    return await _runner_execute_run(run_id, config=config, env_passthrough=env_passthrough)


def _promote_from_run(run_id: str, *, config: Config) -> promote.PromotionResult:
    return promote.promote_from_run(run_id, config=config)


@dataclass
class WorkerSummary:
    runs_completed: int = 0
    runs_failed: int = 0


def _load_keys_for_run(
    run_row: dict[str, Any],
    *,
    keys_path: Path,
    config: Config,
) -> tuple[dict[str, str], list[str]]:
    """Return (env_to_pass_to_both_containers, missing_required_keys)."""
    loaded = keys.load_keys_file(keys_path)
    adapters_root = config.repo_root / "adapters"
    merged_env: dict[str, str] = {}
    missing: list[str] = []
    for slug in (run_row["slug_a"], run_row["slug_b"]):
        mcp_path = adapters_root / slug / "mcp.json"
        mcp = json.loads(mcp_path.read_text(encoding="utf-8"))
        env, miss = keys.compute_env_for_adapter(
            loaded,
            env_required=mcp.get("env_required", []),
            env_optional=mcp.get("env_optional", []),
        )
        merged_env.update(env)
        missing.extend(miss)
    return merged_env, sorted(set(missing))


async def run_worker(
    *,
    once: bool,
    max_runs: int | None,
    scenario_filter: str | None,
    config: Config | None = None,
    keys_path: Path | None = None,
    poll_interval_s: float = 2.0,
) -> WorkerSummary:
    cfg = config or load_config()
    keys_file = keys_path or keys.default_keys_path()
    summary = WorkerSummary()

    stop_requested = False

    def _request_stop(*_: Any) -> None:
        nonlocal stop_requested
        stop_requested = True
        log.info("sandbox.worker.stop_requested")

    try:
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGINT, _request_stop)
        loop.add_signal_handler(signal.SIGTERM, _request_stop)
    except (NotImplementedError, RuntimeError):
        pass  # Windows or non-main thread; tests run synchronously anyway.

    while not stop_requested:
        # Atomically claim the oldest pending row (optionally filtered by
        # scenario, so a worker restricted to one scenario never accidentally
        # consumes work meant for another worker).
        claimed = queue.claim_next_pending(config=cfg, scenario=scenario_filter)
        if claimed is None:
            if once:
                break
            await asyncio.sleep(poll_interval_s)
            continue

        # Fetch the raw row to get slugs for the keys lookup.
        run_row = queue.get_raw_row(claimed.run_id, config=cfg)
        if run_row is None:
            log.error("sandbox.worker.row_vanished", run_id=claimed.run_id)
            summary.runs_failed += 1
            if once:
                break
            continue

        env, missing = _load_keys_for_run(run_row, keys_path=keys_file, config=cfg)
        if missing:
            queue.mark_failed(
                claimed.run_id,
                error=f"missing required keys: {missing}",
                config=cfg,
            )
            summary.runs_failed += 1
            log.warning(
                "sandbox.worker.missing_keys",
                run_id=claimed.run_id,
                missing=missing,
            )
        else:
            try:
                await _execute_run(claimed.run_id, config=cfg, env_passthrough=env)
                _promote_from_run(claimed.run_id, config=cfg)
                summary.runs_completed += 1
            except promote.VerdictMissingError as exc:
                summary.runs_failed += 1
                log.error(
                    "sandbox.worker.promote_missing_verdict",
                    run_id=claimed.run_id,
                    error=str(exc),
                )
            except Exception as exc:
                summary.runs_failed += 1
                log.error(
                    "sandbox.worker.run_errored",
                    run_id=claimed.run_id,
                    error=repr(exc),
                )

        if max_runs is not None and (summary.runs_completed + summary.runs_failed) >= max_runs:
            break
        if once:
            break

    log.info(
        "sandbox.worker.exit",
        runs_completed=summary.runs_completed,
        runs_failed=summary.runs_failed,
    )
    return summary


__all__ = ["WorkerSummary", "run_worker"]
