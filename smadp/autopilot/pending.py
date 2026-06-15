"""Pending verdict review queue: list/show/approve/reject + bulk operations.

Autopilot now routes ALL output to catalog/pending/. This module is the
operator-side gate that decides what graduates into catalog/verdicts/ (the
public catalog rendered by the site).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from smadp.schemas.evidence_level import EVIDENCE_LADDER, rank


class PendingError(RuntimeError):
    pass


@dataclass(frozen=True)
class PendingVerdict:
    """A verdict awaiting human review."""

    key: str  # filename stem (e.g. "v_2026-06-09_aider__autogen_4ef089")
    path: Path
    pair: tuple[str, ...]
    evidence_level: str
    confidence: float
    composite_score: float
    headline: str
    generated_at: str

    @property
    def tier_rank(self) -> int:
        return rank(self.evidence_level) if self.evidence_level in EVIDENCE_LADDER else -1


def _load(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _iter_pending(repo_root: Path) -> Iterator[PendingVerdict]:
    pending_dir = repo_root / "catalog" / "pending"
    if not pending_dir.exists():
        return
    for path in sorted(pending_dir.glob("*.json")):
        data = _load(path)
        if data is None:
            continue
        pair = data.get("pair") or data.get("participants") or []
        if not isinstance(pair, list):
            continue
        yield PendingVerdict(
            key=path.stem,
            path=path,
            pair=tuple(str(p) for p in pair),
            evidence_level=str(data.get("evidence_level") or "unknown"),
            confidence=float(data.get("confidence") or 0.0),
            composite_score=float(data.get("composite_score") or 0.0),
            headline=str(data.get("headline") or ""),
            generated_at=str(data.get("generated_at") or ""),
        )


def list_pending(
    *,
    repo_root: Path,
    tier: str | None = None,
    min_confidence: float | None = None,
    pair_contains: str | None = None,
    max_composite: float | None = None,
    limit: int | None = None,
) -> list[PendingVerdict]:
    """List pending verdicts, filtered.

    Filters:
      tier            — only this evidence_level (exact match)
      min_confidence  — confidence >= this value
      pair_contains   — substring match against any slug in `pair`
      max_composite   — composite_score <= this value (safer verdicts first)
      limit           — at most this many results
    """
    out: list[PendingVerdict] = []
    for v in _iter_pending(repo_root):
        if tier and v.evidence_level != tier:
            continue
        if min_confidence is not None and v.confidence < min_confidence:
            continue
        if max_composite is not None and v.composite_score > max_composite:
            continue
        if pair_contains and not any(pair_contains in s for s in v.pair):
            continue
        out.append(v)
    # Newest first (autopilot uses ISO timestamps in verdict_id and generated_at)
    out.sort(key=lambda v: v.generated_at, reverse=True)
    if limit is not None:
        out = out[:limit]
    return out


def approve_one(*, key: str, repo_root: Path) -> Path:
    """Move a single pending verdict to catalog/verdicts/."""
    pending = repo_root / "catalog" / "pending" / f"{key}.json"
    verdicts = repo_root / "catalog" / "verdicts" / f"{key}.json"
    if not pending.exists():
        raise PendingError(f"no pending verdict at {pending}")
    verdicts.parent.mkdir(parents=True, exist_ok=True)
    try:
        pending.rename(verdicts)
    except OSError as exc:
        raise PendingError(f"could not approve {key}: {exc}") from exc
    _touch_rebuild_sentinel(repo_root)
    return verdicts


def reject_one(*, key: str, repo_root: Path, reason: str) -> Path:
    """Move a single pending verdict to catalog/_rejected/ with a reason record.

    Preserves the original verdict JSON for audit. A sidecar
    ``<key>.reason.json`` captures the rejection metadata.
    """
    pending = repo_root / "catalog" / "pending" / f"{key}.json"
    rejected_dir = repo_root / "catalog" / "_rejected"
    target = rejected_dir / f"{key}.json"
    if not pending.exists():
        raise PendingError(f"no pending verdict at {pending}")
    rejected_dir.mkdir(parents=True, exist_ok=True)
    try:
        pending.rename(target)
    except OSError as exc:
        raise PendingError(f"could not reject {key}: {exc}") from exc
    sidecar = rejected_dir / f"{key}.reason.json"
    sidecar.write_text(
        json.dumps(
            {
                "key": key,
                "reason": reason,
                "rejected_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return target


def approve_batch(
    *,
    repo_root: Path,
    keys: Iterable[str] | None = None,
    tier: str | None = None,
    min_confidence: float | None = None,
    pair_contains: str | None = None,
    max_composite: float | None = None,
    limit: int | None = None,
) -> list[Path]:
    """Approve many pending verdicts at once.

    Either pass an explicit ``keys`` iterable, or pass filters + limit and the
    matching pending verdicts get approved in chronological order.
    """
    if keys is None:
        chosen = list_pending(
            repo_root=repo_root,
            tier=tier,
            min_confidence=min_confidence,
            pair_contains=pair_contains,
            max_composite=max_composite,
            limit=limit,
        )
        target_keys = [v.key for v in chosen]
    else:
        target_keys = list(keys)
    moved: list[Path] = []
    for key in target_keys:
        moved.append(approve_one(key=key, repo_root=repo_root))
    return moved


def _touch_rebuild_sentinel(repo_root: Path) -> None:
    sentinel = repo_root / "report" / ".rebuild-requested"
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.touch()
