# SMADP v2-D Plan 3 — Webhooks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the v2-D webhook surface — per-workspace `subscriptions`, signed-and-retried `webhook_deliveries`, an in-process `dispatcher`, a separate-process `worker`, a `webhook` CLI subgroup, and the wiring that fires `passport.generated` on every passport render.

**Architecture:** The dispatcher is a synchronous in-process function that fans events out to a SQLite-backed `webhook_deliveries` queue, exactly mirroring the v1 `sandbox/queue.py` and v2-D `transparency/journal.py` patterns (WAL, `BEGIN IMMEDIATE`, ISO-8601 `Z` timestamps). The worker is a separate `python -m smadp.webhooks.worker` process — uniform claim/POST/retry loop with HMAC-SHA256 over a stable JSON envelope. Subscription secrets are stored encrypted under the same per-workspace KEK/DEK that backs BYOK keys (mirrors `smadp/tenancy/keys.py`); the spec's `secret_hash` column name is replaced with `secret_encrypted` + `nonce` because HMAC needs the raw secret at delivery time (documented in Pre-flight § Storage choice).

**Tech Stack:** Python 3.11/3.12, FastAPI (existing), Click (existing), httpx **sync** Client (existing convention), Pydantic v2 (`extra="forbid"`), `cryptography` AES-GCM/HKDF (existing BYOK helpers), `respx` for outbound HTTP mocking in tests, `structlog` for logging. **No new dependencies.**

---

## Pre-flight — design picks (read once, then begin)

These decisions resolve ambiguity in the spec. They are **fixed** for Plan 3; later plans can revisit.

### Storage of subscription secrets

The spec table sketch (`§8.1`) shows a `secret_hash` column on `subscriptions`. The delivery flow (`§7.3`) requires `HMAC-SHA256(subscription.secret, body)` — i.e. the **raw** secret at every delivery. A hash of the secret is insufficient. We therefore deviate from the column name and store the secret **encrypted** with the per-workspace AES-GCM DEK derived in `smadp/tenancy/keys.py` (HKDF over `SMADP_KEK_MASTER` with the workspace id as salt; same code path).

Columns: `secret_encrypted BLOB NOT NULL` + `nonce BLOB NOT NULL`. The plaintext secret is returned **once** at create-time (POST response) and never again. Workers call `store.load_subscription_secret(subscription_id)` which decrypts via the workspace DEK.

This deviation is logged in Task 17's spec-coverage cross-check.

### Backoff schedule

Spec §6.5 says "exponential backoff (1s/4s/16s/64s/256s, then `exhausted`)". We interpret this as **6 total attempts** (1 initial + 5 retries) with 5 backoffs between them: indexes `[1, 4, 16, 64, 256]` seconds. After attempt #6 fails the row is marked `exhausted` and a `webhook.delivery_exhausted` transparency event is appended.

Constants live in `smadp/webhooks/worker.py`:

```python
_BACKOFFS_SECONDS = (1, 4, 16, 64, 256)
_MAX_ATTEMPTS = 6  # 1 original + 5 retries
```

### Sync vs async httpx

Existing convention (e.g. `smadp/transparency/sigstore.py`) uses **sync** `httpx.Client(timeout=...)` for outbound HTTP. The worker is single-process, claim-one-row-then-POST; we follow the convention. No `AsyncClient`, no `asyncio` in the worker hot path.

### Dispatcher idempotency

Each `dispatch_event(...)` call generates a **new** `event_id` (`evt_<14ts>_<6hex>`). Two dispatches for the same payload produce two `event_id`s and two delivery rows per matching subscription — that's intentional. Idempotency is the subscriber's responsibility (per spec §10 note on `X-SMADP-Delivery-Id` uniqueness).

The worker's claim is idempotent on the **delivery_id** — `BEGIN IMMEDIATE; UPDATE webhook_deliveries SET status='running', attempts=attempts+1 WHERE id=? AND status='pending' RETURNING *;` ensures two workers cannot double-deliver the same row. We add an explicit `running` state to the spec's `pending|delivered|failed|exhausted` set so the worker can show "in-flight" rows in the CLI.

### Subscription id format

Mirror workspace-id pattern: `sub_<8 base32-uppercase alphanumeric>` (e.g. `sub_AB12CD34`). Validated by Pydantic regex on the schema.

### Delivery id format

Sortable timestamp prefix: `wd_<YYYYMMDDhhmmss>_<6hex>` so `ORDER BY id` ≡ `ORDER BY created_at` and the CLI can show recent rows without an extra column.

### Event id format (envelope `id`)

Sortable timestamp prefix: `evt_<YYYYMMDDhhmmss>_<6hex>`. Same generator helper as delivery id.

### Six event types (exact strings)

From spec §3 row "Webhook events":

```
verdict.created
verdict.updated
verdict.expired
framework_coverage.changed
passport.generated
passport.revoked
```

These live in `smadp/schemas/webhooks.py::EventType` (StrEnum). Plan 3 only **fires** `passport.generated` (Task 11 wires it into the renderer); the other five are reserved for Plans 4/5.

---

## File structure (locked before tasks begin)

| Path | Responsibility |
|------|----------------|
| `smadp/schemas/webhooks.py` | `EventType`, `DeliveryStatus`, `Subscription`, `WebhookDelivery`, `WebhookEnvelope` Pydantic models |
| `smadp/webhooks/__init__.py` | empty package marker |
| `smadp/webhooks/envelope.py` | `build_envelope(...)`, `compute_hmac(secret, body)`, `canonical_envelope_bytes(envelope)` |
| `smadp/webhooks/store.py` | subscription CRUD + secret encrypt/decrypt; mirrors `tenancy/store.py` |
| `smadp/webhooks/deliveries.py` | `webhook_deliveries` queue: schema, enqueue, claim_pending, mark_delivered/failed/exhausted/bump_pending |
| `smadp/webhooks/dispatcher.py` | `dispatch_event(event_type, payload, workspace_id, *, config)` — match subs + INSERT rows |
| `smadp/webhooks/worker.py` | `process_one_pending(...)`, `run_loop(...)`, `python -m smadp.webhooks.worker` entry |
| `smadp/webhooks/api.py` | `POST/GET/DELETE /api/webhooks/subscriptions[/{id}]`, `GET /api/webhooks/deliveries` |
| `smadp/webhooks/cli.py` | `smadp webhook subscriptions ls/create/delete`, `smadp webhook deliveries ls`, `smadp webhook worker --once` |
| `smadp/passport/render.py` | **modify** to call `dispatcher.dispatch_event("passport.generated", ...)` after the transparency event |
| `smadp/api/routes/__init__.py` | **modify** — add `webhooks.router` (alphabetical import + ROUTERS append) |
| `smadp/cli.py` | **modify** — `cli.add_command(webhook_group)` |
| `tests/unit/test_schemas_webhooks.py` | schema validation |
| `tests/unit/test_webhooks_envelope.py` | HMAC reference + canonical bytes byte-stability |
| `tests/unit/test_webhooks_store.py` | sub CRUD + secret roundtrip |
| `tests/unit/test_webhooks_deliveries.py` | queue claim semantics, no double-claim |
| `tests/unit/test_webhooks_dispatcher.py` | matching + insert row count |
| `tests/unit/test_webhooks_worker.py` | retry math, 4xx no-retry, 5xx retry, exhaustion, transparency event |
| `tests/integration/test_webhooks_api.py` | subscription CRUD over FastAPI |
| `tests/integration/test_webhooks_cli.py` | CLI subcommands roundtrip |
| `tests/integration/test_webhook_full_lifecycle.py` | subscribe → render → dispatch → worker → fake server receives signed POST |
| `tests/integration/test_webhook_retry_exhaust.py` | 503 forever → 6 attempts → `exhausted` + transparency event |
| `tests/integration/test_webhook_4xx_no_retry.py` | 400 → `failed` after 1 attempt |
| `tests/golden/test_webhook_envelope_golden.py` | byte-stable envelope JSON for fixed event |
| `.github/workflows/ci.yml` | **modify** — add a passport-render → worker --once smoke step |

---

## Task 1: Webhook schemas (`smadp/schemas/webhooks.py`)

**Files:**
- Create: `smadp/schemas/webhooks.py`
- Create: `tests/unit/test_schemas_webhooks.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_schemas_webhooks.py`:

```python
"""Unit tests for smadp.schemas.webhooks."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from smadp.schemas.webhooks import (
    DeliveryStatus,
    EventType,
    Subscription,
    WebhookDelivery,
    WebhookEnvelope,
)


def test_event_type_values_are_locked():
    """Locked-down enum: any rename is a contract break."""
    assert {e.value for e in EventType} == {
        "verdict.created",
        "verdict.updated",
        "verdict.expired",
        "framework_coverage.changed",
        "passport.generated",
        "passport.revoked",
    }


def test_delivery_status_values_are_locked():
    assert {s.value for s in DeliveryStatus} == {
        "pending",
        "running",
        "delivered",
        "failed",
        "exhausted",
    }


def test_subscription_id_pattern_enforced():
    with pytest.raises(ValidationError):
        Subscription(
            id="bad-id",
            workspace_id="ws_ABCD1234",
            url="https://example.com/wh",
            event_types=[EventType.PASSPORT_GENERATED],
            active=True,
            created_at=datetime.now(timezone.utc),
        )


def test_subscription_url_must_be_https_or_localhost():
    with pytest.raises(ValidationError):
        Subscription(
            id="sub_AB12CD34",
            workspace_id="ws_ABCD1234",
            url="ftp://example.com/wh",
            event_types=[EventType.PASSPORT_GENERATED],
            active=True,
            created_at=datetime.now(timezone.utc),
        )


def test_subscription_accepts_http_localhost_for_dev():
    """http://localhost is allowed (dev/test); other http URLs are not."""
    Subscription(
        id="sub_AB12CD34",
        workspace_id="ws_ABCD1234",
        url="http://localhost:9000/wh",
        event_types=[EventType.PASSPORT_GENERATED],
        active=True,
        created_at=datetime.now(timezone.utc),
    )
    with pytest.raises(ValidationError):
        Subscription(
            id="sub_AB12CD34",
            workspace_id="ws_ABCD1234",
            url="http://example.com/wh",
            event_types=[EventType.PASSPORT_GENERATED],
            active=True,
            created_at=datetime.now(timezone.utc),
        )


def test_subscription_event_types_must_be_nonempty():
    with pytest.raises(ValidationError):
        Subscription(
            id="sub_AB12CD34",
            workspace_id="ws_ABCD1234",
            url="https://example.com/wh",
            event_types=[],
            active=True,
            created_at=datetime.now(timezone.utc),
        )


def test_webhook_delivery_id_pattern_enforced():
    with pytest.raises(ValidationError):
        WebhookDelivery(
            id="bad",
            subscription_id="sub_AB12CD34",
            event_id="evt_20260503120000_abc123",
            event_type=EventType.PASSPORT_GENERATED,
            body=b'{"x":1}',
            status=DeliveryStatus.PENDING,
            attempts=0,
            next_attempt_at=datetime.now(timezone.utc),
            last_error=None,
            created_at=datetime.now(timezone.utc),
            delivered_at=None,
        )


def test_webhook_envelope_requires_required_keys():
    with pytest.raises(ValidationError):
        WebhookEnvelope(
            id="evt_20260503120000_abc123",
            type=EventType.PASSPORT_GENERATED,
            created_at=datetime.now(timezone.utc),
            workspace_id="ws_ABCD1234",
            data={"verdict_id": "vdt_X"},
            signature_meta={},  # missing transparency_log_id
        )


def test_webhook_envelope_round_trip():
    env = WebhookEnvelope(
        id="evt_20260503120000_abc123",
        type=EventType.PASSPORT_GENERATED,
        created_at=datetime(2026, 5, 3, 12, 0, 0, tzinfo=timezone.utc),
        workspace_id="ws_ABCD1234",
        data={"verdict_id": "vdt_X"},
        signature_meta={"transparency_log_id": 7, "prev_event_hash": "sha256:" + "0" * 64},
    )
    again = WebhookEnvelope.model_validate(env.model_dump(mode="json"))
    assert again == env
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_schemas_webhooks.py -v`
Expected: collection error or import error — module doesn't exist yet.

- [ ] **Step 3: Implement the schemas**

Create `smadp/schemas/webhooks.py`:

```python
"""Webhook schemas (Pydantic v2): events, subscriptions, deliveries, envelopes."""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

SUBSCRIPTION_ID_RE = re.compile(r"^sub_[A-Z0-9]{8,}$")
DELIVERY_ID_RE = re.compile(r"^wd_[0-9]{14}_[0-9a-f]{6}$")
EVENT_ID_RE = re.compile(r"^evt_[0-9]{14}_[0-9a-f]{6}$")
WORKSPACE_ID_RE = re.compile(r"^ws_[A-Z0-9]{8,}$")


class EventType(StrEnum):
    VERDICT_CREATED = "verdict.created"
    VERDICT_UPDATED = "verdict.updated"
    VERDICT_EXPIRED = "verdict.expired"
    FRAMEWORK_COVERAGE_CHANGED = "framework_coverage.changed"
    PASSPORT_GENERATED = "passport.generated"
    PASSPORT_REVOKED = "passport.revoked"


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DELIVERED = "delivered"
    FAILED = "failed"
    EXHAUSTED = "exhausted"


class Subscription(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    workspace_id: str
    url: str
    event_types: list[EventType]
    active: bool
    created_at: datetime

    @field_validator("id")
    @classmethod
    def _id_pattern(cls, v: str) -> str:
        if not SUBSCRIPTION_ID_RE.match(v):
            raise ValueError(f"Invalid subscription id: {v!r}")
        return v

    @field_validator("workspace_id")
    @classmethod
    def _ws_id(cls, v: str) -> str:
        if not WORKSPACE_ID_RE.match(v):
            raise ValueError(f"Invalid workspace id: {v!r}")
        return v

    @field_validator("url")
    @classmethod
    def _url_scheme(cls, v: str) -> str:
        parsed = urlparse(v)
        if parsed.scheme == "https":
            return v
        if parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}:
            return v
        raise ValueError(
            f"Subscription URL must be https:// (or http://localhost for dev); got {v!r}"
        )

    @field_validator("event_types")
    @classmethod
    def _nonempty(cls, v: list[EventType]) -> list[EventType]:
        if not v:
            raise ValueError("event_types must not be empty")
        return v


class WebhookDelivery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    subscription_id: str
    event_id: str
    event_type: EventType
    body: bytes
    status: DeliveryStatus
    attempts: int
    next_attempt_at: datetime
    last_error: str | None
    created_at: datetime
    delivered_at: datetime | None

    @field_validator("id")
    @classmethod
    def _id_pattern(cls, v: str) -> str:
        if not DELIVERY_ID_RE.match(v):
            raise ValueError(f"Invalid delivery id: {v!r}")
        return v

    @field_validator("subscription_id")
    @classmethod
    def _sub_id(cls, v: str) -> str:
        if not SUBSCRIPTION_ID_RE.match(v):
            raise ValueError(f"Invalid subscription id: {v!r}")
        return v

    @field_validator("event_id")
    @classmethod
    def _ev_id(cls, v: str) -> str:
        if not EVENT_ID_RE.match(v):
            raise ValueError(f"Invalid event id: {v!r}")
        return v


class WebhookEnvelope(BaseModel):
    """Stable on-the-wire JSON contract; never reorder keys after launch."""

    model_config = ConfigDict(extra="forbid")

    id: str
    type: EventType
    created_at: datetime
    workspace_id: str
    data: dict[str, Any]
    signature_meta: dict[str, Any]

    @field_validator("id")
    @classmethod
    def _ev_id(cls, v: str) -> str:
        if not EVENT_ID_RE.match(v):
            raise ValueError(f"Invalid envelope id: {v!r}")
        return v

    @field_validator("workspace_id")
    @classmethod
    def _ws_id(cls, v: str) -> str:
        if not WORKSPACE_ID_RE.match(v):
            raise ValueError(f"Invalid workspace id: {v!r}")
        return v

    @model_validator(mode="after")
    def _required_signature_meta(self) -> WebhookEnvelope:
        if "transparency_log_id" not in self.signature_meta:
            raise ValueError("signature_meta must include 'transparency_log_id'")
        return self


__all__ = [
    "DeliveryStatus",
    "EventType",
    "Subscription",
    "WebhookDelivery",
    "WebhookEnvelope",
]
```

- [ ] **Step 4: Run tests to verify pass**

Run: `.venv/bin/pytest tests/unit/test_schemas_webhooks.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add smadp/schemas/webhooks.py tests/unit/test_schemas_webhooks.py
git commit -m "feat(schemas): webhook EventType, Subscription, WebhookDelivery, WebhookEnvelope"
```

---

## Task 2: Envelope builder + HMAC

**Files:**
- Create: `smadp/webhooks/__init__.py` (empty)
- Create: `smadp/webhooks/envelope.py`
- Create: `tests/unit/test_webhooks_envelope.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_webhooks_envelope.py`:

```python
"""Unit tests for envelope builder + HMAC."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone

from smadp.schemas.webhooks import EventType
from smadp.webhooks.envelope import (
    build_envelope,
    canonical_envelope_bytes,
    compute_hmac,
)


def test_canonical_bytes_are_sorted_and_compact():
    env = build_envelope(
        event_id="evt_20260503120000_abc123",
        event_type=EventType.PASSPORT_GENERATED,
        created_at=datetime(2026, 5, 3, 12, 0, 0, tzinfo=timezone.utc),
        workspace_id="ws_ABCD1234",
        data={"z": 1, "a": 2},
        signature_meta={"transparency_log_id": 7},
    )
    raw = canonical_envelope_bytes(env)
    obj = json.loads(raw)
    # Round-trip preserves all keys.
    assert set(obj.keys()) == {
        "created_at",
        "data",
        "id",
        "signature_meta",
        "type",
        "workspace_id",
    }
    # Compact: no whitespace.
    assert b" " not in raw
    assert b"\n" not in raw
    # Top-level keys are sorted.
    keys_in_order = [
        s.split(b'":')[0].lstrip(b'{"').rstrip(b'"')
        for s in raw.split(b',"')
    ]
    assert keys_in_order == sorted(keys_in_order)


def test_canonical_bytes_byte_stable_across_calls():
    args = dict(
        event_id="evt_20260503120000_abc123",
        event_type=EventType.PASSPORT_GENERATED,
        created_at=datetime(2026, 5, 3, 12, 0, 0, tzinfo=timezone.utc),
        workspace_id="ws_ABCD1234",
        data={"a": 1, "b": [1, 2, {"c": 3}]},
        signature_meta={"transparency_log_id": 7, "prev_event_hash": "sha256:" + "0" * 64},
    )
    a = canonical_envelope_bytes(build_envelope(**args))
    b = canonical_envelope_bytes(build_envelope(**args))
    assert a == b


def test_hmac_matches_hand_computed_reference():
    body = b'{"hello":"world"}'
    secret = "swordfish"
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    assert compute_hmac(secret, body) == f"sha256={expected}"


def test_hmac_constant_format():
    # Always lowercase hex; always sha256= prefix.
    sig = compute_hmac("k", b"x")
    assert sig.startswith("sha256=")
    hex_part = sig[len("sha256=") :]
    assert hex_part == hex_part.lower()
    assert len(hex_part) == 64
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_webhooks_envelope.py -v`
Expected: import error — module doesn't exist.

- [ ] **Step 3: Implement the envelope helpers**

Create `smadp/webhooks/__init__.py` as an empty file.

Create `smadp/webhooks/envelope.py`:

```python
"""Envelope construction + HMAC-SHA256 signing for webhook deliveries."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime
from typing import Any

from smadp.schemas.webhooks import EventType, WebhookEnvelope


def build_envelope(
    *,
    event_id: str,
    event_type: EventType,
    created_at: datetime,
    workspace_id: str,
    data: dict[str, Any],
    signature_meta: dict[str, Any],
) -> WebhookEnvelope:
    """Construct a validated ``WebhookEnvelope``."""
    return WebhookEnvelope(
        id=event_id,
        type=event_type,
        created_at=created_at,
        workspace_id=workspace_id,
        data=data,
        signature_meta=signature_meta,
    )


def canonical_envelope_bytes(envelope: WebhookEnvelope) -> bytes:
    """Sorted-keys, compact UTF-8 JSON. Deterministic byte-for-byte."""
    blob = envelope.model_dump(mode="json")
    return json.dumps(
        blob,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def compute_hmac(secret: str, body: bytes) -> str:
    """Return ``sha256=<hex>`` for the X-SMADP-Signature header."""
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


__all__ = [
    "build_envelope",
    "canonical_envelope_bytes",
    "compute_hmac",
]
```

- [ ] **Step 4: Run tests to verify pass**

Run: `.venv/bin/pytest tests/unit/test_webhooks_envelope.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add smadp/webhooks/__init__.py smadp/webhooks/envelope.py tests/unit/test_webhooks_envelope.py
git commit -m "feat(webhooks): envelope builder + HMAC-SHA256 signer"
```

---

## Task 3: Subscriptions store (CRUD + secret encryption)

**Files:**
- Create: `smadp/webhooks/store.py`
- Create: `tests/unit/test_webhooks_store.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_webhooks_store.py`:

```python
"""Unit tests for the webhook subscriptions store."""

from __future__ import annotations

from pathlib import Path

import pytest

from smadp.config import Config
from smadp.schemas.tenancy import Plan
from smadp.schemas.webhooks import EventType
from smadp.tenancy import store as tenancy
from smadp.webhooks import store


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return Config()


@pytest.fixture
def workspace_id(cfg: Config) -> str:
    ws = tenancy.create_workspace(name="WH", plan=Plan.PUBLIC, config=cfg)
    return ws.id


def test_create_subscription_returns_secret_once(cfg: Config, workspace_id: str):
    sub, secret = store.create_subscription(
        workspace_id=workspace_id,
        url="https://example.com/wh",
        event_types=[EventType.PASSPORT_GENERATED],
        config=cfg,
    )
    assert sub.id.startswith("sub_")
    assert sub.workspace_id == workspace_id
    assert sub.active is True
    assert isinstance(secret, str) and len(secret) >= 32  # entropy floor


def test_load_subscription_secret_roundtrip(cfg: Config, workspace_id: str):
    sub, secret = store.create_subscription(
        workspace_id=workspace_id,
        url="https://example.com/wh",
        event_types=[EventType.PASSPORT_GENERATED],
        config=cfg,
    )
    loaded = store.load_subscription_secret(subscription_id=sub.id, config=cfg)
    assert loaded == secret


def test_list_subscriptions_for_workspace(cfg: Config, workspace_id: str):
    a, _ = store.create_subscription(
        workspace_id=workspace_id, url="https://a/wh",
        event_types=[EventType.PASSPORT_GENERATED], config=cfg,
    )
    b, _ = store.create_subscription(
        workspace_id=workspace_id, url="https://b/wh",
        event_types=[EventType.VERDICT_UPDATED], config=cfg,
    )
    ids = {s.id for s in store.list_subscriptions(workspace_id=workspace_id, config=cfg)}
    assert ids == {a.id, b.id}


def test_match_subscriptions_by_event_type(cfg: Config, workspace_id: str):
    a, _ = store.create_subscription(
        workspace_id=workspace_id, url="https://a/wh",
        event_types=[EventType.PASSPORT_GENERATED, EventType.VERDICT_UPDATED],
        config=cfg,
    )
    b, _ = store.create_subscription(
        workspace_id=workspace_id, url="https://b/wh",
        event_types=[EventType.VERDICT_UPDATED], config=cfg,
    )
    matches = store.match_subscriptions(
        workspace_id=workspace_id,
        event_type=EventType.PASSPORT_GENERATED,
        config=cfg,
    )
    assert {s.id for s in matches} == {a.id}


def test_match_subscriptions_skips_inactive(cfg: Config, workspace_id: str):
    a, _ = store.create_subscription(
        workspace_id=workspace_id, url="https://a/wh",
        event_types=[EventType.PASSPORT_GENERATED], config=cfg,
    )
    store.deactivate_subscription(subscription_id=a.id, config=cfg)
    matches = store.match_subscriptions(
        workspace_id=workspace_id,
        event_type=EventType.PASSPORT_GENERATED,
        config=cfg,
    )
    assert matches == []


def test_get_subscription_by_id(cfg: Config, workspace_id: str):
    sub, _ = store.create_subscription(
        workspace_id=workspace_id, url="https://x/wh",
        event_types=[EventType.PASSPORT_GENERATED], config=cfg,
    )
    loaded = store.get_subscription(subscription_id=sub.id, config=cfg)
    assert loaded == sub


def test_get_subscription_unknown_raises(cfg: Config):
    with pytest.raises(KeyError):
        store.get_subscription(subscription_id="sub_NOPE0000", config=cfg)


def test_load_secret_unknown_raises(cfg: Config):
    with pytest.raises(KeyError):
        store.load_subscription_secret(subscription_id="sub_NOPE0000", config=cfg)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_webhooks_store.py -v`
Expected: import error — module doesn't exist.

- [ ] **Step 3: Implement the store**

Create `smadp/webhooks/store.py`:

```python
"""SQLite-backed subscriptions store with AES-GCM secret-at-rest encryption.

Mirrors the BYOK pattern in ``smadp/tenancy/keys.py``: HKDF over
``SMADP_KEK_MASTER`` with the workspace id as salt; per-row 12-byte nonce.
The DB lives at ``<cache_dir>/webhooks.db``.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Final

import structlog
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from smadp.config import Config, load_config
from smadp.schemas.webhooks import EventType, Subscription
from smadp.tenancy.keys import _derive_dek
from smadp.utils.time import utcnow

log = structlog.get_logger(__name__)


_SCHEMA_SQL: Final[str] = """
CREATE TABLE IF NOT EXISTS subscriptions (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    url TEXT NOT NULL,
    event_types TEXT NOT NULL,        -- JSON array of EventType values
    active INTEGER NOT NULL,          -- 0/1
    nonce BLOB NOT NULL,
    secret_encrypted BLOB NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS subscriptions_workspace
    ON subscriptions(workspace_id, active);
"""


def _db_path(config: Config) -> Path:
    config.cache_dir.mkdir(parents=True, exist_ok=True)
    return config.cache_dir / "webhooks.db"


def _connect(config: Config) -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(config), isolation_level=None, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_SQL)


@contextmanager
def _transaction(conn: sqlite3.Connection) -> Iterator[None]:
    conn.execute("BEGIN IMMEDIATE;")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK;")
        raise
    else:
        conn.execute("COMMIT;")


def _generate_subscription_id() -> str:
    """``sub_<8 uppercase base32-ish>``."""
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "sub_" + "".join(secrets.choice(alphabet) for _ in range(8))


def _generate_secret() -> str:
    """48 bytes of entropy → urlsafe base64 (~64 chars)."""
    return secrets.token_urlsafe(48)


def _encrypt(plaintext: bytes, *, workspace_id: str) -> tuple[bytes, bytes]:
    dek = _derive_dek(workspace_id)
    aes = AESGCM(dek)
    nonce = secrets.token_bytes(12)
    ct = aes.encrypt(nonce, plaintext, associated_data=workspace_id.encode("utf-8"))
    return nonce, ct


def _decrypt(*, nonce: bytes, ciphertext: bytes, workspace_id: str) -> bytes:
    dek = _derive_dek(workspace_id)
    aes = AESGCM(dek)
    return aes.decrypt(nonce, ciphertext, associated_data=workspace_id.encode("utf-8"))


def _row_to_subscription(row: sqlite3.Row) -> Subscription:
    return Subscription(
        id=row["id"],
        workspace_id=row["workspace_id"],
        url=row["url"],
        event_types=[EventType(v) for v in json.loads(row["event_types"])],
        active=bool(row["active"]),
        created_at=datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")),
    )


def create_subscription(
    *,
    workspace_id: str,
    url: str,
    event_types: list[EventType],
    config: Config | None = None,
) -> tuple[Subscription, str]:
    """Insert a new subscription; return (subscription, plaintext_secret).

    The plaintext secret is the only chance to read it — store it once
    and surface to the caller (e.g. the API response). The subscription
    object itself never carries the secret.
    """
    cfg = config or load_config()
    sub_id = _generate_subscription_id()
    secret = _generate_secret()
    nonce, encrypted = _encrypt(secret.encode("utf-8"), workspace_id=workspace_id)
    now_iso = utcnow().isoformat(timespec="seconds").replace("+00:00", "Z")
    types_json = json.dumps([t.value for t in event_types], sort_keys=True)
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        with _transaction(conn):
            conn.execute(
                "INSERT INTO subscriptions"
                "(id, workspace_id, url, event_types, active, nonce,"
                " secret_encrypted, created_at)"
                " VALUES (?, ?, ?, ?, 1, ?, ?, ?)",
                (sub_id, workspace_id, url, types_json, nonce, encrypted, now_iso),
            )
        log.info(
            "webhooks.subscription.created",
            workspace_id=workspace_id,
            subscription_id=sub_id,
            url=url,
        )
        return (
            Subscription(
                id=sub_id,
                workspace_id=workspace_id,
                url=url,
                event_types=event_types,
                active=True,
                created_at=datetime.fromisoformat(now_iso.replace("Z", "+00:00")),
            ),
            secret,
        )
    finally:
        conn.close()


def get_subscription(*, subscription_id: str, config: Config | None = None) -> Subscription:
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        cur = conn.execute("SELECT * FROM subscriptions WHERE id = ?", (subscription_id,))
        row = cur.fetchone()
        if row is None:
            raise KeyError(f"unknown subscription: {subscription_id!r}")
        return _row_to_subscription(row)
    finally:
        conn.close()


def list_subscriptions(
    *, workspace_id: str, config: Config | None = None
) -> list[Subscription]:
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        cur = conn.execute(
            "SELECT * FROM subscriptions WHERE workspace_id = ? ORDER BY created_at DESC",
            (workspace_id,),
        )
        return [_row_to_subscription(r) for r in cur.fetchall()]
    finally:
        conn.close()


def match_subscriptions(
    *,
    workspace_id: str,
    event_type: EventType,
    config: Config | None = None,
) -> list[Subscription]:
    """Active subscriptions for ``workspace_id`` whose event_types contain ``event_type``."""
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        cur = conn.execute(
            "SELECT * FROM subscriptions WHERE workspace_id = ? AND active = 1",
            (workspace_id,),
        )
        out: list[Subscription] = []
        for r in cur.fetchall():
            sub = _row_to_subscription(r)
            if event_type in sub.event_types:
                out.append(sub)
        return out
    finally:
        conn.close()


def deactivate_subscription(
    *, subscription_id: str, config: Config | None = None
) -> None:
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        with _transaction(conn):
            cur = conn.execute(
                "UPDATE subscriptions SET active = 0 WHERE id = ?", (subscription_id,)
            )
            if cur.rowcount == 0:
                raise KeyError(f"unknown subscription: {subscription_id!r}")
        log.info("webhooks.subscription.deactivated", subscription_id=subscription_id)
    finally:
        conn.close()


def load_subscription_secret(
    *, subscription_id: str, config: Config | None = None
) -> str:
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        cur = conn.execute(
            "SELECT workspace_id, nonce, secret_encrypted FROM subscriptions WHERE id = ?",
            (subscription_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise KeyError(f"unknown subscription: {subscription_id!r}")
        plain = _decrypt(
            nonce=row["nonce"],
            ciphertext=row["secret_encrypted"],
            workspace_id=row["workspace_id"],
        )
        return plain.decode("utf-8")
    finally:
        conn.close()


__all__ = [
    "create_subscription",
    "deactivate_subscription",
    "get_subscription",
    "list_subscriptions",
    "load_subscription_secret",
    "match_subscriptions",
]
```

- [ ] **Step 4: Run tests to verify pass**

Run: `.venv/bin/pytest tests/unit/test_webhooks_store.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add smadp/webhooks/store.py tests/unit/test_webhooks_store.py
git commit -m "feat(webhooks): subscriptions store + AES-GCM secret-at-rest"
```

---

## Task 4: Subscriptions API router

**Files:**
- Create: `smadp/webhooks/api.py`
- Create: `tests/integration/test_webhooks_api.py`
- Modify: `smadp/api/routes/__init__.py` (register router)

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_webhooks_api.py`:

```python
"""Integration tests for the /api/webhooks/subscriptions endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from smadp.api.server import create_app
from smadp.config import Config
from smadp.schemas.tenancy import Plan
from smadp.tenancy import store as tenancy


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return Config()


@pytest.fixture
def workspace_id(cfg: Config) -> str:
    ws = tenancy.create_workspace(name="WH", plan=Plan.PUBLIC, config=cfg)
    return ws.id


@pytest.fixture
def client(cfg: Config) -> TestClient:
    return TestClient(create_app(cfg))


def test_create_subscription_returns_secret_once(client: TestClient, workspace_id: str):
    r = client.post(
        "/api/webhooks/subscriptions",
        headers={"X-SMADP-Workspace": workspace_id},
        json={"url": "https://example.com/wh", "event_types": ["passport.generated"]},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["subscription"]["id"].startswith("sub_")
    assert body["subscription"]["url"] == "https://example.com/wh"
    assert body["subscription"]["active"] is True
    assert isinstance(body["secret"], str) and len(body["secret"]) >= 32


def test_create_subscription_rejects_bad_url(client: TestClient, workspace_id: str):
    r = client.post(
        "/api/webhooks/subscriptions",
        headers={"X-SMADP-Workspace": workspace_id},
        json={"url": "ftp://example.com/wh", "event_types": ["passport.generated"]},
    )
    assert r.status_code == 422


def test_create_subscription_requires_workspace_header(client: TestClient):
    r = client.post(
        "/api/webhooks/subscriptions",
        json={"url": "https://example.com/wh", "event_types": ["passport.generated"]},
    )
    assert r.status_code == 403


def test_list_subscriptions_for_workspace(client: TestClient, workspace_id: str):
    for url in ("https://a/wh", "https://b/wh"):
        client.post(
            "/api/webhooks/subscriptions",
            headers={"X-SMADP-Workspace": workspace_id},
            json={"url": url, "event_types": ["passport.generated"]},
        )
    r = client.get(
        "/api/webhooks/subscriptions",
        headers={"X-SMADP-Workspace": workspace_id},
    )
    assert r.status_code == 200, r.text
    items = r.json()
    assert {s["url"] for s in items} == {"https://a/wh", "https://b/wh"}
    # Secret never appears in list responses.
    assert all("secret" not in s for s in items)


def test_delete_subscription_deactivates(client: TestClient, workspace_id: str):
    r = client.post(
        "/api/webhooks/subscriptions",
        headers={"X-SMADP-Workspace": workspace_id},
        json={"url": "https://example.com/wh", "event_types": ["passport.generated"]},
    )
    sub_id = r.json()["subscription"]["id"]
    d = client.delete(
        f"/api/webhooks/subscriptions/{sub_id}",
        headers={"X-SMADP-Workspace": workspace_id},
    )
    assert d.status_code == 204
    listed = client.get(
        "/api/webhooks/subscriptions",
        headers={"X-SMADP-Workspace": workspace_id},
    ).json()
    assert all(s["active"] is False for s in listed if s["id"] == sub_id)


def test_delete_unknown_subscription_returns_404(client: TestClient, workspace_id: str):
    r = client.delete(
        "/api/webhooks/subscriptions/sub_NOPE0000",
        headers={"X-SMADP-Workspace": workspace_id},
    )
    assert r.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/integration/test_webhooks_api.py -v`
Expected: 6 failures (router not registered).

- [ ] **Step 3: Implement the router**

Create `smadp/webhooks/api.py`:

```python
"""FastAPI router for /api/webhooks/subscriptions."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, field_validator
from urllib.parse import urlparse

from smadp.schemas.tenancy import Workspace
from smadp.schemas.webhooks import EventType, Subscription
from smadp.tenancy.deps import current_workspace
from smadp.webhooks import store

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class _CreateSubscriptionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    event_types: list[EventType]

    @field_validator("url")
    @classmethod
    def _url_scheme(cls, v: str) -> str:
        parsed = urlparse(v)
        if parsed.scheme == "https":
            return v
        if parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}:
            return v
        raise ValueError(
            "Subscription URL must be https:// (or http://localhost for dev)"
        )

    @field_validator("event_types")
    @classmethod
    def _nonempty(cls, v: list[EventType]) -> list[EventType]:
        if not v:
            raise ValueError("event_types must not be empty")
        return v


class _CreateSubscriptionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subscription: Subscription
    secret: str


@router.post(
    "/subscriptions",
    response_model=_CreateSubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_subscription(
    body: _CreateSubscriptionBody,
    workspace: Workspace = Depends(current_workspace),
) -> Any:
    sub, secret = store.create_subscription(
        workspace_id=workspace.id,
        url=body.url,
        event_types=body.event_types,
    )
    return _CreateSubscriptionResponse(subscription=sub, secret=secret)


@router.get("/subscriptions", response_model=list[Subscription])
def list_subscriptions(
    workspace: Workspace = Depends(current_workspace),
) -> Any:
    return store.list_subscriptions(workspace_id=workspace.id)


@router.delete("/subscriptions/{subscription_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_subscription(
    subscription_id: str,
    workspace: Workspace = Depends(current_workspace),
) -> Response:
    try:
        existing = store.get_subscription(subscription_id=subscription_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if existing.workspace_id != workspace.id:
        raise HTTPException(status_code=404, detail="subscription not found in this workspace")
    store.deactivate_subscription(subscription_id=subscription_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
```

Modify `smadp/api/routes/__init__.py` — add `webhooks` to the alphabetical import block AND a separate `from smadp.webhooks import api as webhooks` (since the router lives in `smadp/webhooks/api.py`, not `smadp/api/routes/webhooks.py`). Final file:

```python
"""FastAPI route modules for the SMADP REST API."""

from smadp.api.routes import (
    agents,
    chronicle,
    evaluate,
    frameworks,
    health,
    meta,
    passports,
    sandbox,
    search,
    submit,
    transparency,
    verdicts,
    workspaces,
)
from smadp.webhooks import api as webhooks

ROUTERS = [
    health.router,
    meta.router,
    agents.router,
    verdicts.router,
    submit.router,
    evaluate.router,
    search.router,
    frameworks.router,
    chronicle.router,
    sandbox.router,
    workspaces.router,
    transparency.router,
    passports.router,
    webhooks.router,
]

__all__ = ["ROUTERS"]
```

- [ ] **Step 4: Run tests to verify pass**

Run: `.venv/bin/pytest tests/integration/test_webhooks_api.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add smadp/webhooks/api.py smadp/api/routes/__init__.py tests/integration/test_webhooks_api.py
git commit -m "feat(api): /api/webhooks/subscriptions CRUD"
```

---

## Task 5: Deliveries queue — schema + enqueue

**Files:**
- Create: `smadp/webhooks/deliveries.py`
- Create: `tests/unit/test_webhooks_deliveries.py`

This task implements ONLY the schema + insert path. Task 6 adds the claim/finalize state-transition methods.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_webhooks_deliveries.py`:

```python
"""Unit tests for the webhook_deliveries queue (schema + enqueue path)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from smadp.config import Config
from smadp.schemas.tenancy import Plan
from smadp.schemas.webhooks import DeliveryStatus, EventType
from smadp.tenancy import store as tenancy
from smadp.webhooks import deliveries, store


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return Config()


@pytest.fixture
def subscription_id(cfg: Config) -> str:
    ws = tenancy.create_workspace(name="W", plan=Plan.PUBLIC, config=cfg)
    sub, _ = store.create_subscription(
        workspace_id=ws.id,
        url="https://example.com/wh",
        event_types=[EventType.PASSPORT_GENERATED],
        config=cfg,
    )
    return sub.id


def test_enqueue_creates_pending_row(cfg: Config, subscription_id: str):
    delivery_id = deliveries.enqueue(
        subscription_id=subscription_id,
        event_id="evt_20260503120000_abc123",
        event_type=EventType.PASSPORT_GENERATED,
        body=b'{"x":1}',
        config=cfg,
    )
    assert delivery_id.startswith("wd_")
    rows = list(deliveries.iter_all(config=cfg))
    assert len(rows) == 1
    row = rows[0]
    assert row.id == delivery_id
    assert row.subscription_id == subscription_id
    assert row.event_id == "evt_20260503120000_abc123"
    assert row.event_type == EventType.PASSPORT_GENERATED
    assert row.body == b'{"x":1}'
    assert row.status == DeliveryStatus.PENDING
    assert row.attempts == 0
    assert row.last_error is None
    assert row.delivered_at is None


def test_enqueue_next_attempt_at_is_now_or_past(cfg: Config, subscription_id: str):
    deliveries.enqueue(
        subscription_id=subscription_id,
        event_id="evt_20260503120000_abc123",
        event_type=EventType.PASSPORT_GENERATED,
        body=b"{}",
        config=cfg,
    )
    rows = list(deliveries.iter_all(config=cfg))
    assert rows[0].next_attempt_at <= datetime.now(timezone.utc)


def test_iter_all_orders_by_id(cfg: Config, subscription_id: str):
    ids: list[str] = []
    for i in range(3):
        ids.append(
            deliveries.enqueue(
                subscription_id=subscription_id,
                event_id=f"evt_2026050312000{i}_abc123",
                event_type=EventType.PASSPORT_GENERATED,
                body=b"{}",
                config=cfg,
            )
        )
    fetched = [r.id for r in deliveries.iter_all(config=cfg)]
    assert fetched == ids
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_webhooks_deliveries.py -v`
Expected: import error — module doesn't exist.

- [ ] **Step 3: Implement schema + enqueue**

Create `smadp/webhooks/deliveries.py`:

```python
"""SQLite-backed webhook_deliveries queue.

Lives in the same DB file as ``smadp/webhooks/store.py`` (subscriptions),
namely ``<cache_dir>/webhooks.db``. ``BEGIN IMMEDIATE`` serializes writes;
the ``status`` state machine is ``pending → running → {delivered, pending,
failed, exhausted}``.

Time is read via the module-level ``_now()`` helper so tests can monkeypatch it.
"""

from __future__ import annotations

import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

import structlog

from smadp.config import Config, load_config
from smadp.schemas.webhooks import DeliveryStatus, EventType, WebhookDelivery
from smadp.utils.time import utcnow

log = structlog.get_logger(__name__)


_SCHEMA_SQL: Final[str] = """
CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id TEXT PRIMARY KEY,
    subscription_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    body BLOB NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending','running','delivered','failed','exhausted')),
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT NOT NULL,
    last_error TEXT,
    created_at TEXT NOT NULL,
    delivered_at TEXT
);
CREATE INDEX IF NOT EXISTS webhook_deliveries_pending
    ON webhook_deliveries(status, next_attempt_at);
"""


def _db_path(config: Config) -> Path:
    config.cache_dir.mkdir(parents=True, exist_ok=True)
    return config.cache_dir / "webhooks.db"


def _connect(config: Config) -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(config), isolation_level=None, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_SQL)


@contextmanager
def _transaction(conn: sqlite3.Connection) -> Iterator[None]:
    conn.execute("BEGIN IMMEDIATE;")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK;")
        raise
    else:
        conn.execute("COMMIT;")


def _now() -> datetime:
    """Indirection so tests can monkeypatch deliveries._now."""
    return utcnow()


def _isoformat(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _generate_delivery_id(now: datetime) -> str:
    ts = now.strftime("%Y%m%d%H%M%S")
    suffix = secrets.token_hex(3)
    return f"wd_{ts}_{suffix}"


def _row_to_delivery(row: sqlite3.Row) -> WebhookDelivery:
    return WebhookDelivery(
        id=row["id"],
        subscription_id=row["subscription_id"],
        event_id=row["event_id"],
        event_type=EventType(row["event_type"]),
        body=bytes(row["body"]),
        status=DeliveryStatus(row["status"]),
        attempts=int(row["attempts"]),
        next_attempt_at=datetime.fromisoformat(row["next_attempt_at"].replace("Z", "+00:00")),
        last_error=row["last_error"],
        created_at=datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")),
        delivered_at=(
            datetime.fromisoformat(row["delivered_at"].replace("Z", "+00:00"))
            if row["delivered_at"]
            else None
        ),
    )


def enqueue(
    *,
    subscription_id: str,
    event_id: str,
    event_type: EventType,
    body: bytes,
    config: Config | None = None,
) -> str:
    """Insert a pending delivery row; return its id. ``next_attempt_at = now``."""
    cfg = config or load_config()
    now = _now()
    delivery_id = _generate_delivery_id(now)
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        with _transaction(conn):
            conn.execute(
                "INSERT INTO webhook_deliveries"
                "(id, subscription_id, event_id, event_type, body, status, attempts,"
                " next_attempt_at, last_error, created_at, delivered_at)"
                " VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, NULL, ?, NULL)",
                (
                    delivery_id,
                    subscription_id,
                    event_id,
                    event_type.value,
                    body,
                    _isoformat(now),
                    _isoformat(now),
                ),
            )
        log.info(
            "webhooks.delivery.enqueued",
            delivery_id=delivery_id,
            subscription_id=subscription_id,
            event_id=event_id,
            event_type=event_type.value,
        )
        return delivery_id
    finally:
        conn.close()


def iter_all(*, config: Config | None = None) -> Iterator[WebhookDelivery]:
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        cur = conn.execute("SELECT * FROM webhook_deliveries ORDER BY id ASC")
        for row in cur.fetchall():
            yield _row_to_delivery(row)
    finally:
        conn.close()


__all__ = [
    "enqueue",
    "iter_all",
]
```

- [ ] **Step 4: Run tests to verify pass**

Run: `.venv/bin/pytest tests/unit/test_webhooks_deliveries.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add smadp/webhooks/deliveries.py tests/unit/test_webhooks_deliveries.py
git commit -m "feat(webhooks): webhook_deliveries queue schema + enqueue"
```

---

## Task 6: Deliveries queue — claim + finalize (state machine)

**Files:**
- Modify: `smadp/webhooks/deliveries.py` (extend with claim + finalize methods)
- Modify: `tests/unit/test_webhooks_deliveries.py` (extend)

This task adds the claim-and-finalize state-transition machinery the worker needs. The state machine is `pending → running → {delivered | pending(re-armed) | failed | exhausted}`.

- [ ] **Step 1: Write the failing tests (extend existing file)**

Append to `tests/unit/test_webhooks_deliveries.py`:

```python
def test_claim_pending_marks_row_running(cfg: Config, subscription_id: str):
    delivery_id = deliveries.enqueue(
        subscription_id=subscription_id,
        event_id="evt_20260503120000_abc123",
        event_type=EventType.PASSPORT_GENERATED,
        body=b"{}",
        config=cfg,
    )
    claimed = deliveries.claim_pending(config=cfg)
    assert claimed is not None
    assert claimed.id == delivery_id
    assert claimed.status == DeliveryStatus.RUNNING
    assert claimed.attempts == 1


def test_claim_pending_returns_none_when_empty(cfg: Config):
    assert deliveries.claim_pending(config=cfg) is None


def test_claim_pending_skips_future_rows(
    cfg: Config, subscription_id: str, monkeypatch: pytest.MonkeyPatch
):
    """Rows whose next_attempt_at is in the future are not claimable."""
    from datetime import timedelta

    far_future = datetime(2099, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(deliveries, "_now", lambda: far_future - timedelta(days=1))
    deliveries.enqueue(
        subscription_id=subscription_id,
        event_id="evt_20260503120000_abc123",
        event_type=EventType.PASSPORT_GENERATED,
        body=b"{}",
        config=cfg,
    )
    monkeypatch.setattr(deliveries, "_now", lambda: datetime(2050, 1, 1, tzinfo=timezone.utc))
    assert deliveries.claim_pending(config=cfg) is None


def test_claim_pending_does_not_double_claim(cfg: Config, subscription_id: str):
    deliveries.enqueue(
        subscription_id=subscription_id,
        event_id="evt_20260503120000_abc123",
        event_type=EventType.PASSPORT_GENERATED,
        body=b"{}",
        config=cfg,
    )
    a = deliveries.claim_pending(config=cfg)
    b = deliveries.claim_pending(config=cfg)
    assert a is not None
    assert b is None  # second claim sees no pending


def test_mark_delivered_sets_status_and_delivered_at(cfg: Config, subscription_id: str):
    deliveries.enqueue(
        subscription_id=subscription_id,
        event_id="evt_20260503120000_abc123",
        event_type=EventType.PASSPORT_GENERATED,
        body=b"{}",
        config=cfg,
    )
    claimed = deliveries.claim_pending(config=cfg)
    assert claimed is not None
    deliveries.mark_delivered(delivery_id=claimed.id, config=cfg)
    rows = list(deliveries.iter_all(config=cfg))
    assert rows[0].status == DeliveryStatus.DELIVERED
    assert rows[0].delivered_at is not None


def test_mark_failed_sets_status_and_error(cfg: Config, subscription_id: str):
    deliveries.enqueue(
        subscription_id=subscription_id,
        event_id="evt_20260503120000_abc123",
        event_type=EventType.PASSPORT_GENERATED,
        body=b"{}",
        config=cfg,
    )
    claimed = deliveries.claim_pending(config=cfg)
    assert claimed is not None
    deliveries.mark_failed(delivery_id=claimed.id, error="HTTP 400 bad request", config=cfg)
    rows = list(deliveries.iter_all(config=cfg))
    assert rows[0].status == DeliveryStatus.FAILED
    assert rows[0].last_error == "HTTP 400 bad request"


def test_mark_exhausted_writes_status(cfg: Config, subscription_id: str):
    deliveries.enqueue(
        subscription_id=subscription_id,
        event_id="evt_20260503120000_abc123",
        event_type=EventType.PASSPORT_GENERATED,
        body=b"{}",
        config=cfg,
    )
    claimed = deliveries.claim_pending(config=cfg)
    assert claimed is not None
    deliveries.mark_exhausted(delivery_id=claimed.id, error="HTTP 503 forever", config=cfg)
    rows = list(deliveries.iter_all(config=cfg))
    assert rows[0].status == DeliveryStatus.EXHAUSTED
    assert rows[0].last_error == "HTTP 503 forever"


def test_reschedule_pending_arms_for_future_attempt(
    cfg: Config, subscription_id: str, monkeypatch: pytest.MonkeyPatch
):
    """After a 5xx, the worker re-arms a row with next_attempt_at in the future."""
    from datetime import timedelta

    monkeypatch.setattr(
        deliveries, "_now", lambda: datetime(2026, 5, 3, 12, 0, 0, tzinfo=timezone.utc)
    )
    deliveries.enqueue(
        subscription_id=subscription_id,
        event_id="evt_20260503120000_abc123",
        event_type=EventType.PASSPORT_GENERATED,
        body=b"{}",
        config=cfg,
    )
    claimed = deliveries.claim_pending(config=cfg)
    assert claimed is not None
    next_at = datetime(2026, 5, 3, 12, 0, 4, tzinfo=timezone.utc)
    deliveries.reschedule_pending(
        delivery_id=claimed.id,
        next_attempt_at=next_at,
        error="HTTP 503",
        config=cfg,
    )
    # Now claim should still find nothing — current_now < next_attempt_at.
    assert deliveries.claim_pending(config=cfg) is None
    monkeypatch.setattr(
        deliveries, "_now", lambda: datetime(2026, 5, 3, 12, 0, 5, tzinfo=timezone.utc)
    )
    rearmed = deliveries.claim_pending(config=cfg)
    assert rearmed is not None
    assert rearmed.attempts == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_webhooks_deliveries.py -v`
Expected: at least 8 failures (`AttributeError` for `claim_pending`, `mark_delivered`, etc.).

- [ ] **Step 3: Implement claim + finalize**

Append to `smadp/webhooks/deliveries.py` (before the `__all__` block):

```python
def claim_pending(*, config: Config | None = None) -> WebhookDelivery | None:
    """Atomically claim the oldest pending row whose ``next_attempt_at <= now``.

    Marks the row ``running`` and bumps ``attempts``. Returns the row, or
    ``None`` if no eligible row exists. Two concurrent workers cannot
    return the same row (``BEGIN IMMEDIATE`` serializes the SELECT+UPDATE).
    """
    cfg = config or load_config()
    now = _now()
    now_iso = _isoformat(now)
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        with _transaction(conn):
            cur = conn.execute(
                "SELECT id FROM webhook_deliveries"
                " WHERE status = 'pending' AND next_attempt_at <= ?"
                " ORDER BY next_attempt_at ASC, id ASC LIMIT 1",
                (now_iso,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            delivery_id = row["id"]
            conn.execute(
                "UPDATE webhook_deliveries"
                " SET status = 'running', attempts = attempts + 1"
                " WHERE id = ? AND status = 'pending'",
                (delivery_id,),
            )
            cur = conn.execute(
                "SELECT * FROM webhook_deliveries WHERE id = ?", (delivery_id,)
            )
            return _row_to_delivery(cur.fetchone())
    finally:
        conn.close()


def mark_delivered(*, delivery_id: str, config: Config | None = None) -> None:
    cfg = config or load_config()
    now_iso = _isoformat(_now())
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        with _transaction(conn):
            cur = conn.execute(
                "UPDATE webhook_deliveries"
                " SET status = 'delivered', delivered_at = ?, last_error = NULL"
                " WHERE id = ?",
                (now_iso, delivery_id),
            )
            if cur.rowcount == 0:
                raise KeyError(f"unknown delivery: {delivery_id!r}")
        log.info("webhooks.delivery.delivered", delivery_id=delivery_id)
    finally:
        conn.close()


def mark_failed(*, delivery_id: str, error: str, config: Config | None = None) -> None:
    """Terminal: 4xx response — no retry."""
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        with _transaction(conn):
            cur = conn.execute(
                "UPDATE webhook_deliveries SET status = 'failed', last_error = ? WHERE id = ?",
                (error, delivery_id),
            )
            if cur.rowcount == 0:
                raise KeyError(f"unknown delivery: {delivery_id!r}")
        log.info("webhooks.delivery.failed", delivery_id=delivery_id, error=error)
    finally:
        conn.close()


def mark_exhausted(*, delivery_id: str, error: str, config: Config | None = None) -> None:
    """Terminal: retry budget exceeded."""
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        with _transaction(conn):
            cur = conn.execute(
                "UPDATE webhook_deliveries SET status = 'exhausted', last_error = ? WHERE id = ?",
                (error, delivery_id),
            )
            if cur.rowcount == 0:
                raise KeyError(f"unknown delivery: {delivery_id!r}")
        log.info("webhooks.delivery.exhausted", delivery_id=delivery_id, error=error)
    finally:
        conn.close()


def reschedule_pending(
    *,
    delivery_id: str,
    next_attempt_at: datetime,
    error: str,
    config: Config | None = None,
) -> None:
    """Re-arm a running row as pending with a future attempt time."""
    cfg = config or load_config()
    next_iso = _isoformat(next_attempt_at)
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        with _transaction(conn):
            cur = conn.execute(
                "UPDATE webhook_deliveries"
                " SET status = 'pending', next_attempt_at = ?, last_error = ?"
                " WHERE id = ?",
                (next_iso, error, delivery_id),
            )
            if cur.rowcount == 0:
                raise KeyError(f"unknown delivery: {delivery_id!r}")
        log.info(
            "webhooks.delivery.rescheduled",
            delivery_id=delivery_id,
            next_attempt_at=next_iso,
            error=error,
        )
    finally:
        conn.close()
```

Update `__all__` to include the new functions:

```python
__all__ = [
    "claim_pending",
    "enqueue",
    "iter_all",
    "mark_delivered",
    "mark_exhausted",
    "mark_failed",
    "reschedule_pending",
]
```

- [ ] **Step 4: Run tests to verify pass**

Run: `.venv/bin/pytest tests/unit/test_webhooks_deliveries.py -v`
Expected: 11 passed (3 from Task 5 + 8 new).

- [ ] **Step 5: Commit**

```bash
git add smadp/webhooks/deliveries.py tests/unit/test_webhooks_deliveries.py
git commit -m "feat(webhooks): claim/finalize state machine with BEGIN IMMEDIATE serialization"
```

---

## Task 7: Dispatcher

**Files:**
- Create: `smadp/webhooks/dispatcher.py`
- Create: `tests/unit/test_webhooks_dispatcher.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_webhooks_dispatcher.py`:

```python
"""Unit tests for the webhook dispatcher."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from smadp.config import Config
from smadp.schemas.tenancy import Plan
from smadp.schemas.webhooks import EventType
from smadp.tenancy import store as tenancy
from smadp.webhooks import deliveries, dispatcher, store


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return Config()


@pytest.fixture
def workspace_id(cfg: Config) -> str:
    ws = tenancy.create_workspace(name="W", plan=Plan.PUBLIC, config=cfg)
    return ws.id


def test_dispatch_event_inserts_one_row_per_matching_subscription(
    cfg: Config, workspace_id: str
):
    sub_a, _ = store.create_subscription(
        workspace_id=workspace_id, url="https://a/wh",
        event_types=[EventType.PASSPORT_GENERATED], config=cfg,
    )
    sub_b, _ = store.create_subscription(
        workspace_id=workspace_id, url="https://b/wh",
        event_types=[EventType.PASSPORT_GENERATED, EventType.VERDICT_UPDATED],
        config=cfg,
    )
    sub_c, _ = store.create_subscription(
        workspace_id=workspace_id, url="https://c/wh",
        event_types=[EventType.VERDICT_UPDATED], config=cfg,
    )
    n = dispatcher.dispatch_event(
        event_type=EventType.PASSPORT_GENERATED,
        payload={"verdict_id": "vdt_X"},
        workspace_id=workspace_id,
        signature_meta={"transparency_log_id": 7},
        config=cfg,
    )
    assert n == 2  # sub_a + sub_b match
    rows = list(deliveries.iter_all(config=cfg))
    sub_ids_in_rows = {r.subscription_id for r in rows}
    assert sub_ids_in_rows == {sub_a.id, sub_b.id}
    assert sub_c.id not in sub_ids_in_rows


def test_dispatch_event_inserts_zero_when_no_subscriptions(
    cfg: Config, workspace_id: str
):
    n = dispatcher.dispatch_event(
        event_type=EventType.PASSPORT_GENERATED,
        payload={"verdict_id": "vdt_X"},
        workspace_id=workspace_id,
        signature_meta={"transparency_log_id": 7},
        config=cfg,
    )
    assert n == 0
    assert list(deliveries.iter_all(config=cfg)) == []


def test_dispatch_event_skips_inactive_subscriptions(
    cfg: Config, workspace_id: str
):
    sub, _ = store.create_subscription(
        workspace_id=workspace_id, url="https://a/wh",
        event_types=[EventType.PASSPORT_GENERATED], config=cfg,
    )
    store.deactivate_subscription(subscription_id=sub.id, config=cfg)
    n = dispatcher.dispatch_event(
        event_type=EventType.PASSPORT_GENERATED,
        payload={"verdict_id": "vdt_X"},
        workspace_id=workspace_id,
        signature_meta={"transparency_log_id": 7},
        config=cfg,
    )
    assert n == 0


def test_dispatch_event_writes_canonical_envelope_bytes(
    cfg: Config, workspace_id: str
):
    """The body stored in webhook_deliveries equals canonical envelope bytes."""
    import json

    store.create_subscription(
        workspace_id=workspace_id, url="https://a/wh",
        event_types=[EventType.PASSPORT_GENERATED], config=cfg,
    )
    dispatcher.dispatch_event(
        event_type=EventType.PASSPORT_GENERATED,
        payload={"verdict_id": "vdt_X", "headline": "Hi"},
        workspace_id=workspace_id,
        signature_meta={"transparency_log_id": 7, "prev_event_hash": "sha256:" + "0" * 64},
        config=cfg,
    )
    rows = list(deliveries.iter_all(config=cfg))
    body = rows[0].body
    parsed = json.loads(body)
    assert parsed["type"] == "passport.generated"
    assert parsed["data"] == {"verdict_id": "vdt_X", "headline": "Hi"}
    assert parsed["workspace_id"] == workspace_id
    assert parsed["signature_meta"]["transparency_log_id"] == 7


def test_dispatch_event_id_is_unique_across_calls(cfg: Config, workspace_id: str):
    import json

    store.create_subscription(
        workspace_id=workspace_id, url="https://a/wh",
        event_types=[EventType.PASSPORT_GENERATED], config=cfg,
    )
    dispatcher.dispatch_event(
        event_type=EventType.PASSPORT_GENERATED, payload={}, workspace_id=workspace_id,
        signature_meta={"transparency_log_id": 1}, config=cfg,
    )
    dispatcher.dispatch_event(
        event_type=EventType.PASSPORT_GENERATED, payload={}, workspace_id=workspace_id,
        signature_meta={"transparency_log_id": 2}, config=cfg,
    )
    ids = {json.loads(r.body)["id"] for r in deliveries.iter_all(config=cfg)}
    assert len(ids) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_webhooks_dispatcher.py -v`
Expected: import error — module doesn't exist.

- [ ] **Step 3: Implement the dispatcher**

Create `smadp/webhooks/dispatcher.py`:

```python
"""Synchronous in-process dispatcher: match subscriptions, enqueue deliveries.

Called from inside business-logic flows (e.g. after the passport renderer
appends its transparency event). The worker process consumes the rows
asynchronously.
"""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import Any

import structlog

from smadp.config import Config, load_config
from smadp.schemas.webhooks import EventType
from smadp.utils.time import utcnow
from smadp.webhooks import deliveries, store
from smadp.webhooks.envelope import build_envelope, canonical_envelope_bytes

log = structlog.get_logger(__name__)


def _generate_event_id(now: datetime) -> str:
    ts = now.strftime("%Y%m%d%H%M%S")
    suffix = secrets.token_hex(3)
    return f"evt_{ts}_{suffix}"


def dispatch_event(
    *,
    event_type: EventType,
    payload: dict[str, Any],
    workspace_id: str,
    signature_meta: dict[str, Any],
    config: Config | None = None,
) -> int:
    """Fan an event out to every matching active subscription.

    Returns the number of delivery rows created (one per matching sub).
    Caller MUST include ``signature_meta["transparency_log_id"]`` (the
    transparency event id from ``journal.append_event(...).id``); the
    envelope schema requires it.
    """
    cfg = config or load_config()
    matches = store.match_subscriptions(
        workspace_id=workspace_id, event_type=event_type, config=cfg
    )
    if not matches:
        log.info(
            "webhooks.dispatch.no_subscribers",
            event_type=event_type.value,
            workspace_id=workspace_id,
        )
        return 0

    now = utcnow()
    event_id = _generate_event_id(now)
    envelope = build_envelope(
        event_id=event_id,
        event_type=event_type,
        created_at=now,
        workspace_id=workspace_id,
        data=payload,
        signature_meta=signature_meta,
    )
    body = canonical_envelope_bytes(envelope)

    enqueued = 0
    for sub in matches:
        deliveries.enqueue(
            subscription_id=sub.id,
            event_id=event_id,
            event_type=event_type,
            body=body,
            config=cfg,
        )
        enqueued += 1

    log.info(
        "webhooks.dispatch.enqueued",
        event_id=event_id,
        event_type=event_type.value,
        workspace_id=workspace_id,
        subscribers=enqueued,
    )
    return enqueued


__all__ = ["dispatch_event"]
```

- [ ] **Step 4: Run tests to verify pass**

Run: `.venv/bin/pytest tests/unit/test_webhooks_dispatcher.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add smadp/webhooks/dispatcher.py tests/unit/test_webhooks_dispatcher.py
git commit -m "feat(webhooks): dispatcher fans events out to matching subscriptions"
```

---

## Task 8: Worker — process_one_pending (delivery loop body)

**Files:**
- Create: `smadp/webhooks/worker.py`
- Create: `tests/unit/test_webhooks_worker.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_webhooks_worker.py`:

```python
"""Unit tests for the webhook worker's per-row processor."""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from smadp.config import Config
from smadp.schemas.tenancy import Plan
from smadp.schemas.webhooks import DeliveryStatus, EventType
from smadp.tenancy import keys, store as tenancy
from smadp.webhooks import deliveries, dispatcher, store, worker


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return Config()


@pytest.fixture
def workspace_id(cfg: Config) -> str:
    ws = tenancy.create_workspace(name="W", plan=Plan.PUBLIC, config=cfg)
    keys.upload_signing_key(
        workspace_id=ws.id, private_key=Ed25519PrivateKey.generate(), config=cfg
    )
    return ws.id


def _enqueue_one(cfg: Config, workspace_id: str, url: str = "https://hook/x") -> str:
    sub, secret = store.create_subscription(
        workspace_id=workspace_id, url=url,
        event_types=[EventType.PASSPORT_GENERATED], config=cfg,
    )
    dispatcher.dispatch_event(
        event_type=EventType.PASSPORT_GENERATED,
        payload={"verdict_id": "vdt_X"},
        workspace_id=workspace_id,
        signature_meta={"transparency_log_id": 1},
        config=cfg,
    )
    return secret


def test_process_one_pending_returns_false_when_empty(cfg: Config):
    assert worker.process_one_pending(config=cfg) is False


@respx.mock
def test_process_one_pending_2xx_marks_delivered(cfg: Config, workspace_id: str):
    secret = _enqueue_one(cfg, workspace_id)
    captured: dict[str, str] = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        captured["sig"] = request.headers["X-SMADP-Signature"]
        captured["delivery_id"] = request.headers["X-SMADP-Delivery-Id"]
        captured["event_type"] = request.headers["X-SMADP-Event-Type"]
        captured["body"] = request.content.decode("utf-8")
        return httpx.Response(200)

    respx.post("https://hook/x").mock(side_effect=_capture)
    assert worker.process_one_pending(config=cfg) is True

    rows = list(deliveries.iter_all(config=cfg))
    assert rows[0].status == DeliveryStatus.DELIVERED
    assert rows[0].delivered_at is not None

    # Header sanity:
    assert captured["event_type"] == "passport.generated"
    assert captured["delivery_id"].startswith("wd_")
    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"), captured["body"].encode("utf-8"), hashlib.sha256
    ).hexdigest()
    assert captured["sig"] == expected


@respx.mock
def test_process_one_pending_4xx_marks_failed_no_retry(cfg: Config, workspace_id: str):
    _enqueue_one(cfg, workspace_id)
    respx.post("https://hook/x").mock(return_value=httpx.Response(400, text="bad"))
    assert worker.process_one_pending(config=cfg) is True
    rows = list(deliveries.iter_all(config=cfg))
    assert rows[0].status == DeliveryStatus.FAILED
    assert "400" in rows[0].last_error


@respx.mock
def test_process_one_pending_5xx_reschedules_with_backoff(
    cfg: Config, workspace_id: str, monkeypatch: pytest.MonkeyPatch
):
    _enqueue_one(cfg, workspace_id)
    respx.post("https://hook/x").mock(return_value=httpx.Response(503))
    base = datetime(2026, 5, 3, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(deliveries, "_now", lambda: base)
    monkeypatch.setattr(worker, "_now", lambda: base)
    assert worker.process_one_pending(config=cfg) is True
    rows = list(deliveries.iter_all(config=cfg))
    assert rows[0].status == DeliveryStatus.PENDING
    assert rows[0].attempts == 1
    # First-failure backoff is 1s.
    assert (rows[0].next_attempt_at - base).total_seconds() == 1.0


@respx.mock
def test_process_one_pending_5xx_then_5xx_doubles_backoff(
    cfg: Config, workspace_id: str, monkeypatch: pytest.MonkeyPatch
):
    """attempts=2 → 4s backoff."""
    _enqueue_one(cfg, workspace_id)
    respx.post("https://hook/x").mock(return_value=httpx.Response(503))
    base = datetime(2026, 5, 3, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(deliveries, "_now", lambda: base)
    monkeypatch.setattr(worker, "_now", lambda: base)
    worker.process_one_pending(config=cfg)
    # Bump time past the first backoff.
    later = datetime(2026, 5, 3, 12, 0, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(deliveries, "_now", lambda: later)
    monkeypatch.setattr(worker, "_now", lambda: later)
    worker.process_one_pending(config=cfg)
    rows = list(deliveries.iter_all(config=cfg))
    assert rows[0].attempts == 2
    assert (rows[0].next_attempt_at - later).total_seconds() == 4.0


@respx.mock
def test_process_one_pending_after_max_attempts_marks_exhausted(
    cfg: Config, workspace_id: str, monkeypatch: pytest.MonkeyPatch
):
    """6 total 5xx → exhausted + transparency event ``webhook.delivery_exhausted``."""
    from datetime import timedelta

    from smadp.transparency import journal

    _enqueue_one(cfg, workspace_id)
    respx.post("https://hook/x").mock(return_value=httpx.Response(503))
    cur = datetime(2026, 5, 3, 12, 0, 0, tzinfo=timezone.utc)

    def _set_now(dt: datetime) -> None:
        monkeypatch.setattr(deliveries, "_now", lambda: dt)
        monkeypatch.setattr(worker, "_now", lambda: dt)

    for _ in range(6):
        _set_now(cur)
        worker.process_one_pending(config=cfg)
        cur += timedelta(seconds=300)

    rows = list(deliveries.iter_all(config=cfg))
    assert rows[0].status == DeliveryStatus.EXHAUSTED
    assert rows[0].attempts == 6

    # Transparency event written.
    types = [ev.event_type for ev in journal.iter_events(config=cfg)]
    assert "webhook.delivery_exhausted" in types


@respx.mock
def test_process_one_pending_network_error_treated_as_5xx(
    cfg: Config, workspace_id: str, monkeypatch: pytest.MonkeyPatch
):
    _enqueue_one(cfg, workspace_id)
    respx.post("https://hook/x").mock(side_effect=httpx.ConnectError("boom"))
    base = datetime(2026, 5, 3, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(deliveries, "_now", lambda: base)
    monkeypatch.setattr(worker, "_now", lambda: base)
    assert worker.process_one_pending(config=cfg) is True
    rows = list(deliveries.iter_all(config=cfg))
    assert rows[0].status == DeliveryStatus.PENDING
    assert rows[0].attempts == 1
    assert "boom" in (rows[0].last_error or "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_webhooks_worker.py -v`
Expected: import error — module doesn't exist.

- [ ] **Step 3: Implement the worker (single-row processor only — loop comes in Task 9)**

Create `smadp/webhooks/worker.py`:

```python
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
from smadp.schemas.webhooks import EventType
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
```

- [ ] **Step 4: Run tests to verify pass**

Run: `.venv/bin/pytest tests/unit/test_webhooks_worker.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add smadp/webhooks/worker.py tests/unit/test_webhooks_worker.py
git commit -m "feat(webhooks): worker process_one_pending + 6-attempt retry + exhaustion transparency event"
```

---

## Task 9: Worker `__main__` entry point + CLI subgroup

**Files:**
- Modify: `smadp/webhooks/worker.py` (add `__main__` block)
- Create: `smadp/webhooks/cli.py`
- Modify: `smadp/cli.py` (register `webhook_group`)
- Create: `tests/integration/test_webhooks_cli.py`

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_webhooks_cli.py`:

```python
"""Integration tests for the smadp webhook CLI."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from smadp.cli import cli
from smadp.config import Config
from smadp.schemas.tenancy import Plan
from smadp.schemas.webhooks import EventType
from smadp.tenancy import store as tenancy
from smadp.webhooks import dispatcher, store


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return Config()


@pytest.fixture
def workspace_id(cfg: Config) -> str:
    ws = tenancy.create_workspace(name="CLI", plan=Plan.PUBLIC, config=cfg)
    return ws.id


def test_subscriptions_create_and_ls(cfg: Config, workspace_id: str):
    runner = CliRunner()
    res = runner.invoke(
        cli,
        [
            "webhook", "subscriptions", "create",
            "--workspace", workspace_id,
            "--url", "https://example.com/wh",
            "--event", "passport.generated",
        ],
    )
    assert res.exit_code == 0, res.output
    assert "sub_" in res.output
    assert "secret:" in res.output  # secret printed once

    ls = runner.invoke(
        cli, ["webhook", "subscriptions", "ls", "--workspace", workspace_id]
    )
    assert ls.exit_code == 0, ls.output
    assert "https://example.com/wh" in ls.output


def test_subscriptions_delete(cfg: Config, workspace_id: str):
    sub, _ = store.create_subscription(
        workspace_id=workspace_id, url="https://example.com/wh",
        event_types=[EventType.PASSPORT_GENERATED], config=cfg,
    )
    runner = CliRunner()
    res = runner.invoke(cli, ["webhook", "subscriptions", "delete", sub.id])
    assert res.exit_code == 0, res.output


def test_deliveries_ls_shows_pending_rows(cfg: Config, workspace_id: str):
    store.create_subscription(
        workspace_id=workspace_id, url="https://example.com/wh",
        event_types=[EventType.PASSPORT_GENERATED], config=cfg,
    )
    dispatcher.dispatch_event(
        event_type=EventType.PASSPORT_GENERATED,
        payload={"verdict_id": "vdt_X"},
        workspace_id=workspace_id,
        signature_meta={"transparency_log_id": 1},
        config=cfg,
    )
    runner = CliRunner()
    res = runner.invoke(cli, ["webhook", "deliveries", "ls"])
    assert res.exit_code == 0, res.output
    assert "pending" in res.output
    assert "passport.generated" in res.output


def test_worker_once_no_pending_exits_zero(cfg: Config):
    runner = CliRunner()
    res = runner.invoke(cli, ["webhook", "worker", "--once"])
    assert res.exit_code == 0
    assert "no pending deliveries" in res.output.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/integration/test_webhooks_cli.py -v`
Expected: 4 failures (no `webhook` subgroup).

- [ ] **Step 3: Add `__main__` to worker**

Append to `smadp/webhooks/worker.py` (BELOW the `__all__` block):

```python
def main() -> None:
    """``python -m smadp.webhooks.worker`` — runs forever."""
    log.info("webhooks.worker.starting")
    run_loop()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Implement the CLI subgroup**

Create `smadp/webhooks/cli.py`:

```python
"""Click subcommands for webhooks: subscriptions ls/create/delete, deliveries ls, worker."""

from __future__ import annotations

import sys

import click
from rich.console import Console
from rich.table import Table

from smadp.config import load_config
from smadp.schemas.webhooks import EventType
from smadp.webhooks import deliveries, store, worker

console = Console()


@click.group(name="webhook")
def webhook_group() -> None:
    """Manage webhook subscriptions, view deliveries, run the delivery worker."""


# --- subscriptions ---------------------------------------------------------

@webhook_group.group(name="subscriptions")
def subscriptions_group() -> None:
    """Create / list / delete webhook subscriptions."""


@subscriptions_group.command(name="create")
@click.option("--workspace", "workspace_id", required=True, help="Workspace id.")
@click.option("--url", required=True, help="HTTPS URL to POST events to.")
@click.option(
    "--event",
    "events",
    multiple=True,
    required=True,
    help="Event type to subscribe to (repeatable).",
)
def subscriptions_create(workspace_id: str, url: str, events: tuple[str, ...]) -> None:
    cfg = load_config()
    try:
        event_types = [EventType(e) for e in events]
    except ValueError as exc:
        console.print(f"[red]invalid event type:[/red] {exc}")
        sys.exit(2)
    sub, secret = store.create_subscription(
        workspace_id=workspace_id, url=url, event_types=event_types, config=cfg
    )
    console.print(f"[green]created[/green] {sub.id}")
    console.print(f"  url:    {sub.url}")
    console.print(f"  events: {', '.join(t.value for t in sub.event_types)}")
    console.print(f"  secret: [bold]{secret}[/bold]   (shown once — save it now)")


@subscriptions_group.command(name="ls")
@click.option("--workspace", "workspace_id", required=True, help="Workspace id.")
def subscriptions_ls(workspace_id: str) -> None:
    cfg = load_config()
    rows = store.list_subscriptions(workspace_id=workspace_id, config=cfg)
    if not rows:
        console.print("[yellow]no subscriptions[/yellow]")
        return
    t = Table(title=f"Subscriptions for {workspace_id}")
    t.add_column("id")
    t.add_column("url", overflow="fold")
    t.add_column("events")
    t.add_column("active")
    for s in rows:
        t.add_row(
            s.id,
            s.url,
            ", ".join(e.value for e in s.event_types),
            "yes" if s.active else "no",
        )
    console.print(t)


@subscriptions_group.command(name="delete")
@click.argument("subscription_id")
def subscriptions_delete(subscription_id: str) -> None:
    cfg = load_config()
    try:
        store.deactivate_subscription(subscription_id=subscription_id, config=cfg)
    except KeyError as exc:
        console.print(f"[red]{exc}[/red]")
        sys.exit(2)
    console.print(f"[green]deactivated[/green] {subscription_id}")


# --- deliveries ------------------------------------------------------------

@webhook_group.group(name="deliveries")
def deliveries_group() -> None:
    """Inspect webhook delivery rows."""


@deliveries_group.command(name="ls")
@click.option("--limit", default=50, type=int)
def deliveries_ls(limit: int) -> None:
    cfg = load_config()
    rows = list(deliveries.iter_all(config=cfg))[-limit:]
    if not rows:
        console.print("[yellow]no deliveries[/yellow]")
        return
    t = Table(title=f"Webhook deliveries (last {len(rows)})")
    t.add_column("id")
    t.add_column("event_type")
    t.add_column("status")
    t.add_column("attempts")
    t.add_column("subscription")
    t.add_column("error", overflow="fold")
    for d in rows:
        t.add_row(
            d.id,
            d.event_type.value,
            d.status.value,
            str(d.attempts),
            d.subscription_id,
            d.last_error or "-",
        )
    console.print(t)


# --- worker ----------------------------------------------------------------

@webhook_group.command(name="worker")
@click.option("--once", is_flag=True, help="Process one pending row, then exit.")
@click.option(
    "--max-iterations",
    type=int,
    default=None,
    help="Bound the loop (for tests/CI).",
)
def worker_cmd(once: bool, max_iterations: int | None) -> None:
    cfg = load_config()
    if once:
        did = worker.process_one_pending(config=cfg)
        if did:
            console.print("[green]processed one delivery[/green]")
        else:
            console.print("[yellow]no pending deliveries[/yellow]")
        return
    n = worker.run_loop(config=cfg, max_iterations=max_iterations)
    console.print(f"[green]processed {n} deliveries[/green]")


__all__ = ["webhook_group"]
```

Modify `smadp/cli.py` — add the import next to `passport_group` (around line 29) and the registration next to `cli.add_command(passport_group)` (around line 637). Final additions:

```python
from smadp.webhooks.cli import webhook_group
...
cli.add_command(webhook_group)
```

- [ ] **Step 5: Run tests to verify pass**

Run: `.venv/bin/pytest tests/integration/test_webhooks_cli.py -v`
Expected: 4 passed.

- [ ] **Step 6: Manual smoke**

Run: `.venv/bin/python -m smadp.cli webhook --help`
Expected: shows `subscriptions`, `deliveries`, `worker` subcommands.

Run: `.venv/bin/python -m smadp.webhooks.worker --help` 
Expected: error or hangs (no Click). That's fine — `python -m` runs `main()` which loops; abort with Ctrl-C. (Don't actually run it without `--once`; use `smadp webhook worker --once` for testing.)

- [ ] **Step 7: Commit**

```bash
git add smadp/webhooks/worker.py smadp/webhooks/cli.py smadp/cli.py tests/integration/test_webhooks_cli.py
git commit -m "feat(cli): smadp webhook subscriptions/deliveries/worker + python -m smadp.webhooks.worker"
```

---

## Task 10: Wire dispatcher into passport renderer

**Files:**
- Modify: `smadp/passport/render.py` (call `dispatcher.dispatch_event(...)` after the transparency event)
- Create: `tests/integration/test_passport_fires_webhook.py`

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_passport_fires_webhook.py`:

```python
"""Passport renders MUST fire a passport.generated webhook event."""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from smadp.config import Config
from smadp.passport.render import render_passport
from smadp.schemas.passport import SigningStrategy
from smadp.schemas.tenancy import Plan
from smadp.schemas.webhooks import DeliveryStatus, EventType
from smadp.tenancy import keys, store as tenancy
from smadp.webhooks import deliveries, store


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return Config()


@pytest.fixture
def workspace_id(cfg: Config) -> str:
    ws = tenancy.create_workspace(name="W", plan=Plan.PUBLIC, config=cfg)
    keys.upload_signing_key(
        workspace_id=ws.id, private_key=Ed25519PrivateKey.generate(), config=cfg
    )
    return ws.id


def test_render_passport_enqueues_one_delivery_per_matching_subscription(
    cfg: Config, workspace_id: str
):
    store.create_subscription(
        workspace_id=workspace_id, url="https://a/wh",
        event_types=[EventType.PASSPORT_GENERATED], config=cfg,
    )
    store.create_subscription(
        workspace_id=workspace_id, url="https://b/wh",
        event_types=[EventType.PASSPORT_GENERATED], config=cfg,
    )
    render_passport(
        verdict={
            "verdict_id": "vdt_FIRE",
            "pair": ["a/x", "b/y"],
            "headline": "Fire",
            "composite_score": 0.5,
            "framework_mappings": {},
        },
        frameworks={},
        evidence_index={},
        evidence_blobs={},
        signing_strategy=SigningStrategy.BYOK,
        workspace_id=workspace_id,
        rendered_at="2026-05-03T12:00:00Z",
        config=cfg,
    )
    rows = list(deliveries.iter_all(config=cfg))
    assert len(rows) == 2
    assert {r.event_type for r in rows} == {EventType.PASSPORT_GENERATED}
    assert {r.status for r in rows} == {DeliveryStatus.PENDING}


def test_render_passport_with_no_subscriptions_writes_zero_rows(
    cfg: Config, workspace_id: str
):
    render_passport(
        verdict={
            "verdict_id": "vdt_X",
            "pair": ["a/x", "b/y"],
            "headline": "X",
            "composite_score": 0.5,
            "framework_mappings": {},
        },
        frameworks={},
        evidence_index={},
        evidence_blobs={},
        signing_strategy=SigningStrategy.BYOK,
        workspace_id=workspace_id,
        rendered_at="2026-05-03T12:00:00Z",
        config=cfg,
    )
    assert list(deliveries.iter_all(config=cfg)) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/integration/test_passport_fires_webhook.py -v`
Expected: `test_render_passport_enqueues_one_delivery_per_matching_subscription` fails (0 rows ≠ 2). The second test passes vacuously.

- [ ] **Step 3: Wire the dispatcher into render_passport**

In `smadp/passport/render.py`, add the import next to the existing `from smadp.transparency import journal` line:

```python
from smadp.webhooks import dispatcher
from smadp.schemas.webhooks import EventType as _WebhookEventType
```

Inside `render_passport(...)`, immediately AFTER the `transparency_event = journal.append_event(...)` block (about line 146 in the current file), add:

```python
    # Fire passport.generated webhook to all matching subscriptions.
    # The transparency event id is the binding between log and webhook.
    dispatcher.dispatch_event(
        event_type=_WebhookEventType.PASSPORT_GENERATED,
        payload={
            "verdict_id": verdict.get("verdict_id"),
            "workspace_id": workspace_id,
            "canonical_sha256": canonical_sha,
            "signing_strategy": signing_strategy.value,
        },
        workspace_id=workspace_id,
        signature_meta={
            "transparency_log_id": transparency_event.id,
            "prev_event_hash": transparency_event.prev_hash,
        },
        config=cfg,
    )
```

- [ ] **Step 4: Run tests to verify pass**

Run: `.venv/bin/pytest tests/integration/test_passport_fires_webhook.py -v`
Expected: 2 passed.

Also re-run the existing passport suite to confirm no regression:

Run: `.venv/bin/pytest tests/integration/test_passport_render_full.py tests/integration/test_passport_e2e.py tests/integration/test_passport_sigstore_deferred.py -v`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add smadp/passport/render.py tests/integration/test_passport_fires_webhook.py
git commit -m "feat(passport): fire passport.generated webhook after transparency event"
```

---

## Task 11: Integration — full lifecycle (subscribe → render → worker delivers)

**Files:**
- Create: `tests/integration/test_webhook_full_lifecycle.py`

- [ ] **Step 1: Write the test**

Create `tests/integration/test_webhook_full_lifecycle.py`:

```python
"""End-to-end webhook lifecycle: render passport → worker delivers signed POST."""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

import httpx
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from smadp.config import Config
from smadp.passport.render import render_passport
from smadp.schemas.passport import SigningStrategy
from smadp.schemas.tenancy import Plan
from smadp.schemas.webhooks import DeliveryStatus, EventType
from smadp.tenancy import keys, store as tenancy
from smadp.webhooks import deliveries, store, worker


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return Config()


@respx.mock
def test_full_lifecycle_subscribe_render_deliver(cfg: Config):
    # 1. workspace + BYOK
    ws = tenancy.create_workspace(name="L", plan=Plan.PUBLIC, config=cfg)
    keys.upload_signing_key(
        workspace_id=ws.id, private_key=Ed25519PrivateKey.generate(), config=cfg
    )

    # 2. subscribe
    sub, secret = store.create_subscription(
        workspace_id=ws.id, url="https://hook/x",
        event_types=[EventType.PASSPORT_GENERATED], config=cfg,
    )

    # 3. mock the subscriber
    captured: dict[str, str] = {}

    def _capture(req: httpx.Request) -> httpx.Response:
        captured["sig"] = req.headers["X-SMADP-Signature"]
        captured["delivery_id"] = req.headers["X-SMADP-Delivery-Id"]
        captured["event_type"] = req.headers["X-SMADP-Event-Type"]
        captured["body"] = req.content.decode("utf-8")
        return httpx.Response(200)

    respx.post("https://hook/x").mock(side_effect=_capture)

    # 4. render passport (this fires the dispatch)
    render_passport(
        verdict={
            "verdict_id": "vdt_LIFECYCLE",
            "pair": ["a/x", "b/y"],
            "headline": "L",
            "composite_score": 0.5,
            "framework_mappings": {},
        },
        frameworks={},
        evidence_index={},
        evidence_blobs={},
        signing_strategy=SigningStrategy.BYOK,
        workspace_id=ws.id,
        rendered_at="2026-05-03T12:00:00Z",
        config=cfg,
    )

    # 5. before worker runs, row exists pending
    rows_before = list(deliveries.iter_all(config=cfg))
    assert len(rows_before) == 1
    assert rows_before[0].status == DeliveryStatus.PENDING

    # 6. worker consumes the row
    assert worker.process_one_pending(config=cfg) is True

    rows_after = list(deliveries.iter_all(config=cfg))
    assert rows_after[0].status == DeliveryStatus.DELIVERED
    assert rows_after[0].delivered_at is not None

    # 7. signature matches
    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"), captured["body"].encode("utf-8"), hashlib.sha256
    ).hexdigest()
    assert captured["sig"] == expected
    assert captured["event_type"] == "passport.generated"
    assert captured["delivery_id"].startswith("wd_")
    # Body contains the verdict id and transparency_log_id binding
    assert "vdt_LIFECYCLE" in captured["body"]
    assert '"transparency_log_id":' in captured["body"]
```

- [ ] **Step 2: Run — expect pass**

Run: `.venv/bin/pytest tests/integration/test_webhook_full_lifecycle.py -v`
Expected: 1 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_webhook_full_lifecycle.py
git commit -m "test(webhooks): end-to-end lifecycle render -> dispatch -> worker -> signed POST"
```

---

## Task 12: Integration — 5xx forever → exhausted + transparency event

**Files:**
- Create: `tests/integration/test_webhook_retry_exhaust.py`

- [ ] **Step 1: Write the test**

Create `tests/integration/test_webhook_retry_exhaust.py`:

```python
"""5xx forever -> 6 attempts -> exhausted + webhook.delivery_exhausted journal entry."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from smadp.config import Config
from smadp.schemas.tenancy import Plan
from smadp.schemas.webhooks import DeliveryStatus, EventType
from smadp.tenancy import keys, store as tenancy
from smadp.transparency import journal
from smadp.webhooks import deliveries, dispatcher, store, worker


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return Config()


@respx.mock
def test_503_forever_marks_exhausted_and_writes_transparency_event(
    cfg: Config, monkeypatch: pytest.MonkeyPatch
):
    ws = tenancy.create_workspace(name="X", plan=Plan.PUBLIC, config=cfg)
    keys.upload_signing_key(
        workspace_id=ws.id, private_key=Ed25519PrivateKey.generate(), config=cfg
    )
    store.create_subscription(
        workspace_id=ws.id, url="https://hook/x",
        event_types=[EventType.PASSPORT_GENERATED], config=cfg,
    )
    dispatcher.dispatch_event(
        event_type=EventType.PASSPORT_GENERATED,
        payload={"verdict_id": "vdt_X"},
        workspace_id=ws.id,
        signature_meta={"transparency_log_id": 1},
        config=cfg,
    )
    respx.post("https://hook/x").mock(return_value=httpx.Response(503))

    cur = datetime(2026, 5, 3, 12, 0, 0, tzinfo=timezone.utc)

    def _set_now(dt: datetime) -> None:
        monkeypatch.setattr(deliveries, "_now", lambda: dt)
        monkeypatch.setattr(worker, "_now", lambda: dt)

    for _ in range(6):
        _set_now(cur)
        assert worker.process_one_pending(config=cfg) is True
        cur += timedelta(seconds=300)

    rows = list(deliveries.iter_all(config=cfg))
    assert len(rows) == 1
    assert rows[0].status == DeliveryStatus.EXHAUSTED
    assert rows[0].attempts == 6

    types = [ev.event_type for ev in journal.iter_events(config=cfg)]
    assert "webhook.delivery_exhausted" in types
```

- [ ] **Step 2: Run — expect pass**

Run: `.venv/bin/pytest tests/integration/test_webhook_retry_exhaust.py -v`
Expected: 1 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_webhook_retry_exhaust.py
git commit -m "test(webhooks): 503 forever -> 6 attempts -> exhausted + transparency event"
```

---

## Task 13: Integration — 4xx → failed (no retry)

**Files:**
- Create: `tests/integration/test_webhook_4xx_no_retry.py`

- [ ] **Step 1: Write the test**

Create `tests/integration/test_webhook_4xx_no_retry.py`:

```python
"""4xx response marks delivery failed without retry; no extra rows enqueued."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from smadp.config import Config
from smadp.schemas.tenancy import Plan
from smadp.schemas.webhooks import DeliveryStatus, EventType
from smadp.tenancy import keys, store as tenancy
from smadp.webhooks import deliveries, dispatcher, store, worker


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return Config()


@respx.mock
def test_400_marks_failed_no_retry(cfg: Config):
    ws = tenancy.create_workspace(name="X", plan=Plan.PUBLIC, config=cfg)
    keys.upload_signing_key(
        workspace_id=ws.id, private_key=Ed25519PrivateKey.generate(), config=cfg
    )
    store.create_subscription(
        workspace_id=ws.id, url="https://hook/x",
        event_types=[EventType.PASSPORT_GENERATED], config=cfg,
    )
    dispatcher.dispatch_event(
        event_type=EventType.PASSPORT_GENERATED,
        payload={"verdict_id": "vdt_X"},
        workspace_id=ws.id,
        signature_meta={"transparency_log_id": 1},
        config=cfg,
    )
    route = respx.post("https://hook/x").mock(return_value=httpx.Response(400, text="bad"))

    assert worker.process_one_pending(config=cfg) is True
    rows = list(deliveries.iter_all(config=cfg))
    assert rows[0].status == DeliveryStatus.FAILED
    assert "400" in rows[0].last_error
    assert rows[0].attempts == 1

    # Calling again does NOT re-attempt — the row is terminal.
    assert worker.process_one_pending(config=cfg) is False
    assert route.call_count == 1
```

- [ ] **Step 2: Run — expect pass**

Run: `.venv/bin/pytest tests/integration/test_webhook_4xx_no_retry.py -v`
Expected: 1 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_webhook_4xx_no_retry.py
git commit -m "test(webhooks): 4xx -> failed (no retry, no further attempts)"
```

---

## Task 14: Golden — webhook envelope JSON byte-stable for fixed input

**Files:**
- Create: `tests/golden/test_webhook_envelope_golden.py`

- [ ] **Step 1: Write the test**

Create `tests/golden/test_webhook_envelope_golden.py`:

```python
"""Golden test: WebhookEnvelope canonical bytes are byte-stable for fixed input."""

from __future__ import annotations

from datetime import datetime, timezone

from smadp.schemas.webhooks import EventType
from smadp.webhooks.envelope import build_envelope, canonical_envelope_bytes


_FIXED_ARGS = dict(
    event_id="evt_20260503120000_abc123",
    event_type=EventType.PASSPORT_GENERATED,
    created_at=datetime(2026, 5, 3, 12, 0, 0, tzinfo=timezone.utc),
    workspace_id="ws_GOLDEN12",
    data={
        "verdict_id": "vdt_GOLDEN",
        "agent_pair": ["anthropic/claude", "openai/gpt"],
        "composite_score": 0.42,
        "trigger": "model_bump",
    },
    signature_meta={
        "transparency_log_id": 7,
        "prev_event_hash": "sha256:" + "0" * 64,
    },
)


_EXPECTED = (
    b'{"created_at":"2026-05-03T12:00:00Z","data":'
    b'{"agent_pair":["anthropic/claude","openai/gpt"],'
    b'"composite_score":0.42,"trigger":"model_bump","verdict_id":"vdt_GOLDEN"},'
    b'"id":"evt_20260503120000_abc123","signature_meta":'
    b'{"prev_event_hash":"sha256:00000000000000000000000000000000'
    b'00000000000000000000000000000000","transparency_log_id":7},'
    b'"type":"passport.generated","workspace_id":"ws_GOLDEN12"}'
)


def test_envelope_bytes_match_golden_fixture():
    actual = canonical_envelope_bytes(build_envelope(**_FIXED_ARGS))
    assert actual == _EXPECTED


def test_envelope_bytes_stable_across_calls():
    a = canonical_envelope_bytes(build_envelope(**_FIXED_ARGS))
    b = canonical_envelope_bytes(build_envelope(**_FIXED_ARGS))
    assert a == b
```

- [ ] **Step 2: Run — expect pass**

Run: `.venv/bin/pytest tests/golden/test_webhook_envelope_golden.py -v`
Expected: 2 passed.

If `_EXPECTED` is off by a comma/quote because Pydantic emits the datetime slightly differently (e.g. trailing `+00:00` vs `Z`), inspect the actual output and update `_EXPECTED` to match — this is the **first** byte-stable run, so adjusting once is OK; the second test guards every run thereafter.

- [ ] **Step 3: Commit**

```bash
git add tests/golden/test_webhook_envelope_golden.py
git commit -m "test(webhooks): golden envelope bytes for fixed input (sorted keys, compact)"
```

---

## Task 15: CI smoke — passport render → worker --once

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Inspect existing CI**

Run: `cat .github/workflows/ci.yml`

Plan 2 added a "Smoke — passport render + verify" step. We add one MORE step AFTER it (and BEFORE Catalog lint): subscribe a webhook → render passport → worker `--once` → assert `delivered`.

The mock subscriber will be a temporary FastAPI/uvicorn instance? No — too heavy for CI. Instead we'll use a Python `BaseHTTPRequestHandler` in a background thread.

- [ ] **Step 2: Add the smoke step**

Insert this YAML step in the `python` job, immediately AFTER the existing `Smoke — passport render + verify` step and BEFORE `Catalog lint`:

```yaml
      - name: Smoke — webhook full lifecycle
        env:
          SMADP_CACHE_DIR: ${{ runner.temp }}/smadp-webhook-ci
          SMADP_KEK_MASTER: "0000000000000000000000000000000000000000000000000000000000000000"
        run: |
          python - <<'PY'
          import threading
          from http.server import BaseHTTPRequestHandler, HTTPServer
          from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

          received = []

          class Handler(BaseHTTPRequestHandler):
              def do_POST(self):
                  length = int(self.headers.get('content-length', 0))
                  body = self.rfile.read(length)
                  received.append({
                      'sig': self.headers.get('X-SMADP-Signature'),
                      'event': self.headers.get('X-SMADP-Event-Type'),
                      'delivery_id': self.headers.get('X-SMADP-Delivery-Id'),
                      'body_len': len(body),
                  })
                  self.send_response(200)
                  self.end_headers()

              def log_message(self, *a, **k):
                  return

          server = HTTPServer(('127.0.0.1', 0), Handler)
          port = server.server_address[1]
          t = threading.Thread(target=server.serve_forever, daemon=True)
          t.start()

          from smadp.config import Config
          from smadp.passport.render import render_passport
          from smadp.schemas.passport import SigningStrategy
          from smadp.schemas.tenancy import Plan
          from smadp.schemas.webhooks import EventType
          from smadp.tenancy import keys, store as tenancy
          from smadp.webhooks import deliveries, store, worker

          cfg = Config()
          ws = tenancy.create_workspace(name='ci', plan=Plan.PUBLIC, config=cfg)
          keys.upload_signing_key(workspace_id=ws.id, private_key=Ed25519PrivateKey.generate(), config=cfg)
          store.create_subscription(
              workspace_id=ws.id, url=f'http://127.0.0.1:{port}/wh',
              event_types=[EventType.PASSPORT_GENERATED], config=cfg,
          )
          render_passport(
              verdict={'verdict_id':'vdt_ci','pair':['a/x','b/y'],'headline':'ci','composite_score':0.5,'framework_mappings':{}},
              frameworks={}, evidence_index={}, evidence_blobs={},
              signing_strategy=SigningStrategy.BYOK,
              workspace_id=ws.id, rendered_at='2026-05-03T00:00:00Z', config=cfg,
          )
          assert worker.process_one_pending(config=cfg) is True
          rows = list(deliveries.iter_all(config=cfg))
          assert rows[0].status.value == 'delivered', rows[0].status.value
          assert received and received[0]['event'] == 'passport.generated'
          assert received[0]['sig'].startswith('sha256=')
          print('OK: webhook delivered to', f'http://127.0.0.1:{port}/wh')
          server.shutdown()
          PY
```

- [ ] **Step 3: Verify YAML parses**

Run: `.venv/bin/python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"`
Expected: no error.

- [ ] **Step 4: Local smoke (optional but recommended)**

Save the script body to `/tmp/smadp_wh_smoke.py` (manually copy from the YAML, dropping the YAML indentation — keep just the Python). Then:

```bash
SMADP_CACHE_DIR=/tmp/smadp-task15-webhook SMADP_KEK_MASTER=0000000000000000000000000000000000000000000000000000000000000000 .venv/bin/python /tmp/smadp_wh_smoke.py
```

Expected: prints `OK: webhook delivered to http://127.0.0.1:<port>/wh`. Exit 0.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: smoke-test webhook full lifecycle (subscribe + render + worker --once)"
```

- [ ] **Step 6: DO NOT push**

Push happens after the final-sweep task.

---

## Task 16: Spec coverage cross-check (no code, just verify)

**Files:** none

This task does NOT change any files. It is a focused re-read of the spec sections this plan claims to cover, ticking each off.

- [ ] **Step 1: Spec §6.4 (`smadp.webhooks.api`)**
  - CRUD on subscriptions: ✓ (Task 4 — POST/GET/DELETE; PATCH not in spec)
  - `dispatch_event(event_type, payload, workspace_id)`: ✓ (Task 7 — added required `signature_meta` kwarg, documented in Pre-flight)

- [ ] **Step 2: Spec §6.5 (`smadp.webhooks.worker`)**
  - separate process: ✓ (Task 9 `__main__`)
  - polls `webhook_deliveries`: ✓ (Task 8 `process_one_pending` + `run_loop`)
  - signs and POSTs: ✓ (Task 8 — HMAC + httpx)
  - exponential backoff (1s/4s/16s/64s/256s, then `exhausted`): ✓ (Task 8 `_BACKOFFS_SECONDS` + `_MAX_ATTEMPTS=6`)
  - `python -m smadp.webhooks.worker` entry: ✓ (Task 9 `main()`)

- [ ] **Step 3: Spec §7.3 (webhook delivery flow)**
  - `SELECT * FROM webhook_deliveries WHERE status='pending' AND next_attempt_at <= now`: ✓ (Task 6 `claim_pending`)
  - `BEGIN IMMEDIATE`: ✓ (Tasks 5/6 `_transaction`)
  - `sig = HMAC-SHA256(subscription.secret, body)`: ✓ (Task 8)
  - headers `X-SMADP-Event/X-SMADP-Signature/X-SMADP-Delivery-Id`: ✓ (Task 8 — header names use `X-SMADP-Event-Type` per spec §8.4 "Headers on POST")
  - on 2xx: status='delivered': ✓
  - on 4xx (no retry): status='failed': ✓
  - on 5xx/timeout: backoff + retry: ✓
  - if attempts ≥ 5: status='exhausted', transparency event written: ✓ (we use 6 total attempts per Pre-flight; transparency event written in Task 8 `_emit_exhausted_transparency_event`)

- [ ] **Step 4: Spec §8.1 (subscriptions, webhook_deliveries tables)**
  - `subscriptions(id, workspace_id, url, secret_hash, event_types JSON, active, created_at)`: **deviation** — column `secret_hash` replaced with `secret_encrypted` + `nonce` because HMAC needs raw secret at delivery time (documented in Pre-flight § Storage choice).
  - `webhook_deliveries(id, subscription_id, event_id, body, status, attempts, next_attempt_at, last_error, created_at, delivered_at)` + INDEX(status, next_attempt_at): ✓ (Task 5; we added `event_type` column for cheap CLI display, doesn't conflict)

- [ ] **Step 5: Spec §8.3 (webhook schemas)**
  - `Subscription`, `EventType`, `WebhookDelivery`, `WebhookEnvelope`: ✓ (Task 1)

- [ ] **Step 6: Spec §8.4 (envelope shape)**
  - keys `id, type, created_at, workspace_id, data, signature_meta`: ✓ (Task 1 model + Task 2 builder + Task 14 golden)
  - Headers `X-SMADP-Signature: sha256=<hmac>`, `X-SMADP-Delivery-Id`, `X-SMADP-Event-Type`: ✓ (Task 8)

- [ ] **Step 7: Spec §9 failure modes**
  - "Outbound webhook delivery: 5 retries with exponential backoff, exhausted writes transparency event, exhausted does not block subsequent deliveries": ✓ (Task 8 + Task 12)
  - "Concurrency on queue claims: BEGIN IMMEDIATE + UPDATE WHERE status='pending'": ✓ (Task 6 — but we use SELECT-then-UPDATE-WHERE-status='pending' instead of UPDATE...RETURNING; sqlite3 in stdlib supports both, the SELECT-then-UPDATE form is identical under BEGIN IMMEDIATE locking)

- [ ] **Step 8: Spec §10.1 unit (`webhooks.api`, `webhooks.worker`)**
  - subscription matching: ✓ (Task 7 dispatcher tests)
  - dispatcher enqueues correctly: ✓
  - HMAC matches hand-computed reference: ✓ (Tasks 2 + 8 + 11)
  - retry/backoff timing: ✓ (Tasks 8 + 12 — using monkeypatch over `_now`, not freezegun, to avoid adding a dep)
  - 4xx → no retry: ✓ (Tasks 8 + 13)
  - 5xx → retry: ✓ (Tasks 8 + 12)
  - >5 → exhausted: ✓ (Tasks 8 + 12 — actually 6 total attempts per Pre-flight)
  - idempotency on duplicate claim: ✓ (Task 6 `test_claim_pending_does_not_double_claim`)

- [ ] **Step 9: Spec §10.2 integration**
  - Full webhook lifecycle: ✓ (Task 11)

- [ ] **Step 10: Spec §10.3 golden**
  - Webhook envelope JSON for each of the 6 event types: **partial** — Task 14 covers `passport.generated` only. The other 5 are reserved for the plans that emit them; their envelope shape is identical (only `type` differs). Skipping individual goldens for the unfired event types is acceptable scope for Plan 3.

- [ ] **Step 11: Scope cuts (acknowledged)**
  - `verdict.created/updated/expired/framework_coverage.changed/passport.revoked` event firing — Plans 4 & 5.
  - Native integrations (`smadp.integrations.{vanta,drata,slack}`) — Plan 4 (vendor flows / integrations).
  - PATCH /subscriptions to update url/event_types — out of scope for Plan 3 (delete-and-recreate is fine for v2-D).
  - `signed_events.workspace_id` association for the exhausted-event signing key — Plan 3 looks up via subscription → workspace → BYOK key; works for Plan 3's use case.

- [ ] **Step 12: No commit (this is documentation-only review)**

---

## Task 17: Final sweep — lint, format, mypy, full test suite

**Files:**
- Possibly modify any file flagged by the linters

- [ ] **Step 1: Run ruff lint**

Run: `.venv/bin/ruff check smadp tests`
Expected: 0 issues. If issues found, fix and re-run.

- [ ] **Step 2: Run ruff format check**

Run: `.venv/bin/ruff format --check smadp tests`
Expected: 0 changes needed. If changes needed: `.venv/bin/ruff format smadp tests` then commit as `style: ruff format`.

- [ ] **Step 3: Run mypy**

Run: `.venv/bin/mypy smadp`
Expected: no errors.

If mypy flags `smadp.webhooks.cli`, `smadp.webhooks.api`, or `smadp.webhooks.worker` for typing oddities in CLI or worker glue (typical for these surfaces), add them to the `[[tool.mypy.overrides]]` block in `pyproject.toml` alongside the existing `smadp.cli`/`smadp.api.routes.*` entries — same `disable_error_code` list. Document the rationale in an inline comment matching the existing v1.1-wiring note.

- [ ] **Step 4: Run the full test suite**

Run: `.venv/bin/pytest -ra`
Expected: all tests pass. New tests added in Plan 3 ≈ 50 (8+4+8+6+11+5+7+4+2+1+1+2 + integration & golden = ~60). Total roughly 365+.

- [ ] **Step 5: Commit any sweep fixes**

If sweep surfaced fixes, commit as `chore(plan3): final sweep — lint/format/mypy fixes` with a short body explaining what was changed.

- [ ] **Step 6: Push**

```bash
git push
gh run watch
```

Expected: CI green for Python 3.11, 3.12, and Dashboard build. Plan 3 ships when CI is green.

---

## Task 18: Self-review checklist

This is the engineer's own checklist — read it, tick each item, do not invoke a subagent for it.

- [ ] **Spec coverage check** — Task 16 is the explicit cross-check.
- [ ] **All tasks committed individually** — `git log --oneline` shows TDD discipline (test commit + impl commit per task is fine; the plan commits them together in a single task-final commit).
- [ ] **No `# TODO`/`# FIXME` in shipped code** — grep `smadp/webhooks/` for these markers; none should remain.
- [ ] **No real network calls in tests** — every outbound call is `respx`-mocked OR uses a 127.0.0.1 mock server.
- [ ] **No raw secret in API list-response** — confirm by re-reading Task 4's `list_subscriptions` route: returns `list[Subscription]` which has no secret field.

---

**Plan 3 ships when CI is green and all 17 build tasks (1–15 + 17) are merged. Plan 4 (Vendor flows + native integrations) can begin immediately and will:**
- Wire `smadp.vendor.{claim,response,dispute}` against the existing transparency log and tenancy layer.
- Add `smadp.integrations.{vanta,drata,slack}` adapters that translate the generic envelope into vendor-native API calls.
- Plug those adapters into the dispatcher so a subscription with `target=vanta|drata|slack` writes the translated body into the queue.
