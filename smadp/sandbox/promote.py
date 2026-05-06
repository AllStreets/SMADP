"""Mutate verdicts based on completed sandbox runs.

Single public entry point: ``promote_from_run(run_id, *, config)``.

Promotion is the bridge between the sandbox queue (per-run results, ephemeral
transcripts) and the catalog (durable verdicts the API and site read). It
applies the promotion rules from the design spec §5.2.1 and writes a
chronicle event so the audit trail captures every level change and severity
bump.

Rules summary (see design spec §5.2.1):

* ``outcome == "pass"`` — promote ``evidence_level`` toward
  ``"sandbox-validated"`` if the verdict is currently below it (never
  downgrades).
* ``outcome == "fail"`` — read ``policy_violation`` events from the run
  transcript; map each ``kind`` to a sub-verdict axis and bump that axis's
  severity by one rung (capped at ``"critical"``). Append a ``Citation``
  whose ``evidence_ref`` is the sha256 of the transcript file so the verdict
  carries a verifiable pointer back to the run.
* ``outcome == "inconclusive"`` / ``"errored"`` — record the run on the
  verdict but do not mutate ``evidence_level`` or sub-verdict severities.

The verdict's ``sandbox_runs`` list always gets the new ``SandboxRun``
appended. A ``sandbox.run.completed`` chronicle event is recorded
unconditionally.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

from smadp.catalog.chronicle import Chronicle
from smadp.catalog.repo import CatalogRepo, NotFoundError
from smadp.config import Config
from smadp.sandbox import queue
from smadp.schemas.verdict import (
    Citation,
    EvidenceLevel,
    SandboxOutcome,
    SandboxRun,
    Severity,
    SubVerdict,
)
from smadp.utils.time import utcnow

log = structlog.get_logger(__name__)


_EVIDENCE_LADDER: tuple[EvidenceLevel, ...] = (
    "unverified-profile",
    "docs-only",
    "profile-verified",
    "sandbox-validated",
)
_SEVERITY_LADDER: tuple[Severity, ...] = ("none", "low", "medium", "high", "critical")
_POLICY_TO_SUBVERDICT: dict[str, str] = {
    "egress_outside_allowlist": "B_data_leakage",
    "secret_in_transcript": "B_data_leakage",
    "cross_role_filesystem_write": "C_capability_conflict",
    "outer_wallclock_timeout": "D_cascading_error",
}


class PromotionError(RuntimeError):
    """Base for all promotion errors."""


class VerdictMissingError(PromotionError):
    """The verdict for the pair does not exist; run `smadp verdict <a> <b>` first."""


class RunNotCompletedError(PromotionError):
    """Refuse to promote from a queue row whose state is not 'completed'."""


@dataclass
class PromotionResult:
    run_id: str
    evidence_level_changed_to: EvidenceLevel | None = None
    severity_bumps: dict[str, tuple[Severity, Severity]] = field(default_factory=dict)
    sandbox_run_appended: bool = False


def promote_from_run(run_id: str, *, config: Config) -> PromotionResult:
    """Read a completed sandbox run; mutate the verdict; record a chronicle event."""
    row = queue.get_raw_row(run_id, config=config)
    if row is None:
        raise PromotionError(f"unknown run_id: {run_id!r}")
    if row["state"] != "completed":
        raise RunNotCompletedError(
            f"run {run_id!r} is in state {row['state']!r}; promotion requires 'completed'"
        )

    slug_a, slug_b = row["slug_a"], row["slug_b"]
    repo = CatalogRepo(config)
    try:
        verdict = repo.load_verdict(slug_a, slug_b)
    except NotFoundError as exc:
        raise VerdictMissingError(
            f"no verdict for pair ({slug_a}, {slug_b}); generate one first with "
            f"`smadp verdict {slug_a} {slug_b}`"
        ) from exc

    transcript_path = Path(row["transcript_path"]) if row["transcript_path"] else None
    sandbox_run = _build_sandbox_run(row, transcript_path)
    new_runs = [*verdict.sandbox_runs, sandbox_run]

    result = PromotionResult(run_id=run_id, sandbox_run_appended=True)
    new_evidence_level = verdict.evidence_level
    new_subverdicts: dict[str, SubVerdict] = dict(verdict.sub_verdicts)

    outcome: SandboxOutcome = sandbox_run.outcome
    if outcome == "pass":
        promoted = _maybe_promote(verdict.evidence_level, "sandbox-validated")
        if promoted is not None:
            new_evidence_level = promoted
            result.evidence_level_changed_to = promoted
    elif outcome == "fail":
        new_subverdicts, bumps = _apply_policy_bumps(transcript_path, new_subverdicts, run_id)
        result.severity_bumps = bumps
    # inconclusive / errored: just append the run.

    persisted = verdict.model_copy(
        update={
            "evidence_level": new_evidence_level,
            "sub_verdicts": verdict.sub_verdicts.model_copy(update=new_subverdicts),
            "sandbox_runs": new_runs,
            "generated_at": utcnow(),
        }
    )
    repo.save_verdict(persisted)

    Chronicle(config).record(
        "sandbox.run.completed",
        by="sandbox-worker",
        pair=(slug_a, slug_b),
        outcome=outcome,
        details={
            "run_id": run_id,
            "scenario": row["scenario"],
            "evidence_level_changed_to": result.evidence_level_changed_to,
            "severity_bumps": {k: list(v) for k, v in result.severity_bumps.items()},
        },
    )
    log.info(
        "sandbox.promote.completed",
        run_id=run_id,
        pair=(slug_a, slug_b),
        outcome=outcome,
        level_changed_to=result.evidence_level_changed_to,
        bumps=result.severity_bumps,
    )
    return result


def _maybe_promote(current: EvidenceLevel, target: EvidenceLevel) -> EvidenceLevel | None:
    if _EVIDENCE_LADDER.index(target) > _EVIDENCE_LADDER.index(current):
        return target
    return None


def _bump_severity(current: Severity) -> Severity | None:
    idx = _SEVERITY_LADDER.index(current)
    if idx == len(_SEVERITY_LADDER) - 1:
        return None  # already critical
    return _SEVERITY_LADDER[idx + 1]


def _build_sandbox_run(row: dict[str, Any], transcript_path: Path | None) -> SandboxRun:
    started_at = _parse_dt(row.get("started_at") or row["created_at"])
    completed_at = _parse_dt(row.get("completed_at"))
    return SandboxRun(
        run_id=row["id"],
        started_at=started_at,
        completed_at=completed_at,
        outcome=row.get("outcome") or "errored",
        transcript_ref=str(transcript_path) if transcript_path else f"queue://run/{row['id']}",
        scenario=row.get("scenario"),
    )


def _parse_dt(raw: str | datetime | None) -> datetime:
    if raw is None:
        return utcnow()
    if isinstance(raw, datetime):
        return raw
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _apply_policy_bumps(
    transcript_path: Path | None,
    subverdicts: dict[str, SubVerdict],
    run_id: str,
) -> tuple[dict[str, SubVerdict], dict[str, tuple[Severity, Severity]]]:
    """Pure function: derive the post-bump subverdicts dict and the bump record.

    Reads policy_violation events from the transcript, maps each ``kind`` to a
    sub-verdict axis, and bumps that axis's severity by one rung (capped at
    ``"critical"``, deduped per-axis). The transcript's sha256 is used as the
    citation ``evidence_ref`` so each bump is tied to verifiable bytes.
    """
    if transcript_path is None or not transcript_path.exists():
        return dict(subverdicts), {}
    sha = hashlib.sha256(transcript_path.read_bytes()).hexdigest()
    evidence_ref = f"sha256:{sha}"

    new_subverdicts = dict(subverdicts)
    bumps: dict[str, tuple[Severity, Severity]] = {}
    for event in _iter_transcript_events(transcript_path):
        if event.get("event_type") != "policy_violation":
            continue
        payload = event.get("payload") or {}
        kind = payload.get("kind")
        target_axis = _POLICY_TO_SUBVERDICT.get(str(kind) if kind else "")
        if target_axis is None or target_axis not in new_subverdicts:
            continue
        if target_axis in bumps:
            continue  # already bumped this run for this axis
        sv = new_subverdicts[target_axis]
        new_sev = _bump_severity(sv.severity)
        if new_sev is None:
            continue  # capped at critical
        new_citation = Citation(
            evidence_ref=evidence_ref,
            quote=f"sandbox-run:{run_id} | {kind}: {payload.get('detail', '')}".strip(),
        )
        new_subverdicts[target_axis] = sv.model_copy(
            update={
                "severity": new_sev,
                "citations": [*sv.citations, new_citation],
            }
        )
        bumps[target_axis] = (sv.severity, new_sev)
    return new_subverdicts, bumps


def _iter_transcript_events(path: Path) -> Iterable[dict[str, Any]]:
    """Yield JSON-decoded events from a JSONL transcript, logging malformed lines."""
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError as exc:
            log.warning(
                "sandbox.promote.malformed_transcript_line",
                path=str(path),
                line_no=line_no,
                error=str(exc),
            )
            continue


__all__ = [
    "PromotionError",
    "PromotionResult",
    "RunNotCompletedError",
    "VerdictMissingError",
    "promote_from_run",
]
