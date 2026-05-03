"""Sigstore (Rekor) submission stubs — real wiring lands in Plan 2.

Plan 1 establishes:

* the ``signed_events.rekor_uuid`` column (already in ``journal.py`` schema)
* a queue API so retries are uniform
* a stub ``submit_to_rekor`` that returns ``None`` (deferred)

Plan 2 swaps the stub for a real ``sigstore`` client call. The interface
shape — ``submit_to_rekor(event_id) -> rekor_uuid | None`` and
``retry_pending_submissions()`` — is the contract Plan 2 must honor.
"""

from __future__ import annotations

import structlog

from smadp.config import Config, load_config
from smadp.schemas.transparency import SignedEvent
from smadp.transparency.journal import _connect, _ensure_schema, iter_events

log = structlog.get_logger(__name__)


def submit_to_rekor(*, event_id: int, config: Config | None = None) -> str | None:
    """STUB: returns None to indicate deferred submission.

    Plan 2 replaces this with a real Sigstore client call that returns
    the assigned Rekor UUID.
    """
    log.info("transparency.sigstore.deferred", event_id=event_id)
    return None


def list_pending_submissions(*, config: Config | None = None) -> list[SignedEvent]:
    cfg = config or load_config()
    return [ev for ev in iter_events(config=cfg) if ev.rekor_uuid is None]


def mark_submitted(*, event_id: int, rekor_uuid: str, config: Config | None = None) -> None:
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        cur = conn.execute(
            "UPDATE signed_events SET rekor_uuid = ? WHERE id = ? AND rekor_uuid IS NULL",
            (rekor_uuid, event_id),
        )
        if cur.rowcount == 0:
            raise KeyError(f"No pending event with id {event_id!r}; already submitted or absent.")
        log.info(
            "transparency.sigstore.submitted",
            event_id=event_id,
            rekor_uuid=rekor_uuid,
        )
    finally:
        conn.close()


def retry_pending_submissions(*, config: Config | None = None) -> int:
    """Iterate pending events, call ``submit_to_rekor``, mark submitted on success.

    Returns the number of events successfully submitted.
    """
    cfg = config or load_config()
    submitted = 0
    for ev in list_pending_submissions(config=cfg):
        rekor_uuid = submit_to_rekor(event_id=ev.id, config=cfg)
        if rekor_uuid is not None:
            mark_submitted(event_id=ev.id, rekor_uuid=rekor_uuid, config=cfg)
            submitted += 1
    return submitted


__all__ = [
    "list_pending_submissions",
    "mark_submitted",
    "retry_pending_submissions",
    "submit_to_rekor",
]
