"""Webhook delivery worker.

Single-row processor (``process_one_pending``) and a loop (``run_loop``)
plus a ``__main__`` entry point so it can run as ``python -m smadp.webhooks.worker``.
The loop body is intentionally tiny — every state-machine decision is in
``smadp/webhooks/deliveries.py``.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Final

import httpx
import structlog

from smadp.config import Config, load_config
from smadp.tenancy.keys import load_signing_key
from smadp.transparency import journal
from smadp.utils.time import utcnow
from smadp.webhooks import deliveries, store
from smadp.webhooks.envelope import compute_hmac

log = structlog.get_logger(__name__)

_BACKOFFS_SECONDS: Final[tuple[int, ...]] = (1, 4, 16, 64, 256)
_MAX_ATTEMPTS: Final[int] = 6  # 1 original + 5 retries
_POST_TIMEOUT_S: Final[float] = 10.0


def _now() -> datetime:
    """Indirection so tests can monkeypatch worker._now."""
    return utcnow()


def _backoff_for_attempts_done(attempts_done: int) -> int:
    """Return seconds to wait before the next attempt, given how many have happened.

    attempts_done == 1 → 1s (1st backoff), == 5 → 256s (5th backoff).
    Caller must guarantee attempts_done < _MAX_ATTEMPTS.
    """
    return _BACKOFFS_SECONDS[attempts_done - 1]


def process_one_pending(*, config: Config | None = None) -> bool:
    """Claim and process one pending delivery; return True if any work happened."""
    cfg = config or load_config()
    delivery = deliveries.claim_pending(config=cfg)
    if delivery is None:
        return False

    secret = store.load_subscription_secret(subscription_id=delivery.subscription_id, config=cfg)
    sub = store.get_subscription(subscription_id=delivery.subscription_id, config=cfg)
    sig = compute_hmac(secret, delivery.body)
    headers = {
        "Content-Type": "application/json",
        "X-SMADP-Event-Type": delivery.event_type.value,
        "X-SMADP-Delivery-Id": delivery.id,
        "X-SMADP-Signature": sig,
    }
    try:
        with httpx.Client(timeout=_POST_TIMEOUT_S) as client:
            resp = client.post(sub.url, content=delivery.body, headers=headers)
        status_code: int = resp.status_code
    except httpx.HTTPError as exc:
        _handle_failure(
            cfg=cfg,
            delivery_id=delivery.id,
            attempts_done=delivery.attempts,
            error=f"network: {exc!s}",
        )
        return True

    if 200 <= status_code < 300:
        deliveries.mark_delivered(delivery_id=delivery.id, config=cfg)
        return True
    if 400 <= status_code < 500:
        deliveries.mark_failed(
            delivery_id=delivery.id,
            error=f"HTTP {status_code}",
            config=cfg,
        )
        return True

    # 1xx, 3xx, 5xx → retry-eligible
    _handle_failure(
        cfg=cfg,
        delivery_id=delivery.id,
        attempts_done=delivery.attempts,
        error=f"HTTP {status_code}",
    )
    return True


def _handle_failure(
    *, cfg: Config, delivery_id: str, attempts_done: int, error: str
) -> None:
    """Either reschedule pending or mark exhausted + write transparency event."""
    if attempts_done >= _MAX_ATTEMPTS:
        deliveries.mark_exhausted(delivery_id=delivery_id, error=error, config=cfg)
        _emit_exhausted_transparency_event(cfg=cfg, delivery_id=delivery_id, error=error)
        return
    backoff = _backoff_for_attempts_done(attempts_done)
    next_at = _now() + timedelta(seconds=backoff)
    deliveries.reschedule_pending(
        delivery_id=delivery_id,
        next_attempt_at=next_at,
        error=error,
        config=cfg,
    )


def _emit_exhausted_transparency_event(
    *, cfg: Config, delivery_id: str, error: str
) -> None:
    """Sign with the FIRST workspace's BYOK key (delivery's owning workspace).

    We look up the subscription → workspace, then load that workspace's BYOK key.
    If the key is missing, log + skip (do NOT crash the worker).
    """
    try:
        delivery = next(d for d in deliveries.iter_all(config=cfg) if d.id == delivery_id)
        sub = store.get_subscription(subscription_id=delivery.subscription_id, config=cfg)
        signing_key = load_signing_key(workspace_id=sub.workspace_id, config=cfg)
        if signing_key is None:
            log.warning(
                "webhooks.exhausted.no_signing_key",
                workspace_id=sub.workspace_id,
                delivery_id=delivery_id,
            )
            return
        journal.append_event(
            event_type="webhook.delivery_exhausted",
            payload={
                "workspace_id": sub.workspace_id,
                "subscription_id": sub.id,
                "delivery_id": delivery_id,
                "url": sub.url,
                "last_error": error,
            },
            signing_key=signing_key,
            config=cfg,
        )
    except (KeyError, StopIteration) as exc:
        log.warning(
            "webhooks.exhausted.transparency_skipped",
            delivery_id=delivery_id,
            reason=str(exc),
        )


def run_loop(
    *, config: Config | None = None, idle_sleep_s: float = 1.0, max_iterations: int | None = None
) -> int:
    """Process pending deliveries until idle, sleep, repeat. Returns total processed.

    ``max_iterations`` of None means run forever (used by ``__main__``).
    Tests pass an int to bound the loop.
    """
    cfg = config or load_config()
    processed = 0
    iterations = 0
    while True:
        did_work = process_one_pending(config=cfg)
        if did_work:
            processed += 1
        else:
            time.sleep(idle_sleep_s)
        iterations += 1
        if max_iterations is not None and iterations >= max_iterations:
            return processed


__all__ = [
    "process_one_pending",
    "run_loop",
]


def main() -> None:
    """``python -m smadp.webhooks.worker`` — runs forever."""
    log.info("webhooks.worker.starting")
    run_loop()


if __name__ == "__main__":
    main()
