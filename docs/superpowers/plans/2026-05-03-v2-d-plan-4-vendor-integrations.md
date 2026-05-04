# SMADP v2-D Plan 4 — Vendor Flows + Native Integrations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the v2-D vendor surface — `smadp.vendor.{store,verifier,api,cli}` for claim/response/dispute lifecycles — and the native-integration adapters `smadp.integrations.{vanta,drata,slack}` that translate the generic webhook envelope into vendor-specific payloads, plus the dispatcher/worker wiring that lets a single subscription target a native kind.

**Architecture:** Vendor data lives in a per-instance SQLite file (`<cache_dir>/vendor.db`, WAL, `BEGIN IMMEDIATE`) and binds to the existing `tenancy` workspace + member identity (no separate "vendor user" model). Three claim verification methods (repo file, DNS TXT, email magic-link) sit behind a uniform `verify(claim, evidence) -> ClaimVerification` interface; each method is a small pure function plus its own httpx/dnspython transport. Native integrations are a registry of `Adapter` protocol implementations keyed by `IntegrationKind` (`GENERIC|VANTA|DRATA|SLACK`); the dispatcher calls `adapter.translate(envelope) -> bytes` *before* enqueuing, so the worker stays uniform — only the body shape and a small `headers` overlay differ per kind. Subscriptions gain two nullable columns (`integration_kind`, `integration_config`) added via `ALTER TABLE` in `webhooks/store.py`.

**Tech Stack:** Python 3.11/3.12, FastAPI (existing), Click (existing), httpx **sync** Client (existing convention), Pydantic v2 (`extra="forbid"`), SQLite WAL, `cryptography` AES-GCM/HKDF (existing BYOK helpers — vendor data does NOT need encryption-at-rest beyond what already protects tenancy data), `respx` for outbound HTTP mocking, `structlog` for logging. **One new dependency: `dnspython>=2.6` for DNS-TXT verification.**

---

## Pre-flight — design picks (read once, then begin)

These decisions resolve ambiguity in the spec. They are **fixed** for Plan 4; later plans can revisit.

### Vendor identity = workspace member (no separate vendor user model)

Spec §8.1 names the column `vendor_user_id` on `vendor_claims`, `vendor_responses`, `disputes`. We bind that string to **the tenancy `workspace_members.user_id` value** — i.e. the X-SMADP-User header value (FastAPI dep `current_user_id`). There is no separate "vendor users" table. Promotion to "verified vendor for agent X" is the existence of a `vendor_claims` row with `status='verified'` for `(agent_id, vendor_user_id)` in the caller's current workspace.

Authorization for vendor endpoints requires:
1. The caller passes `current_workspace` (X-SMADP-Workspace) — same dep used by webhooks.
2. The caller has at least `editor` role in that workspace (uses `tenancy.deps.require_role(Role.EDITOR)`).
3. For verify/edit/dispute endpoints, the caller's `(workspace_id, user_id, agent_id)` triple maps to a verified claim (enforced inline in the route, not as a dep).

### Agent ID format = catalog slug

`agent_id` is the lowercase basename of `catalog/profiles/<slug>.json` (e.g. `claude-code`, `cursor`). Validated on Pydantic `VendorClaim.agent_id` with `^[a-z0-9][a-z0-9-]{0,63}$`. We do **not** verify the slug exists in the catalog at write time (catalog is read-only at runtime; v2-D Plan 5 will add catalog refresh — until then, an unknown slug just never matches a real verdict).

### Claim id, dispute id, response id formats

Mirror the Plan 3 patterns (sortable timestamp prefix where deliveries care about ordering; uppercase-base32 where they don't):

```
vendor_claims.id      → vc_<8 base32-uppercase>            e.g. vc_AB12CD34
vendor_responses.id   → vr_<14ts>_<6hex>                   e.g. vr_20260503120000_ab12cd
disputes.id           → dsp_<14ts>_<6hex>                  e.g. dsp_20260503120000_ef34gh
```

Helpers `_generate_claim_id()`, `_generate_response_id(now)`, `_generate_dispute_id(now)` live in `smadp/vendor/store.py`. Validated by Pydantic regex on the schemas.

### Claim token

`secrets.token_urlsafe(32)` → 43 ASCII chars. Generated at create-time, returned **once** in the create-claim response (along with method-specific instructions), stored verbatim in the `token` column. Token never expires until the claim is revoked. Verification methods compare token via constant-time `hmac.compare_digest`.

### Repo verification

The vendor declares a base URL at create-time (`evidence.repo_url`, e.g. `https://github.com/foo/bar/raw/main`). Verifier does a single sync `httpx.get(repo_url.rstrip("/") + "/.smadp/owner.txt", timeout=10.0, follow_redirects=True)`. Body is whitespace-stripped and `compare_digest`'d to the stored token. **Two retries with exponential backoff (1s, 4s)** on transport errors only — 4xx/5xx are immediate fail. Per-call status + body are returned in `ClaimVerification.detail` for operator debugging.

### DNS verification

The vendor declares a domain at create-time (`evidence.domain`, e.g. `acme.com`). Verifier resolves `_smadp-owner.<domain>` TXT records via `dns.resolver.Resolver(configure=True)`. Each TXT chunk is decoded UTF-8 + whitespace-stripped; if any chunk equals the token, claim is verified. Resolver `lifetime=10.0` seconds; **no application-level retries** — dnspython retries internally per its own resolver policy. `NXDOMAIN`, `NoAnswer`, `Timeout` → claim_token_mismatch with the exception class name in `detail`.

### Email magic-link verification (no SMTP at this stage)

There is **no SMTP integration in Plan 4**. The flow is:

1. `POST /api/vendor/claims` with `method="email"` and `evidence.email_address` returns the new claim object **plus** a magic-link URL: `https://smadp.example/vendor/claims/{claim_id}/verify?token=<token>`. The host comes from `Config.public_base_url` (new field; defaults to `http://localhost:8000`).
2. The operator delivers the URL out-of-band (manual paste in chat, ops ticket — explicitly noted in CLI/API response).
3. The vendor visits the URL or POSTs `/api/vendor/claims/{id}/verify` with `method="email"` and `evidence.token=<token>`. Verifier `compare_digest`s evidence.token to the stored token.

`Config.public_base_url` (new): `os.environ.get("SMADP_PUBLIC_BASE_URL", "http://localhost:8000")`. Loaded by `Config.__init__`. Self-validation: must be `https://` or `http://localhost*`.

SMTP delivery is deferred to Plan 5 (refresh) or 6 (frontend) — whoever needs it first.

### Dispute state machine

States (StrEnum `DisputeStatus`):

```
TRIAGE              # initial, on POST
PENDING_REVIEW      # operator decided substantive
RESOLVED_REEVAL     # operator says re-eval; we record the decision
RESOLVED_STANDS     # operator says verdict stands
SPAM                # operator dismissed
```

Transitions (enforced by `vendor.store.update_dispute_status`):

```
TRIAGE → PENDING_REVIEW (decision="substantive")
TRIAGE → SPAM           (decision="spam")
PENDING_REVIEW → RESOLVED_REEVAL  (decision="reeval", rationale required)
PENDING_REVIEW → RESOLVED_STANDS  (decision="stands", rationale required)
```

Any other transition raises `ValueError("invalid dispute transition: {old} → {new}")`. **No automated SLA enforcement** in Plan 4 — `triaged_at + 5 business days` is computed and exposed via the API/CLI as `sla_breached_at`, but no badge or paging is wired (those land in Plan 6 frontend). Spec §9 explicitly says "No automated state transition — humans must resolve."

### `requested_outcome` enum

From spec §8.1 column `requested_outcome ENUM('reeval','withdraw','amend')` — modeled as `RequestedOutcome` StrEnum in `smadp/schemas/dispute.py`.

### Refresh integration: deferred to Plan 5

Spec §7.5 says a substantive dispute resolution that picks `reeval` should "trigger §7.1 refresh with trigger='dispute'". Plan 5 owns `smadp.refresh`. Plan 4 records the decision in `disputes.decision_rationale_md` and emits a `dispute.resolved` transparency event with `{"requested_trigger": "dispute"}` in the payload — Plan 5 consumes that. **Do not import refresh from Plan 4.**

### Storage of vendor data

New SQLite file: `<cache_dir>/vendor.db`. Same pragmas (WAL, NORMAL sync, foreign_keys ON). Three tables (`vendor_claims`, `vendor_responses`, `disputes`) — schema in Task 2 / Task 3. Tokens stored in plaintext (they are server-generated nonces, low value alone — verifying still requires control of the corresponding repo/DNS/inbox). The KEK/DEK encryption used by `tenancy/keys.py` and `webhooks/store.py` is **not** used here.

### Native integration architecture

`IntegrationKind` (StrEnum) lives in `smadp/schemas/webhooks.py`:

```python
class IntegrationKind(StrEnum):
    GENERIC = "generic"
    VANTA = "vanta"
    DRATA = "drata"
    SLACK = "slack"
```

`Subscription` (Pydantic) gets two new optional fields:

```python
integration_kind: IntegrationKind = IntegrationKind.GENERIC
integration_config: dict[str, Any] = Field(default_factory=dict)
```

`subscriptions` SQLite table gets two new columns added via idempotent `ALTER TABLE` in `_ensure_schema`:

```sql
ALTER TABLE subscriptions ADD COLUMN integration_kind TEXT NOT NULL DEFAULT 'generic';
ALTER TABLE subscriptions ADD COLUMN integration_config TEXT NOT NULL DEFAULT '{}';
```

`Adapter` Protocol (`smadp/integrations/base.py`):

```python
class Adapter(Protocol):
    kind: IntegrationKind
    def translate(self, envelope: WebhookEnvelope, *, config: Mapping[str, Any]) -> bytes: ...
    def headers(self, envelope: WebhookEnvelope, *, config: Mapping[str, Any]) -> dict[str, str]: ...
```

Registry: `_REGISTRY: dict[IntegrationKind, Adapter]` populated at module import. Function `get_adapter(kind: IntegrationKind) -> Adapter`.

### Dispatcher: pre-translate body per subscription

Plan 3's dispatcher built one canonical `body: bytes` and enqueued it on every matching sub. Plan 4 replaces that with a per-sub body:

```python
for sub in matches:
    if sub.integration_kind == IntegrationKind.GENERIC:
        body = canonical_envelope_bytes(envelope)
        headers_overlay: dict[str, str] = {}
    else:
        adapter = get_adapter(sub.integration_kind)
        body = adapter.translate(envelope, config=sub.integration_config)
        headers_overlay = adapter.headers(envelope, config=sub.integration_config)
    deliveries.enqueue(
        subscription_id=sub.id,
        event_id=event_id,
        event_type=event_type,
        body=body,
        headers_overlay=headers_overlay,
        config=cfg,
    )
```

`webhook_deliveries` table gets one new nullable column added via idempotent `ALTER TABLE`:

```sql
ALTER TABLE webhook_deliveries ADD COLUMN headers_overlay TEXT NOT NULL DEFAULT '{}';
```

### Worker: merge headers_overlay into the POST

Plan 3 worker built fixed headers (`X-SMADP-Signature`, `X-SMADP-Delivery-Id`, `X-SMADP-Event-Type`, `Content-Type: application/json`). Plan 4 adds `headers_overlay` (already-decoded JSON dict from the queue row) **before** signing — the HMAC still binds the body bytes only, never the headers. Overlay keys cannot override the four reserved SMADP headers; conflicts are silently dropped with a `webhooks.worker.header_conflict_dropped` log event.

### HMAC for native integrations

The spec doesn't say. We pick: **the same HMAC contract applies to all kinds.** `X-SMADP-Signature` is computed over the (possibly translated) body bytes that ship in the request. For Vanta/Drata that signature is largely vestigial (their APIs use bearer tokens supplied via `headers_overlay`); for Slack incoming webhooks it is also vestigial. Including it costs nothing and keeps the worker uniform.

### Vanta / Drata / Slack translator shapes

These are **mock-shape** translators — Plan 4 ships the integration *plumbing* with translators whose payload shapes are internally consistent and tested but are not validated against live Vanta/Drata APIs (we do not have credentials in CI; spec §10.5 notes this gating). The shapes match each vendor's published webhook/evidence-upload schema as of Q1 2026; updating them when we have live test access is a Plan 6 follow-up.

- **Vanta** (`smadp/integrations/vanta.py`): POST a JSON evidence-update payload of shape `{"evidenceType": "smadp_passport", "evidenceId": "<verdict_id>", "passedAt": "<created_at>", "metadata": {<envelope.data>}}`. Headers: `Authorization: Bearer <integration_config["token"]>`. Required config keys: `token`, `evidence_request_id`.
- **Drata** (`smadp/integrations/drata.py`): POST `{"controlId": "<integration_config['control_id']>", "evidence": {"verdict_id": ..., "score": ..., "passport_url": ...}, "occurredAt": ...}`. Headers: `Authorization: Bearer <token>`, `X-Drata-Source: smadp`. Required: `token`, `control_id`.
- **Slack** (`smadp/integrations/slack.py`): POST a Block Kit message — header `text` is `"Verdict updated: <pair>"` for verdict events, `"Passport generated for <verdict_id>"` for passport events; blocks include a section with score + a button linking to the passport URL (taken from `envelope.data["passport_url"]` when present, otherwise omitted). No auth headers (Slack incoming webhooks authenticate by URL secret).

Translators **must not** raise on missing optional `data` fields — they degrade to "n/a" strings.

### CLI subgroup

`smadp vendor` subgroup exposed via `cli.add_command(vendor_group)`. Subcommands:

```
smadp vendor claims create  --agent-id ... --method repo|dns|email --evidence ... 
smadp vendor claims ls      [--agent-id ...]
smadp vendor claims verify  CLAIM_ID
smadp vendor claims revoke  CLAIM_ID
smadp vendor responses post --verdict-id ... --body-md ...
smadp vendor disputes file  --verdict-id ... --argument-md ... --requested-outcome reeval|withdraw|amend
smadp vendor disputes triage DISPUTE_ID --decision spam|substantive
smadp vendor disputes resolve DISPUTE_ID --decision reeval|stands --rationale-md ...
smadp vendor disputes ls    [--verdict-id ...]
```

All use `Config()` and `current_workspace` is supplied via `--workspace-id`/`SMADP_WORKSPACE_ID` env. User id supplied via `--user-id`/`SMADP_USER_ID`. Same env-fallback pattern as the existing `tenancy` CLI.

---

## File structure (locked before tasks begin)

| Path | Responsibility |
|------|----------------|
| `smadp/schemas/vendor.py` | `VendorClaim`, `ClaimMethod` enum, `ClaimStatus` enum, `VendorResponse`, `RepoEvidence`, `DnsEvidence`, `EmailEvidence`, `TokenEvidence` (verify-time discriminated union), `ClaimVerification` |
| `smadp/schemas/dispute.py` | `Dispute`, `DisputeStatus` enum, `RequestedOutcome` enum, `DisputeDecision` enum |
| `smadp/vendor/__init__.py` | empty package marker |
| `smadp/vendor/store.py` | claims + responses + disputes CRUD over `<cache_dir>/vendor.db`; id generators; status transition validator |
| `smadp/vendor/verifier.py` | `verify_repo`, `verify_dns`, `verify_email`, `verify(claim, evidence)` dispatch |
| `smadp/vendor/api.py` | `/api/vendor/claims`, `/api/vendor/responses`, `/api/vendor/disputes` routers |
| `smadp/vendor/cli.py` | `smadp vendor` Click subgroup with claims/responses/disputes commands |
| `smadp/integrations/__init__.py` | empty package marker |
| `smadp/integrations/base.py` | `Adapter` Protocol; `_REGISTRY`; `get_adapter(kind)`; `register_adapter(adapter)` |
| `smadp/integrations/generic.py` | `GenericAdapter` (no-op pass-through; canonical envelope bytes) |
| `smadp/integrations/vanta.py` | `VantaAdapter` |
| `smadp/integrations/drata.py` | `DrataAdapter` |
| `smadp/integrations/slack.py` | `SlackAdapter` |
| `smadp/schemas/webhooks.py` | **modify** — add `IntegrationKind` enum + `integration_kind` & `integration_config` fields to `Subscription` |
| `smadp/webhooks/store.py` | **modify** — `_ensure_schema` adds `ALTER TABLE` for the two new columns; `create_subscription` accepts the new fields; `_row_to_subscription` reads them |
| `smadp/webhooks/api.py` | **modify** — `_CreateSubscriptionBody` accepts `integration_kind`/`integration_config` |
| `smadp/webhooks/dispatcher.py` | **modify** — per-sub adapter translation; pass `headers_overlay` to enqueue |
| `smadp/webhooks/deliveries.py` | **modify** — `enqueue(..., headers_overlay)`; new column on `webhook_deliveries`; `_row_to_delivery` reads it |
| `smadp/webhooks/worker.py` | **modify** — read `headers_overlay` from row; merge into POST headers (reserved keys win) |
| `smadp/schemas/__init__.py` | **modify** — re-export new enums + models |
| `smadp/api/routes/__init__.py` | **modify** — append `vendor.router` (alphabetical) |
| `smadp/cli.py` | **modify** — `cli.add_command(vendor_group)` |
| `smadp/config.py` | **modify** — add `public_base_url` field with env fallback `SMADP_PUBLIC_BASE_URL` |
| `pyproject.toml` | **modify** — add `dnspython>=2.6` to `[project] dependencies` |
| `tests/unit/test_schemas_vendor.py` | enum lock + id pattern + url scheme + evidence discriminator |
| `tests/unit/test_schemas_dispute.py` | enum lock + id pattern + status transition validity matrix |
| `tests/unit/test_vendor_store_claims.py` | claim CRUD, status transitions |
| `tests/unit/test_vendor_store_responses.py` | response CRUD |
| `tests/unit/test_vendor_store_disputes.py` | dispute CRUD, transition matrix, sla_breached_at calc |
| `tests/unit/test_vendor_verifier_repo.py` | repo happy + token mismatch + 5xx + transport retry |
| `tests/unit/test_vendor_verifier_dns.py` | dns happy + nxdomain + token mismatch |
| `tests/unit/test_vendor_verifier_email.py` | token compare + missing token |
| `tests/unit/test_vendor_api_claims.py` | claim create/list/verify/revoke over FastAPI |
| `tests/unit/test_vendor_api_responses.py` | response post requires verified claim |
| `tests/unit/test_vendor_api_disputes.py` | file/triage/resolve over FastAPI |
| `tests/unit/test_vendor_cli.py` | CLI roundtrip |
| `tests/unit/test_integrations_registry.py` | registry has all 4 kinds; missing kind raises |
| `tests/unit/test_integrations_vanta.py` | translator output shape + header overlay |
| `tests/unit/test_integrations_drata.py` | translator output shape + header overlay |
| `tests/unit/test_integrations_slack.py` | translator output shape; passport URL fallback |
| `tests/unit/test_webhooks_dispatcher_native.py` | dispatcher routes vanta/drata/slack subs through their adapter |
| `tests/unit/test_webhooks_worker_headers.py` | worker merges overlay; reserved headers win |
| `tests/integration/test_vendor_full_lifecycle.py` | claim (repo) → verify → post response → file dispute → triage substantive → resolve stands → transparency events |
| `tests/integration/test_webhook_native_lifecycle.py` | render passport with a slack-kind sub → worker delivers translated body to mock Slack URL |
| `tests/golden/test_integration_payloads_golden.py` | byte-stable Vanta/Drata/Slack translated payloads |
| `.github/workflows/ci.yml` | **modify** — add a vendor-claim-verify smoke step |

---

## Task 1: Vendor + dispute schemas

**Files:**
- Create: `smadp/schemas/vendor.py`
- Create: `smadp/schemas/dispute.py`
- Modify: `smadp/schemas/__init__.py`
- Create: `tests/unit/test_schemas_vendor.py`
- Create: `tests/unit/test_schemas_dispute.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_schemas_vendor.py`:

```python
"""Unit tests for smadp.schemas.vendor."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from smadp.schemas.vendor import (
    ClaimMethod,
    ClaimStatus,
    ClaimVerification,
    DnsEvidence,
    EmailEvidence,
    RepoEvidence,
    TokenEvidence,
    VendorClaim,
    VendorResponse,
)


def test_claim_method_values_locked():
    assert {m.value for m in ClaimMethod} == {"repo", "dns", "email"}


def test_claim_status_values_locked():
    assert {s.value for s in ClaimStatus} == {"pending", "verified", "revoked"}


def test_vendor_claim_id_pattern_enforced():
    with pytest.raises(ValidationError):
        VendorClaim(
            id="bad-id",
            workspace_id="ws_ABCD1234",
            agent_id="claude-code",
            vendor_user_id="user_a",
            method=ClaimMethod.REPO,
            token="t" * 32,
            status=ClaimStatus.PENDING,
            evidence_url=None,
            created_at=datetime.now(UTC),
            granted_at=None,
            revoked_at=None,
        )


def test_vendor_claim_agent_id_pattern_enforced():
    with pytest.raises(ValidationError):
        VendorClaim(
            id="vc_AB12CD34",
            workspace_id="ws_ABCD1234",
            agent_id="Bad_Slug!",
            vendor_user_id="user_a",
            method=ClaimMethod.REPO,
            token="t" * 32,
            status=ClaimStatus.PENDING,
            evidence_url=None,
            created_at=datetime.now(UTC),
            granted_at=None,
            revoked_at=None,
        )


def test_vendor_response_id_pattern_enforced():
    with pytest.raises(ValidationError):
        VendorResponse(
            id="vr_bad",
            workspace_id="ws_ABCD1234",
            verdict_id="vdt_X",
            vendor_user_id="user_a",
            body_md="hi",
            created_at=datetime.now(UTC),
        )


def test_repo_evidence_requires_https_or_localhost():
    RepoEvidence(repo_url="https://github.com/o/r/raw/main")
    RepoEvidence(repo_url="http://localhost:9000/r/raw/main")
    with pytest.raises(ValidationError):
        RepoEvidence(repo_url="ftp://example.com/owner.txt")


def test_dns_evidence_strips_scheme_and_path():
    e = DnsEvidence(domain="ACME.com")
    assert e.domain == "acme.com"
    with pytest.raises(ValidationError):
        DnsEvidence(domain="not a domain")


def test_email_evidence_basic():
    e = EmailEvidence(email_address="vendor@acme.com")
    assert e.email_address == "vendor@acme.com"
    with pytest.raises(ValidationError):
        EmailEvidence(email_address="not-an-email")


def test_token_evidence_min_length():
    with pytest.raises(ValidationError):
        TokenEvidence(token="short")
    TokenEvidence(token="t" * 32)


def test_claim_verification_record():
    v = ClaimVerification(verified=True, detail="ok")
    assert v.verified is True
    assert v.detail == "ok"
```

Create `tests/unit/test_schemas_dispute.py`:

```python
"""Unit tests for smadp.schemas.dispute."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from smadp.schemas.dispute import (
    Dispute,
    DisputeDecision,
    DisputeStatus,
    RequestedOutcome,
)


def test_dispute_status_values_locked():
    assert {s.value for s in DisputeStatus} == {
        "triage",
        "pending_review",
        "resolved_reeval",
        "resolved_stands",
        "spam",
    }


def test_requested_outcome_values_locked():
    assert {o.value for o in RequestedOutcome} == {"reeval", "withdraw", "amend"}


def test_dispute_decision_values_locked():
    assert {d.value for d in DisputeDecision} == {
        "spam",
        "substantive",
        "reeval",
        "stands",
    }


def test_dispute_id_pattern_enforced():
    with pytest.raises(ValidationError):
        Dispute(
            id="dsp_bad",
            workspace_id="ws_ABCD1234",
            verdict_id="vdt_X",
            vendor_user_id="user_a",
            argument_md="argument",
            requested_outcome=RequestedOutcome.REEVAL,
            status=DisputeStatus.TRIAGE,
            decision_rationale_md=None,
            filed_at=datetime.now(UTC),
            triaged_at=None,
            resolved_at=None,
            sla_breached_at=None,
        )


def test_dispute_argument_md_nonempty():
    with pytest.raises(ValidationError):
        Dispute(
            id="dsp_20260503120000_abcdef",
            workspace_id="ws_ABCD1234",
            verdict_id="vdt_X",
            vendor_user_id="user_a",
            argument_md="",
            requested_outcome=RequestedOutcome.REEVAL,
            status=DisputeStatus.TRIAGE,
            decision_rationale_md=None,
            filed_at=datetime.now(UTC),
            triaged_at=None,
            resolved_at=None,
            sla_breached_at=None,
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_schemas_vendor.py tests/unit/test_schemas_dispute.py -v`
Expected: ImportError / module not found.

- [ ] **Step 3: Implement schemas**

Create `smadp/schemas/vendor.py`:

```python
"""Vendor-facing schemas: claims, responses, claim evidence."""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

VENDOR_CLAIM_ID_RE = re.compile(r"^vc_[A-Z0-9]{8}$")
VENDOR_RESPONSE_ID_RE = re.compile(r"^vr_[0-9]{14}_[0-9a-f]{6}$")
WORKSPACE_ID_RE = re.compile(r"^ws_[A-Z0-9]{8,}$")
AGENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ClaimMethod(StrEnum):
    REPO = "repo"
    DNS = "dns"
    EMAIL = "email"


class ClaimStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    REVOKED = "revoked"


class VendorClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    workspace_id: str
    agent_id: str
    vendor_user_id: str
    method: ClaimMethod
    token: str
    status: ClaimStatus
    evidence_url: str | None
    created_at: datetime
    granted_at: datetime | None
    revoked_at: datetime | None

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not VENDOR_CLAIM_ID_RE.match(v):
            raise ValueError(f"Invalid vendor claim id: {v!r}")
        return v

    @field_validator("workspace_id")
    @classmethod
    def _ws(cls, v: str) -> str:
        if not WORKSPACE_ID_RE.match(v):
            raise ValueError(f"Invalid workspace id: {v!r}")
        return v

    @field_validator("agent_id")
    @classmethod
    def _agent(cls, v: str) -> str:
        if not AGENT_ID_RE.match(v):
            raise ValueError(f"Invalid agent id: {v!r}")
        return v

    @field_validator("token")
    @classmethod
    def _token(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("token must be at least 32 chars")
        return v


class VendorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    workspace_id: str
    verdict_id: str
    vendor_user_id: str
    body_md: str
    created_at: datetime

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not VENDOR_RESPONSE_ID_RE.match(v):
            raise ValueError(f"Invalid vendor response id: {v!r}")
        return v

    @field_validator("body_md")
    @classmethod
    def _body(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("body_md must not be empty")
        if len(v) > 8192:
            raise ValueError("body_md must be <= 8192 chars")
        return v


class RepoEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repo_url: str

    @field_validator("repo_url")
    @classmethod
    def _scheme(cls, v: str) -> str:
        parsed = urlparse(v)
        if parsed.scheme == "https":
            return v
        if parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}:
            return v
        raise ValueError(
            f"repo_url must be https:// (or http://localhost for dev); got {v!r}"
        )


class DnsEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str

    @field_validator("domain", mode="before")
    @classmethod
    def _normalize(cls, v: str) -> str:
        v = v.strip().lower().rstrip(".")
        if not DOMAIN_RE.match(v):
            raise ValueError(f"Invalid domain: {v!r}")
        return v


class EmailEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email_address: str

    @field_validator("email_address")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip()
        if not EMAIL_RE.match(v):
            raise ValueError(f"Invalid email: {v!r}")
        return v


class TokenEvidence(BaseModel):
    """Evidence carried by the verify call for the email method."""

    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=32)


class ClaimVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verified: bool
    detail: str


__all__ = [
    "ClaimMethod",
    "ClaimStatus",
    "ClaimVerification",
    "DnsEvidence",
    "EmailEvidence",
    "RepoEvidence",
    "TokenEvidence",
    "VendorClaim",
    "VendorResponse",
]
```

Create `smadp/schemas/dispute.py`:

```python
"""Dispute schemas (Pydantic v2)."""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator

DISPUTE_ID_RE = re.compile(r"^dsp_[0-9]{14}_[0-9a-f]{6}$")
WORKSPACE_ID_RE = re.compile(r"^ws_[A-Z0-9]{8,}$")


class DisputeStatus(StrEnum):
    TRIAGE = "triage"
    PENDING_REVIEW = "pending_review"
    RESOLVED_REEVAL = "resolved_reeval"
    RESOLVED_STANDS = "resolved_stands"
    SPAM = "spam"


class RequestedOutcome(StrEnum):
    REEVAL = "reeval"
    WITHDRAW = "withdraw"
    AMEND = "amend"


class DisputeDecision(StrEnum):
    SPAM = "spam"
    SUBSTANTIVE = "substantive"
    REEVAL = "reeval"
    STANDS = "stands"


class Dispute(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    workspace_id: str
    verdict_id: str
    vendor_user_id: str
    argument_md: str
    requested_outcome: RequestedOutcome
    status: DisputeStatus
    decision_rationale_md: str | None
    filed_at: datetime
    triaged_at: datetime | None
    resolved_at: datetime | None
    sla_breached_at: datetime | None

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not DISPUTE_ID_RE.match(v):
            raise ValueError(f"Invalid dispute id: {v!r}")
        return v

    @field_validator("workspace_id")
    @classmethod
    def _ws(cls, v: str) -> str:
        if not WORKSPACE_ID_RE.match(v):
            raise ValueError(f"Invalid workspace id: {v!r}")
        return v

    @field_validator("argument_md")
    @classmethod
    def _arg(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("argument_md must not be empty")
        if len(v) > 16384:
            raise ValueError("argument_md must be <= 16384 chars")
        return v


__all__ = [
    "Dispute",
    "DisputeDecision",
    "DisputeStatus",
    "RequestedOutcome",
]
```

Modify `smadp/schemas/__init__.py` — append re-exports for the new symbols (preserve existing re-exports; alphabetical):

```python
from smadp.schemas.dispute import (
    Dispute,
    DisputeDecision,
    DisputeStatus,
    RequestedOutcome,
)
from smadp.schemas.vendor import (
    ClaimMethod,
    ClaimStatus,
    ClaimVerification,
    DnsEvidence,
    EmailEvidence,
    RepoEvidence,
    TokenEvidence,
    VendorClaim,
    VendorResponse,
)
```

(If `smadp/schemas/__init__.py` does not currently re-export everything, just add the imports above and skip the `__all__` step.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_schemas_vendor.py tests/unit/test_schemas_dispute.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add smadp/schemas/vendor.py smadp/schemas/dispute.py smadp/schemas/__init__.py tests/unit/test_schemas_vendor.py tests/unit/test_schemas_dispute.py
git commit -m "feat(vendor): add VendorClaim/Dispute Pydantic schemas"
```

---

## Task 2: Vendor store — claims (`smadp/vendor/store.py`)

**Files:**
- Create: `smadp/vendor/__init__.py`
- Create: `smadp/vendor/store.py` (claim CRUD only — responses + disputes added in Tasks 3 & 4)
- Create: `tests/unit/test_vendor_store_claims.py`

- [ ] **Step 1: Write the failing test**

Create `smadp/vendor/__init__.py` as an empty file (just to make the package importable):

```python
"""Vendor flows: claim verification, vendor responses, disputes."""
```

Create `tests/unit/test_vendor_store_claims.py`:

```python
"""Unit tests for vendor.store claim CRUD."""

from __future__ import annotations

from pathlib import Path

import pytest

from smadp.config import Config
from smadp.schemas.tenancy import Plan
from smadp.schemas.vendor import ClaimMethod, ClaimStatus
from smadp.tenancy import store as tenancy
from smadp.vendor import store


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return Config()


@pytest.fixture
def workspace_id(cfg: Config) -> str:
    ws = tenancy.create_workspace(name="V", plan=Plan.PUBLIC, config=cfg)
    return ws.id


def test_create_claim_returns_token(cfg: Config, workspace_id: str):
    claim = store.create_claim(
        workspace_id=workspace_id,
        agent_id="claude-code",
        vendor_user_id="user_a",
        method=ClaimMethod.REPO,
        evidence_url="https://github.com/o/r/raw/main",
        config=cfg,
    )
    assert claim.id.startswith("vc_")
    assert claim.status == ClaimStatus.PENDING
    assert len(claim.token) >= 32
    assert claim.evidence_url == "https://github.com/o/r/raw/main"


def test_get_claim_roundtrip(cfg: Config, workspace_id: str):
    a = store.create_claim(
        workspace_id=workspace_id,
        agent_id="claude-code",
        vendor_user_id="user_a",
        method=ClaimMethod.DNS,
        evidence_url=None,
        config=cfg,
    )
    b = store.get_claim(claim_id=a.id, config=cfg)
    assert a == b


def test_list_claims_for_workspace(cfg: Config, workspace_id: str):
    a = store.create_claim(
        workspace_id=workspace_id,
        agent_id="claude-code",
        vendor_user_id="u",
        method=ClaimMethod.REPO,
        evidence_url="https://github.com/o/r/raw/main",
        config=cfg,
    )
    b = store.create_claim(
        workspace_id=workspace_id,
        agent_id="cursor",
        vendor_user_id="u",
        method=ClaimMethod.DNS,
        evidence_url=None,
        config=cfg,
    )
    ids = {c.id for c in store.list_claims(workspace_id=workspace_id, config=cfg)}
    assert ids == {a.id, b.id}


def test_list_claims_filter_by_agent(cfg: Config, workspace_id: str):
    store.create_claim(
        workspace_id=workspace_id,
        agent_id="claude-code",
        vendor_user_id="u",
        method=ClaimMethod.REPO,
        evidence_url="https://github.com/o/r/raw/main",
        config=cfg,
    )
    b = store.create_claim(
        workspace_id=workspace_id,
        agent_id="cursor",
        vendor_user_id="u",
        method=ClaimMethod.DNS,
        evidence_url=None,
        config=cfg,
    )
    matched = store.list_claims(workspace_id=workspace_id, agent_id="cursor", config=cfg)
    assert {c.id for c in matched} == {b.id}


def test_mark_claim_verified(cfg: Config, workspace_id: str):
    a = store.create_claim(
        workspace_id=workspace_id,
        agent_id="claude-code",
        vendor_user_id="u",
        method=ClaimMethod.REPO,
        evidence_url="https://github.com/o/r/raw/main",
        config=cfg,
    )
    store.mark_claim_verified(claim_id=a.id, config=cfg)
    loaded = store.get_claim(claim_id=a.id, config=cfg)
    assert loaded.status == ClaimStatus.VERIFIED
    assert loaded.granted_at is not None


def test_revoke_claim(cfg: Config, workspace_id: str):
    a = store.create_claim(
        workspace_id=workspace_id,
        agent_id="claude-code",
        vendor_user_id="u",
        method=ClaimMethod.REPO,
        evidence_url="https://github.com/o/r/raw/main",
        config=cfg,
    )
    store.revoke_claim(claim_id=a.id, config=cfg)
    loaded = store.get_claim(claim_id=a.id, config=cfg)
    assert loaded.status == ClaimStatus.REVOKED
    assert loaded.revoked_at is not None


def test_get_claim_unknown_raises(cfg: Config):
    with pytest.raises(KeyError):
        store.get_claim(claim_id="vc_NOPE0000", config=cfg)


def test_find_verified_claim_lookup(cfg: Config, workspace_id: str):
    a = store.create_claim(
        workspace_id=workspace_id,
        agent_id="claude-code",
        vendor_user_id="user_a",
        method=ClaimMethod.REPO,
        evidence_url="https://github.com/o/r/raw/main",
        config=cfg,
    )
    assert (
        store.find_verified_claim(
            workspace_id=workspace_id,
            vendor_user_id="user_a",
            agent_id="claude-code",
            config=cfg,
        )
        is None
    )
    store.mark_claim_verified(claim_id=a.id, config=cfg)
    found = store.find_verified_claim(
        workspace_id=workspace_id,
        vendor_user_id="user_a",
        agent_id="claude-code",
        config=cfg,
    )
    assert found is not None and found.id == a.id
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_vendor_store_claims.py -v`
Expected: ImportError on `smadp.vendor.store`.

- [ ] **Step 3: Implement claim CRUD**

Create `smadp/vendor/store.py`:

```python
"""SQLite-backed vendor store: claims, responses, disputes.

DB lives at ``<cache_dir>/vendor.db`` (WAL, BEGIN IMMEDIATE).
Tokens are stored in plaintext — they are server-generated nonces and
verifying still requires control of the corresponding repo/DNS/inbox.
"""

from __future__ import annotations

import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Final

import structlog

from smadp.config import Config, load_config
from smadp.schemas.vendor import (
    ClaimMethod,
    ClaimStatus,
    VendorClaim,
)
from smadp.utils.time import utcnow

log = structlog.get_logger(__name__)


_SCHEMA_SQL: Final[str] = """
CREATE TABLE IF NOT EXISTS vendor_claims (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    vendor_user_id TEXT NOT NULL,
    method TEXT NOT NULL,
    token TEXT NOT NULL,
    status TEXT NOT NULL,
    evidence_url TEXT,
    created_at TEXT NOT NULL,
    granted_at TEXT,
    revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS vendor_claims_workspace
    ON vendor_claims(workspace_id, agent_id);
CREATE INDEX IF NOT EXISTS vendor_claims_user
    ON vendor_claims(workspace_id, vendor_user_id, agent_id, status);
"""


def _db_path(config: Config) -> Path:
    config.cache_dir.mkdir(parents=True, exist_ok=True)
    return config.cache_dir / "vendor.db"


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


def _now_iso() -> str:
    return utcnow().isoformat(timespec="seconds").replace("+00:00", "Z")


def _from_iso(s: str | None) -> datetime | None:
    if s is None:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _generate_claim_id() -> str:
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "vc_" + "".join(secrets.choice(alphabet) for _ in range(8))


def _generate_token() -> str:
    return secrets.token_urlsafe(32)


def _row_to_claim(row: sqlite3.Row) -> VendorClaim:
    return VendorClaim(
        id=row["id"],
        workspace_id=row["workspace_id"],
        agent_id=row["agent_id"],
        vendor_user_id=row["vendor_user_id"],
        method=ClaimMethod(row["method"]),
        token=row["token"],
        status=ClaimStatus(row["status"]),
        evidence_url=row["evidence_url"],
        created_at=_from_iso(row["created_at"]),
        granted_at=_from_iso(row["granted_at"]),
        revoked_at=_from_iso(row["revoked_at"]),
    )


def create_claim(
    *,
    workspace_id: str,
    agent_id: str,
    vendor_user_id: str,
    method: ClaimMethod,
    evidence_url: str | None,
    config: Config | None = None,
) -> VendorClaim:
    cfg = config or load_config()
    claim_id = _generate_claim_id()
    token = _generate_token()
    now_iso = _now_iso()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        with _transaction(conn):
            conn.execute(
                "INSERT INTO vendor_claims"
                "(id, workspace_id, agent_id, vendor_user_id, method, token,"
                " status, evidence_url, created_at, granted_at, revoked_at)"
                " VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, NULL, NULL)",
                (
                    claim_id,
                    workspace_id,
                    agent_id,
                    vendor_user_id,
                    method.value,
                    token,
                    evidence_url,
                    now_iso,
                ),
            )
        log.info(
            "vendor.claim.created",
            workspace_id=workspace_id,
            agent_id=agent_id,
            claim_id=claim_id,
            method=method.value,
        )
        return get_claim(claim_id=claim_id, config=cfg)
    finally:
        conn.close()


def get_claim(*, claim_id: str, config: Config | None = None) -> VendorClaim:
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        cur = conn.execute("SELECT * FROM vendor_claims WHERE id = ?", (claim_id,))
        row = cur.fetchone()
        if row is None:
            raise KeyError(f"unknown vendor claim: {claim_id!r}")
        return _row_to_claim(row)
    finally:
        conn.close()


def list_claims(
    *,
    workspace_id: str,
    agent_id: str | None = None,
    config: Config | None = None,
) -> list[VendorClaim]:
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        if agent_id is None:
            cur = conn.execute(
                "SELECT * FROM vendor_claims WHERE workspace_id = ?"
                " ORDER BY created_at DESC",
                (workspace_id,),
            )
        else:
            cur = conn.execute(
                "SELECT * FROM vendor_claims WHERE workspace_id = ? AND agent_id = ?"
                " ORDER BY created_at DESC",
                (workspace_id, agent_id),
            )
        return [_row_to_claim(r) for r in cur.fetchall()]
    finally:
        conn.close()


def mark_claim_verified(*, claim_id: str, config: Config | None = None) -> None:
    cfg = config or load_config()
    now_iso = _now_iso()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        with _transaction(conn):
            cur = conn.execute(
                "UPDATE vendor_claims SET status='verified', granted_at=?"
                " WHERE id = ? AND status='pending'",
                (now_iso, claim_id),
            )
            if cur.rowcount == 0:
                raise KeyError(
                    f"vendor claim {claim_id!r} is not pending or does not exist"
                )
        log.info("vendor.claim.verified", claim_id=claim_id)
    finally:
        conn.close()


def revoke_claim(*, claim_id: str, config: Config | None = None) -> None:
    cfg = config or load_config()
    now_iso = _now_iso()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        with _transaction(conn):
            cur = conn.execute(
                "UPDATE vendor_claims SET status='revoked', revoked_at=?"
                " WHERE id = ? AND status != 'revoked'",
                (now_iso, claim_id),
            )
            if cur.rowcount == 0:
                raise KeyError(
                    f"vendor claim {claim_id!r} already revoked or unknown"
                )
        log.info("vendor.claim.revoked", claim_id=claim_id)
    finally:
        conn.close()


def find_verified_claim(
    *,
    workspace_id: str,
    vendor_user_id: str,
    agent_id: str,
    config: Config | None = None,
) -> VendorClaim | None:
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        cur = conn.execute(
            "SELECT * FROM vendor_claims"
            " WHERE workspace_id = ? AND vendor_user_id = ?"
            " AND agent_id = ? AND status = 'verified'"
            " ORDER BY granted_at DESC LIMIT 1",
            (workspace_id, vendor_user_id, agent_id),
        )
        row = cur.fetchone()
        return _row_to_claim(row) if row else None
    finally:
        conn.close()


__all__ = [
    "create_claim",
    "find_verified_claim",
    "get_claim",
    "list_claims",
    "mark_claim_verified",
    "revoke_claim",
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_vendor_store_claims.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add smadp/vendor/__init__.py smadp/vendor/store.py tests/unit/test_vendor_store_claims.py
git commit -m "feat(vendor): add claim CRUD store backed by vendor.db"
```

---

## Task 3: Vendor store — responses

**Files:**
- Modify: `smadp/vendor/store.py`
- Create: `tests/unit/test_vendor_store_responses.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_vendor_store_responses.py`:

```python
"""Unit tests for vendor.store response CRUD."""

from __future__ import annotations

from pathlib import Path

import pytest

from smadp.config import Config
from smadp.schemas.tenancy import Plan
from smadp.tenancy import store as tenancy
from smadp.vendor import store


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return Config()


@pytest.fixture
def workspace_id(cfg: Config) -> str:
    ws = tenancy.create_workspace(name="V", plan=Plan.PUBLIC, config=cfg)
    return ws.id


def test_post_response_returns_id(cfg: Config, workspace_id: str):
    r = store.post_response(
        workspace_id=workspace_id,
        verdict_id="vdt_X",
        vendor_user_id="user_a",
        body_md="we mitigated this",
        config=cfg,
    )
    assert r.id.startswith("vr_")
    assert r.body_md == "we mitigated this"


def test_list_responses_for_verdict(cfg: Config, workspace_id: str):
    a = store.post_response(
        workspace_id=workspace_id,
        verdict_id="vdt_X",
        vendor_user_id="user_a",
        body_md="first",
        config=cfg,
    )
    b = store.post_response(
        workspace_id=workspace_id,
        verdict_id="vdt_X",
        vendor_user_id="user_a",
        body_md="second",
        config=cfg,
    )
    store.post_response(
        workspace_id=workspace_id,
        verdict_id="vdt_OTHER",
        vendor_user_id="user_a",
        body_md="other",
        config=cfg,
    )
    ids = {r.id for r in store.list_responses(workspace_id=workspace_id, verdict_id="vdt_X", config=cfg)}
    assert ids == {a.id, b.id}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_vendor_store_responses.py -v`
Expected: AttributeError on `store.post_response`.

- [ ] **Step 3: Add response CRUD to `smadp/vendor/store.py`**

Append to `_SCHEMA_SQL` (insert before the closing `"""`):

```sql
CREATE TABLE IF NOT EXISTS vendor_responses (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    verdict_id TEXT NOT NULL,
    vendor_user_id TEXT NOT NULL,
    body_md TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS vendor_responses_verdict
    ON vendor_responses(workspace_id, verdict_id);
```

Add import at the top:

```python
from smadp.schemas.vendor import (
    ClaimMethod,
    ClaimStatus,
    VendorClaim,
    VendorResponse,
)
```

Add helpers + functions (anywhere after the existing claim functions; keep alphabetical-ish):

```python
def _generate_response_id(now: datetime) -> str:
    ts = now.strftime("%Y%m%d%H%M%S")
    suffix = secrets.token_hex(3)
    return f"vr_{ts}_{suffix}"


def _row_to_response(row: sqlite3.Row) -> VendorResponse:
    return VendorResponse(
        id=row["id"],
        workspace_id=row["workspace_id"],
        verdict_id=row["verdict_id"],
        vendor_user_id=row["vendor_user_id"],
        body_md=row["body_md"],
        created_at=_from_iso(row["created_at"]),
    )


def post_response(
    *,
    workspace_id: str,
    verdict_id: str,
    vendor_user_id: str,
    body_md: str,
    config: Config | None = None,
) -> VendorResponse:
    cfg = config or load_config()
    now = utcnow()
    response_id = _generate_response_id(now)
    now_iso = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        with _transaction(conn):
            conn.execute(
                "INSERT INTO vendor_responses"
                "(id, workspace_id, verdict_id, vendor_user_id, body_md, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (response_id, workspace_id, verdict_id, vendor_user_id, body_md, now_iso),
            )
        log.info(
            "vendor.response.posted",
            workspace_id=workspace_id,
            verdict_id=verdict_id,
            response_id=response_id,
        )
        return VendorResponse(
            id=response_id,
            workspace_id=workspace_id,
            verdict_id=verdict_id,
            vendor_user_id=vendor_user_id,
            body_md=body_md,
            created_at=_from_iso(now_iso),
        )
    finally:
        conn.close()


def list_responses(
    *,
    workspace_id: str,
    verdict_id: str,
    config: Config | None = None,
) -> list[VendorResponse]:
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        cur = conn.execute(
            "SELECT * FROM vendor_responses"
            " WHERE workspace_id = ? AND verdict_id = ?"
            " ORDER BY created_at ASC",
            (workspace_id, verdict_id),
        )
        return [_row_to_response(r) for r in cur.fetchall()]
    finally:
        conn.close()
```

Append `post_response` and `list_responses` to `__all__`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_vendor_store_responses.py tests/unit/test_vendor_store_claims.py -v`
Expected: all PASS (claims still pass after schema additions).

- [ ] **Step 5: Commit**

```bash
git add smadp/vendor/store.py tests/unit/test_vendor_store_responses.py
git commit -m "feat(vendor): add vendor response post/list"
```

---

## Task 4: Vendor store — disputes + transition matrix

**Files:**
- Modify: `smadp/vendor/store.py`
- Create: `tests/unit/test_vendor_store_disputes.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_vendor_store_disputes.py`:

```python
"""Unit tests for vendor.store dispute CRUD + transitions."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from smadp.config import Config
from smadp.schemas.dispute import DisputeDecision, DisputeStatus, RequestedOutcome
from smadp.schemas.tenancy import Plan
from smadp.tenancy import store as tenancy
from smadp.vendor import store


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return Config()


@pytest.fixture
def workspace_id(cfg: Config) -> str:
    ws = tenancy.create_workspace(name="V", plan=Plan.PUBLIC, config=cfg)
    return ws.id


def _file(cfg, ws):
    return store.file_dispute(
        workspace_id=ws,
        verdict_id="vdt_X",
        vendor_user_id="user_a",
        argument_md="we believe this is wrong because ...",
        requested_outcome=RequestedOutcome.REEVAL,
        config=cfg,
    )


def test_file_dispute_starts_in_triage(cfg: Config, workspace_id: str):
    d = _file(cfg, workspace_id)
    assert d.id.startswith("dsp_")
    assert d.status == DisputeStatus.TRIAGE
    assert d.triaged_at is None
    assert d.sla_breached_at is None


def test_triage_to_spam(cfg: Config, workspace_id: str):
    d = _file(cfg, workspace_id)
    store.update_dispute_status(
        dispute_id=d.id,
        decision=DisputeDecision.SPAM,
        rationale_md=None,
        config=cfg,
    )
    loaded = store.get_dispute(dispute_id=d.id, config=cfg)
    assert loaded.status == DisputeStatus.SPAM
    assert loaded.resolved_at is not None


def test_triage_to_pending_review_sets_sla(cfg: Config, workspace_id: str):
    d = _file(cfg, workspace_id)
    store.update_dispute_status(
        dispute_id=d.id,
        decision=DisputeDecision.SUBSTANTIVE,
        rationale_md=None,
        config=cfg,
    )
    loaded = store.get_dispute(dispute_id=d.id, config=cfg)
    assert loaded.status == DisputeStatus.PENDING_REVIEW
    assert loaded.triaged_at is not None
    assert loaded.sla_breached_at is not None
    # 5 business days >= 5 calendar days
    assert (loaded.sla_breached_at - loaded.triaged_at).days >= 5


def test_pending_review_to_resolved_reeval_requires_rationale(cfg: Config, workspace_id: str):
    d = _file(cfg, workspace_id)
    store.update_dispute_status(
        dispute_id=d.id, decision=DisputeDecision.SUBSTANTIVE, rationale_md=None, config=cfg
    )
    with pytest.raises(ValueError, match="rationale"):
        store.update_dispute_status(
            dispute_id=d.id,
            decision=DisputeDecision.REEVAL,
            rationale_md=None,
            config=cfg,
        )


def test_pending_review_to_resolved_reeval(cfg: Config, workspace_id: str):
    d = _file(cfg, workspace_id)
    store.update_dispute_status(
        dispute_id=d.id, decision=DisputeDecision.SUBSTANTIVE, rationale_md=None, config=cfg
    )
    store.update_dispute_status(
        dispute_id=d.id,
        decision=DisputeDecision.REEVAL,
        rationale_md="re-running with new criteria",
        config=cfg,
    )
    loaded = store.get_dispute(dispute_id=d.id, config=cfg)
    assert loaded.status == DisputeStatus.RESOLVED_REEVAL
    assert loaded.decision_rationale_md == "re-running with new criteria"


def test_pending_review_to_resolved_stands(cfg: Config, workspace_id: str):
    d = _file(cfg, workspace_id)
    store.update_dispute_status(
        dispute_id=d.id, decision=DisputeDecision.SUBSTANTIVE, rationale_md=None, config=cfg
    )
    store.update_dispute_status(
        dispute_id=d.id,
        decision=DisputeDecision.STANDS,
        rationale_md="evidence reviewed; verdict confirmed",
        config=cfg,
    )
    loaded = store.get_dispute(dispute_id=d.id, config=cfg)
    assert loaded.status == DisputeStatus.RESOLVED_STANDS


def test_invalid_transition_triage_to_reeval_raises(cfg: Config, workspace_id: str):
    d = _file(cfg, workspace_id)
    with pytest.raises(ValueError, match="invalid dispute transition"):
        store.update_dispute_status(
            dispute_id=d.id,
            decision=DisputeDecision.REEVAL,
            rationale_md="x",
            config=cfg,
        )


def test_list_disputes_for_verdict(cfg: Config, workspace_id: str):
    a = _file(cfg, workspace_id)
    b = store.file_dispute(
        workspace_id=workspace_id,
        verdict_id="vdt_X",
        vendor_user_id="user_b",
        argument_md="another argument",
        requested_outcome=RequestedOutcome.AMEND,
        config=cfg,
    )
    ids = {d.id for d in store.list_disputes(workspace_id=workspace_id, verdict_id="vdt_X", config=cfg)}
    assert ids == {a.id, b.id}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_vendor_store_disputes.py -v`
Expected: AttributeError on `store.file_dispute`.

- [ ] **Step 3: Add dispute CRUD to `smadp/vendor/store.py`**

Add to imports at top:

```python
from datetime import datetime, timedelta
```

(Import `timedelta`. Keep existing `datetime` import.)

```python
from smadp.schemas.dispute import (
    Dispute,
    DisputeDecision,
    DisputeStatus,
    RequestedOutcome,
)
```

Append to `_SCHEMA_SQL` (before the closing `"""`):

```sql
CREATE TABLE IF NOT EXISTS disputes (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    verdict_id TEXT NOT NULL,
    vendor_user_id TEXT NOT NULL,
    argument_md TEXT NOT NULL,
    requested_outcome TEXT NOT NULL,
    status TEXT NOT NULL,
    decision_rationale_md TEXT,
    filed_at TEXT NOT NULL,
    triaged_at TEXT,
    resolved_at TEXT,
    sla_breached_at TEXT
);
CREATE INDEX IF NOT EXISTS disputes_verdict
    ON disputes(workspace_id, verdict_id, status);
```

Add helpers + the transition validator and CRUD:

```python
_BUSINESS_DAYS_SLA: Final[int] = 5


def _generate_dispute_id(now: datetime) -> str:
    ts = now.strftime("%Y%m%d%H%M%S")
    suffix = secrets.token_hex(3)
    return f"dsp_{ts}_{suffix}"


def _add_business_days(start: datetime, days: int) -> datetime:
    """Add N business days (Mon-Fri); skips weekends, ignores holidays."""
    result = start
    added = 0
    while added < days:
        result = result + timedelta(days=1)
        if result.weekday() < 5:  # Mon=0..Fri=4
            added += 1
    return result


_VALID_TRANSITIONS: Final[dict[tuple[DisputeStatus, DisputeDecision], DisputeStatus]] = {
    (DisputeStatus.TRIAGE, DisputeDecision.SPAM): DisputeStatus.SPAM,
    (DisputeStatus.TRIAGE, DisputeDecision.SUBSTANTIVE): DisputeStatus.PENDING_REVIEW,
    (DisputeStatus.PENDING_REVIEW, DisputeDecision.REEVAL): DisputeStatus.RESOLVED_REEVAL,
    (DisputeStatus.PENDING_REVIEW, DisputeDecision.STANDS): DisputeStatus.RESOLVED_STANDS,
}


def _row_to_dispute(row: sqlite3.Row) -> Dispute:
    return Dispute(
        id=row["id"],
        workspace_id=row["workspace_id"],
        verdict_id=row["verdict_id"],
        vendor_user_id=row["vendor_user_id"],
        argument_md=row["argument_md"],
        requested_outcome=RequestedOutcome(row["requested_outcome"]),
        status=DisputeStatus(row["status"]),
        decision_rationale_md=row["decision_rationale_md"],
        filed_at=_from_iso(row["filed_at"]),
        triaged_at=_from_iso(row["triaged_at"]),
        resolved_at=_from_iso(row["resolved_at"]),
        sla_breached_at=_from_iso(row["sla_breached_at"]),
    )


def file_dispute(
    *,
    workspace_id: str,
    verdict_id: str,
    vendor_user_id: str,
    argument_md: str,
    requested_outcome: RequestedOutcome,
    config: Config | None = None,
) -> Dispute:
    cfg = config or load_config()
    now = utcnow()
    dispute_id = _generate_dispute_id(now)
    now_iso = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        with _transaction(conn):
            conn.execute(
                "INSERT INTO disputes"
                "(id, workspace_id, verdict_id, vendor_user_id, argument_md,"
                " requested_outcome, status, decision_rationale_md,"
                " filed_at, triaged_at, resolved_at, sla_breached_at)"
                " VALUES (?, ?, ?, ?, ?, ?, 'triage', NULL, ?, NULL, NULL, NULL)",
                (
                    dispute_id,
                    workspace_id,
                    verdict_id,
                    vendor_user_id,
                    argument_md,
                    requested_outcome.value,
                    now_iso,
                ),
            )
        log.info(
            "vendor.dispute.filed",
            workspace_id=workspace_id,
            verdict_id=verdict_id,
            dispute_id=dispute_id,
        )
        return get_dispute(dispute_id=dispute_id, config=cfg)
    finally:
        conn.close()


def get_dispute(*, dispute_id: str, config: Config | None = None) -> Dispute:
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        cur = conn.execute("SELECT * FROM disputes WHERE id = ?", (dispute_id,))
        row = cur.fetchone()
        if row is None:
            raise KeyError(f"unknown dispute: {dispute_id!r}")
        return _row_to_dispute(row)
    finally:
        conn.close()


def list_disputes(
    *,
    workspace_id: str,
    verdict_id: str | None = None,
    config: Config | None = None,
) -> list[Dispute]:
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        if verdict_id is None:
            cur = conn.execute(
                "SELECT * FROM disputes WHERE workspace_id = ? ORDER BY filed_at DESC",
                (workspace_id,),
            )
        else:
            cur = conn.execute(
                "SELECT * FROM disputes WHERE workspace_id = ? AND verdict_id = ?"
                " ORDER BY filed_at DESC",
                (workspace_id, verdict_id),
            )
        return [_row_to_dispute(r) for r in cur.fetchall()]
    finally:
        conn.close()


def update_dispute_status(
    *,
    dispute_id: str,
    decision: DisputeDecision,
    rationale_md: str | None,
    config: Config | None = None,
) -> Dispute:
    cfg = config or load_config()
    current = get_dispute(dispute_id=dispute_id, config=cfg)
    target = _VALID_TRANSITIONS.get((current.status, decision))
    if target is None:
        raise ValueError(
            f"invalid dispute transition: {current.status.value} → {decision.value}"
        )
    if target in {DisputeStatus.RESOLVED_REEVAL, DisputeStatus.RESOLVED_STANDS}:
        if not rationale_md or not rationale_md.strip():
            raise ValueError("rationale_md required for resolution")
    now = utcnow()
    now_iso = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    triaged_at = current.triaged_at
    sla_breached_at = current.sla_breached_at
    resolved_at = current.resolved_at
    if current.status == DisputeStatus.TRIAGE:
        triaged_at = now
        if target == DisputeStatus.PENDING_REVIEW:
            sla_breached_at = _add_business_days(now, _BUSINESS_DAYS_SLA)
        if target == DisputeStatus.SPAM:
            resolved_at = now
    elif target in {DisputeStatus.RESOLVED_REEVAL, DisputeStatus.RESOLVED_STANDS}:
        resolved_at = now

    triaged_iso = (
        triaged_at.isoformat(timespec="seconds").replace("+00:00", "Z")
        if triaged_at
        else None
    )
    sla_iso = (
        sla_breached_at.isoformat(timespec="seconds").replace("+00:00", "Z")
        if sla_breached_at
        else None
    )
    resolved_iso = (
        resolved_at.isoformat(timespec="seconds").replace("+00:00", "Z")
        if resolved_at
        else None
    )

    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        with _transaction(conn):
            conn.execute(
                "UPDATE disputes SET status = ?, decision_rationale_md = COALESCE(?, decision_rationale_md),"
                " triaged_at = ?, sla_breached_at = ?, resolved_at = ?"
                " WHERE id = ?",
                (target.value, rationale_md, triaged_iso, sla_iso, resolved_iso, dispute_id),
            )
        log.info(
            "vendor.dispute.transitioned",
            dispute_id=dispute_id,
            from_status=current.status.value,
            to_status=target.value,
            decision=decision.value,
        )
        return get_dispute(dispute_id=dispute_id, config=cfg)
    finally:
        conn.close()
```

Append `file_dispute`, `get_dispute`, `list_disputes`, `update_dispute_status` to `__all__`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_vendor_store_disputes.py tests/unit/test_vendor_store_claims.py tests/unit/test_vendor_store_responses.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add smadp/vendor/store.py tests/unit/test_vendor_store_disputes.py
git commit -m "feat(vendor): add dispute CRUD with transition matrix and SLA calc"
```

---

## Task 5: Verifier — repo method

**Files:**
- Create: `smadp/vendor/verifier.py`
- Create: `tests/unit/test_vendor_verifier_repo.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_vendor_verifier_repo.py`:

```python
"""Unit tests for vendor.verifier repo method."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from smadp.config import Config
from smadp.schemas.tenancy import Plan
from smadp.schemas.vendor import ClaimMethod, RepoEvidence
from smadp.tenancy import store as tenancy
from smadp.vendor import store, verifier


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return Config()


@pytest.fixture
def workspace_id(cfg: Config) -> str:
    ws = tenancy.create_workspace(name="V", plan=Plan.PUBLIC, config=cfg)
    return ws.id


def _claim(cfg, ws):
    return store.create_claim(
        workspace_id=ws,
        agent_id="claude-code",
        vendor_user_id="user_a",
        method=ClaimMethod.REPO,
        evidence_url="https://github.com/o/r/raw/main",
        config=cfg,
    )


@respx.mock
def test_verify_repo_happy_path(cfg: Config, workspace_id: str):
    claim = _claim(cfg, workspace_id)
    respx.get("https://github.com/o/r/raw/main/.smadp/owner.txt").mock(
        return_value=httpx.Response(200, text=claim.token + "\n")
    )
    result = verifier.verify_repo(claim=claim, evidence=RepoEvidence(repo_url=claim.evidence_url))
    assert result.verified is True
    assert "200" in result.detail


@respx.mock
def test_verify_repo_token_mismatch(cfg: Config, workspace_id: str):
    claim = _claim(cfg, workspace_id)
    respx.get("https://github.com/o/r/raw/main/.smadp/owner.txt").mock(
        return_value=httpx.Response(200, text="not-the-token")
    )
    result = verifier.verify_repo(claim=claim, evidence=RepoEvidence(repo_url=claim.evidence_url))
    assert result.verified is False
    assert "mismatch" in result.detail.lower()


@respx.mock
def test_verify_repo_404_no_retry(cfg: Config, workspace_id: str):
    claim = _claim(cfg, workspace_id)
    respx.get("https://github.com/o/r/raw/main/.smadp/owner.txt").mock(
        return_value=httpx.Response(404)
    )
    result = verifier.verify_repo(claim=claim, evidence=RepoEvidence(repo_url=claim.evidence_url))
    assert result.verified is False
    assert "404" in result.detail


@respx.mock
def test_verify_repo_5xx_then_success_retries(cfg: Config, workspace_id: str, monkeypatch: pytest.MonkeyPatch):
    # Disable backoff sleeps so the test is fast.
    monkeypatch.setattr(verifier, "_RETRY_BACKOFFS", (0.0, 0.0))
    claim = _claim(cfg, workspace_id)
    route = respx.get("https://github.com/o/r/raw/main/.smadp/owner.txt").mock(
        side_effect=[httpx.ConnectError("boom"), httpx.Response(200, text=claim.token)]
    )
    result = verifier.verify_repo(claim=claim, evidence=RepoEvidence(repo_url=claim.evidence_url))
    assert result.verified is True
    assert route.call_count == 2


@respx.mock
def test_verify_repo_transport_exhaust(cfg: Config, workspace_id: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(verifier, "_RETRY_BACKOFFS", (0.0, 0.0))
    claim = _claim(cfg, workspace_id)
    respx.get("https://github.com/o/r/raw/main/.smadp/owner.txt").mock(
        side_effect=httpx.ConnectError("dead")
    )
    result = verifier.verify_repo(claim=claim, evidence=RepoEvidence(repo_url=claim.evidence_url))
    assert result.verified is False
    assert "dead" in result.detail.lower() or "connect" in result.detail.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_vendor_verifier_repo.py -v`
Expected: ImportError on `smadp.vendor.verifier`.

- [ ] **Step 3: Implement repo verifier**

Create `smadp/vendor/verifier.py`:

```python
"""Claim verification: repo (httpx), DNS (dnspython), email (token compare)."""

from __future__ import annotations

import hmac
import time
from typing import Final

import httpx
import structlog

from smadp.schemas.vendor import (
    ClaimMethod,
    ClaimVerification,
    DnsEvidence,
    EmailEvidence,
    RepoEvidence,
    TokenEvidence,
    VendorClaim,
)

log = structlog.get_logger(__name__)

_HTTP_TIMEOUT_S: Final[float] = 10.0
_RETRY_BACKOFFS: tuple[float, ...] = (1.0, 4.0)
_OWNER_FILE_SUFFIX: Final[str] = "/.smadp/owner.txt"


def verify_repo(*, claim: VendorClaim, evidence: RepoEvidence) -> ClaimVerification:
    url = evidence.repo_url.rstrip("/") + _OWNER_FILE_SUFFIX
    last_exc: Exception | None = None
    last_status: int | None = None
    last_body: str | None = None

    attempts = (0.0,) + _RETRY_BACKOFFS  # 1 initial + N retries
    for i, backoff in enumerate(attempts):
        if backoff > 0.0:
            time.sleep(backoff)
        try:
            with httpx.Client(timeout=_HTTP_TIMEOUT_S, follow_redirects=True) as client:
                resp = client.get(url)
            last_status = resp.status_code
            last_body = resp.text
            if 500 <= resp.status_code < 600:
                last_exc = RuntimeError(f"HTTP {resp.status_code}")
                continue
            if resp.status_code != 200:
                return ClaimVerification(
                    verified=False, detail=f"repo HTTP {resp.status_code}"
                )
            body = resp.text.strip()
            if hmac.compare_digest(body, claim.token):
                return ClaimVerification(
                    verified=True, detail=f"repo HTTP 200; token match (attempt {i + 1})"
                )
            return ClaimVerification(verified=False, detail="repo token mismatch")
        except (httpx.TransportError, RuntimeError) as exc:
            last_exc = exc
            continue
    detail = f"transport error: {last_exc!r}"
    if last_status is not None:
        detail += f" (last HTTP={last_status})"
    return ClaimVerification(verified=False, detail=detail)


__all__ = [
    "verify_repo",
]
```

(DNS / email functions added in Tasks 6 & 7.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_vendor_verifier_repo.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add smadp/vendor/verifier.py tests/unit/test_vendor_verifier_repo.py
git commit -m "feat(vendor): add repo-file claim verifier"
```

---

## Task 6: Verifier — DNS method

**Files:**
- Modify: `smadp/vendor/verifier.py`
- Modify: `pyproject.toml`
- Create: `tests/unit/test_vendor_verifier_dns.py`

- [ ] **Step 1: Add `dnspython` dependency**

In `pyproject.toml`, find the `[project] dependencies = [` array and append `"dnspython>=2.6,<3"` (alphabetical position; existing entries are sorted).

Then sync:

```bash
uv sync
```

Expected: dnspython downloaded, no version-resolution errors.

- [ ] **Step 2: Write the failing test**

Create `tests/unit/test_vendor_verifier_dns.py`:

```python
"""Unit tests for vendor.verifier DNS method."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from smadp.config import Config
from smadp.schemas.tenancy import Plan
from smadp.schemas.vendor import ClaimMethod, DnsEvidence
from smadp.tenancy import store as tenancy
from smadp.vendor import store, verifier


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return Config()


@pytest.fixture
def workspace_id(cfg: Config) -> str:
    ws = tenancy.create_workspace(name="V", plan=Plan.PUBLIC, config=cfg)
    return ws.id


def _claim(cfg, ws):
    return store.create_claim(
        workspace_id=ws,
        agent_id="claude-code",
        vendor_user_id="user_a",
        method=ClaimMethod.DNS,
        evidence_url=None,
        config=cfg,
    )


def _txt_answer(values: list[str]):
    """Build a fake dnspython answer iterable."""
    answers = []
    for v in values:
        m = MagicMock()
        m.strings = [v.encode("utf-8")]
        answers.append(m)
    return answers


def test_verify_dns_happy_path(cfg: Config, workspace_id: str):
    claim = _claim(cfg, workspace_id)
    with patch.object(verifier, "_resolve_txt", return_value=_txt_answer(["junk", claim.token])):
        result = verifier.verify_dns(claim=claim, evidence=DnsEvidence(domain="acme.com"))
    assert result.verified is True
    assert "acme.com" in result.detail


def test_verify_dns_token_mismatch(cfg: Config, workspace_id: str):
    claim = _claim(cfg, workspace_id)
    with patch.object(verifier, "_resolve_txt", return_value=_txt_answer(["other-token"])):
        result = verifier.verify_dns(claim=claim, evidence=DnsEvidence(domain="acme.com"))
    assert result.verified is False
    assert "mismatch" in result.detail.lower()


def test_verify_dns_nxdomain(cfg: Config, workspace_id: str):
    import dns.resolver

    claim = _claim(cfg, workspace_id)
    with patch.object(verifier, "_resolve_txt", side_effect=dns.resolver.NXDOMAIN()):
        result = verifier.verify_dns(claim=claim, evidence=DnsEvidence(domain="acme.com"))
    assert result.verified is False
    assert "nxdomain" in result.detail.lower()


def test_verify_dns_timeout(cfg: Config, workspace_id: str):
    import dns.exception

    claim = _claim(cfg, workspace_id)
    with patch.object(verifier, "_resolve_txt", side_effect=dns.exception.Timeout()):
        result = verifier.verify_dns(claim=claim, evidence=DnsEvidence(domain="acme.com"))
    assert result.verified is False
    assert "timeout" in result.detail.lower()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/unit/test_vendor_verifier_dns.py -v`
Expected: AttributeError on `verifier.verify_dns` / `verifier._resolve_txt`.

- [ ] **Step 4: Implement DNS verifier**

Add to `smadp/vendor/verifier.py` imports:

```python
import dns.exception
import dns.resolver
```

Add functions (after `verify_repo`):

```python
_DNS_LIFETIME_S: Final[float] = 10.0
_DNS_PREFIX: Final[str] = "_smadp-owner."


def _resolve_txt(name: str):
    """Indirection for monkeypatching in tests."""
    resolver = dns.resolver.Resolver(configure=True)
    resolver.lifetime = _DNS_LIFETIME_S
    resolver.timeout = _DNS_LIFETIME_S
    return resolver.resolve(name, "TXT")


def verify_dns(*, claim: VendorClaim, evidence: DnsEvidence) -> ClaimVerification:
    name = _DNS_PREFIX + evidence.domain
    try:
        answers = _resolve_txt(name)
    except dns.resolver.NXDOMAIN:
        return ClaimVerification(verified=False, detail=f"NXDOMAIN for {name}")
    except dns.resolver.NoAnswer:
        return ClaimVerification(verified=False, detail=f"NoAnswer for {name}")
    except dns.exception.Timeout:
        return ClaimVerification(verified=False, detail=f"Timeout resolving {name}")
    except dns.exception.DNSException as exc:
        return ClaimVerification(
            verified=False, detail=f"DNS error for {name}: {exc.__class__.__name__}"
        )
    for rdata in answers:
        for chunk in rdata.strings:
            value = chunk.decode("utf-8", errors="replace").strip()
            if hmac.compare_digest(value, claim.token):
                return ClaimVerification(
                    verified=True, detail=f"DNS TXT match at {evidence.domain}"
                )
    return ClaimVerification(
        verified=False,
        detail=f"DNS TXT mismatch at {evidence.domain} (no chunk matched token)",
    )
```

Append `verify_dns` to `__all__`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_vendor_verifier_dns.py tests/unit/test_vendor_verifier_repo.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add smadp/vendor/verifier.py pyproject.toml tests/unit/test_vendor_verifier_dns.py uv.lock 2>/dev/null
git commit -m "feat(vendor): add DNS-TXT claim verifier (dnspython)"
```

---

## Task 7: Verifier — email magic-link method + dispatch

**Files:**
- Modify: `smadp/config.py`
- Modify: `smadp/vendor/verifier.py`
- Create: `tests/unit/test_vendor_verifier_email.py`

- [ ] **Step 1: Add `public_base_url` to Config**

Read `smadp/config.py` to confirm the existing structure (Pydantic `BaseSettings` or dataclass with env reads). Add a `public_base_url` field with env fallback `SMADP_PUBLIC_BASE_URL`, default `"http://localhost:8000"`. Validate scheme = `https://` or `http://localhost*`. Match the existing field-declaration style in that file.

- [ ] **Step 2: Write the failing test**

Create `tests/unit/test_vendor_verifier_email.py`:

```python
"""Unit tests for vendor.verifier email + dispatch."""

from __future__ import annotations

from pathlib import Path

import pytest

from smadp.config import Config
from smadp.schemas.tenancy import Plan
from smadp.schemas.vendor import (
    ClaimMethod,
    DnsEvidence,
    EmailEvidence,
    RepoEvidence,
    TokenEvidence,
)
from smadp.tenancy import store as tenancy
from smadp.vendor import store, verifier


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return Config()


@pytest.fixture
def workspace_id(cfg: Config) -> str:
    ws = tenancy.create_workspace(name="V", plan=Plan.PUBLIC, config=cfg)
    return ws.id


def _claim_email(cfg, ws):
    return store.create_claim(
        workspace_id=ws,
        agent_id="claude-code",
        vendor_user_id="user_a",
        method=ClaimMethod.EMAIL,
        evidence_url=None,
        config=cfg,
    )


def test_verify_email_token_match(cfg: Config, workspace_id: str):
    claim = _claim_email(cfg, workspace_id)
    result = verifier.verify_email(claim=claim, evidence=TokenEvidence(token=claim.token))
    assert result.verified is True
    assert "match" in result.detail.lower()


def test_verify_email_token_mismatch(cfg: Config, workspace_id: str):
    claim = _claim_email(cfg, workspace_id)
    result = verifier.verify_email(claim=claim, evidence=TokenEvidence(token="x" * 32))
    assert result.verified is False


def test_dispatch_routes_repo(cfg: Config, workspace_id: str, monkeypatch: pytest.MonkeyPatch):
    claim = store.create_claim(
        workspace_id=workspace_id,
        agent_id="claude-code",
        vendor_user_id="user_a",
        method=ClaimMethod.REPO,
        evidence_url="https://github.com/o/r/raw/main",
        config=cfg,
    )
    called: dict[str, object] = {}

    def fake_repo(*, claim, evidence):
        called["claim"] = claim
        called["evidence"] = evidence
        return verifier.ClaimVerification(verified=True, detail="stub")

    monkeypatch.setattr(verifier, "verify_repo", fake_repo)
    result = verifier.verify(claim=claim, evidence=RepoEvidence(repo_url="https://github.com/o/r/raw/main"))
    assert result.verified is True
    assert called["claim"] is claim


def test_dispatch_routes_dns(cfg: Config, workspace_id: str, monkeypatch: pytest.MonkeyPatch):
    claim = store.create_claim(
        workspace_id=workspace_id,
        agent_id="claude-code",
        vendor_user_id="user_a",
        method=ClaimMethod.DNS,
        evidence_url=None,
        config=cfg,
    )
    monkeypatch.setattr(
        verifier,
        "verify_dns",
        lambda *, claim, evidence: verifier.ClaimVerification(verified=True, detail="dns-stub"),
    )
    result = verifier.verify(claim=claim, evidence=DnsEvidence(domain="acme.com"))
    assert result.verified is True
    assert "dns-stub" in result.detail


def test_dispatch_method_evidence_mismatch_raises(cfg: Config, workspace_id: str):
    claim = store.create_claim(
        workspace_id=workspace_id,
        agent_id="claude-code",
        vendor_user_id="user_a",
        method=ClaimMethod.REPO,
        evidence_url="https://github.com/o/r/raw/main",
        config=cfg,
    )
    with pytest.raises(ValueError, match="evidence type"):
        verifier.verify(claim=claim, evidence=DnsEvidence(domain="acme.com"))


def test_email_magic_link_url():
    url = verifier.build_email_magic_link(
        public_base_url="https://smadp.example",
        claim_id="vc_AB12CD34",
        token="t" * 32,
    )
    assert url == "https://smadp.example/vendor/claims/vc_AB12CD34/verify?token=" + ("t" * 32)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/unit/test_vendor_verifier_email.py -v`
Expected: AttributeError on `verifier.verify_email` / `verifier.verify` / `verifier.build_email_magic_link`.

- [ ] **Step 4: Implement email + dispatch**

Append to `smadp/vendor/verifier.py`:

```python
def verify_email(*, claim: VendorClaim, evidence: TokenEvidence) -> ClaimVerification:
    if hmac.compare_digest(evidence.token, claim.token):
        return ClaimVerification(verified=True, detail="email token match")
    return ClaimVerification(verified=False, detail="email token mismatch")


def build_email_magic_link(*, public_base_url: str, claim_id: str, token: str) -> str:
    base = public_base_url.rstrip("/")
    return f"{base}/vendor/claims/{claim_id}/verify?token={token}"


def verify(
    *,
    claim: VendorClaim,
    evidence: RepoEvidence | DnsEvidence | TokenEvidence,
) -> ClaimVerification:
    if claim.method == ClaimMethod.REPO:
        if not isinstance(evidence, RepoEvidence):
            raise ValueError("evidence type must be RepoEvidence for method=repo")
        return verify_repo(claim=claim, evidence=evidence)
    if claim.method == ClaimMethod.DNS:
        if not isinstance(evidence, DnsEvidence):
            raise ValueError("evidence type must be DnsEvidence for method=dns")
        return verify_dns(claim=claim, evidence=evidence)
    if claim.method == ClaimMethod.EMAIL:
        if not isinstance(evidence, TokenEvidence):
            raise ValueError("evidence type must be TokenEvidence for method=email")
        return verify_email(claim=claim, evidence=evidence)
    raise ValueError(f"unknown claim method: {claim.method!r}")
```

Add `verify_email`, `verify`, `build_email_magic_link` to `__all__`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_vendor_verifier_email.py tests/unit/test_vendor_verifier_dns.py tests/unit/test_vendor_verifier_repo.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add smadp/config.py smadp/vendor/verifier.py tests/unit/test_vendor_verifier_email.py
git commit -m "feat(vendor): add email magic-link verifier + verify dispatch"
```

---

## Task 8: Vendor API — claims router

**Files:**
- Create: `smadp/vendor/api.py` (claims endpoints only — responses + disputes added in Task 9 + 10)
- Modify: `smadp/api/routes/__init__.py`
- Create: `tests/unit/test_vendor_api_claims.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_vendor_api_claims.py`:

```python
"""Unit tests for vendor.api claim endpoints."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from smadp.api.app import build_app
from smadp.config import Config
from smadp.schemas.tenancy import Plan, Role
from smadp.tenancy import store as tenancy


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    monkeypatch.setenv("SMADP_PUBLIC_BASE_URL", "https://smadp.example")
    return Config()


@pytest.fixture
def workspace_id(cfg: Config) -> str:
    ws = tenancy.create_workspace(name="V", plan=Plan.PUBLIC, config=cfg)
    tenancy.add_member(workspace_id=ws.id, user_id="user_a", role=Role.EDITOR, config=cfg)
    return ws.id


@pytest.fixture
def client(cfg: Config) -> TestClient:
    return TestClient(build_app())


def _hdrs(workspace_id: str, user_id: str = "user_a") -> dict[str, str]:
    return {"X-SMADP-Workspace": workspace_id, "X-SMADP-User": user_id}


def test_create_claim_repo_returns_token(client: TestClient, workspace_id: str):
    r = client.post(
        "/api/vendor/claims",
        json={
            "agent_id": "claude-code",
            "method": "repo",
            "evidence_url": "https://github.com/o/r/raw/main",
        },
        headers=_hdrs(workspace_id),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["claim"]["id"].startswith("vc_")
    assert body["claim"]["status"] == "pending"
    assert "token" in body
    assert len(body["token"]) >= 32
    assert body["instructions"]["method"] == "repo"
    assert "owner.txt" in body["instructions"]["text"]


def test_create_claim_email_returns_magic_link(client: TestClient, workspace_id: str):
    r = client.post(
        "/api/vendor/claims",
        json={"agent_id": "claude-code", "method": "email", "evidence_url": None},
        headers=_hdrs(workspace_id),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["instructions"]["method"] == "email"
    assert body["instructions"]["magic_link_url"].startswith(
        "https://smadp.example/vendor/claims/"
    )
    assert "?token=" in body["instructions"]["magic_link_url"]


def test_create_claim_invalid_agent_id_400(client: TestClient, workspace_id: str):
    r = client.post(
        "/api/vendor/claims",
        json={"agent_id": "Bad_Slug!", "method": "repo", "evidence_url": "https://github.com/o/r/raw/main"},
        headers=_hdrs(workspace_id),
    )
    assert r.status_code == 422


def test_create_claim_requires_workspace(client: TestClient):
    r = client.post(
        "/api/vendor/claims",
        json={"agent_id": "claude-code", "method": "repo", "evidence_url": "https://github.com/o/r/raw/main"},
    )
    assert r.status_code in {401, 403, 422}


def test_list_claims(client: TestClient, workspace_id: str):
    client.post(
        "/api/vendor/claims",
        json={"agent_id": "claude-code", "method": "repo", "evidence_url": "https://github.com/o/r/raw/main"},
        headers=_hdrs(workspace_id),
    )
    r = client.get("/api/vendor/claims", headers=_hdrs(workspace_id))
    assert r.status_code == 200
    assert len(r.json()) == 1
    # Token is NEVER returned on list
    assert "token" not in r.json()[0]


@respx.mock
def test_verify_claim_repo_happy_path(client: TestClient, workspace_id: str):
    create = client.post(
        "/api/vendor/claims",
        json={"agent_id": "claude-code", "method": "repo", "evidence_url": "https://github.com/o/r/raw/main"},
        headers=_hdrs(workspace_id),
    )
    cid = create.json()["claim"]["id"]
    token = create.json()["token"]
    respx.get("https://github.com/o/r/raw/main/.smadp/owner.txt").mock(
        return_value=httpx.Response(200, text=token)
    )
    r = client.post(
        f"/api/vendor/claims/{cid}/verify",
        json={"method": "repo", "evidence": {"repo_url": "https://github.com/o/r/raw/main"}},
        headers=_hdrs(workspace_id),
    )
    assert r.status_code == 200
    assert r.json()["claim"]["status"] == "verified"
    assert r.json()["verification"]["verified"] is True


@respx.mock
def test_verify_claim_repo_mismatch_409(client: TestClient, workspace_id: str):
    create = client.post(
        "/api/vendor/claims",
        json={"agent_id": "claude-code", "method": "repo", "evidence_url": "https://github.com/o/r/raw/main"},
        headers=_hdrs(workspace_id),
    )
    cid = create.json()["claim"]["id"]
    respx.get("https://github.com/o/r/raw/main/.smadp/owner.txt").mock(
        return_value=httpx.Response(200, text="not-the-token")
    )
    r = client.post(
        f"/api/vendor/claims/{cid}/verify",
        json={"method": "repo", "evidence": {"repo_url": "https://github.com/o/r/raw/main"}},
        headers=_hdrs(workspace_id),
    )
    assert r.status_code == 409
    body = r.json()
    assert body["claim"]["status"] == "pending"
    assert body["verification"]["verified"] is False


def test_revoke_claim(client: TestClient, workspace_id: str):
    create = client.post(
        "/api/vendor/claims",
        json={"agent_id": "claude-code", "method": "repo", "evidence_url": "https://github.com/o/r/raw/main"},
        headers=_hdrs(workspace_id),
    )
    cid = create.json()["claim"]["id"]
    r = client.post(f"/api/vendor/claims/{cid}/revoke", headers=_hdrs(workspace_id))
    assert r.status_code == 200
    assert r.json()["status"] == "revoked"


def test_cross_workspace_404(client: TestClient, cfg: Config, workspace_id: str):
    create = client.post(
        "/api/vendor/claims",
        json={"agent_id": "claude-code", "method": "repo", "evidence_url": "https://github.com/o/r/raw/main"},
        headers=_hdrs(workspace_id),
    )
    cid = create.json()["claim"]["id"]
    other = tenancy.create_workspace(name="O", plan=Plan.PUBLIC, config=cfg)
    tenancy.add_member(workspace_id=other.id, user_id="user_b", role=Role.EDITOR, config=cfg)
    r = client.get("/api/vendor/claims", headers=_hdrs(other.id, "user_b"))
    assert r.status_code == 200
    assert all(c["id"] != cid for c in r.json())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_vendor_api_claims.py -v`
Expected: 404s — `/api/vendor/claims` not registered.

- [ ] **Step 3: Implement the claims router**

Create `smadp/vendor/api.py`:

```python
"""FastAPI router for /api/vendor."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from smadp.config import Config, load_config
from smadp.schemas.tenancy import Role, Workspace
from smadp.schemas.vendor import (
    ClaimMethod,
    ClaimVerification,
    DnsEvidence,
    EmailEvidence,
    RepoEvidence,
    TokenEvidence,
    VendorClaim,
)
from smadp.tenancy.deps import current_user_id, current_workspace, require_role
from smadp.vendor import store, verifier

router = APIRouter(prefix="/vendor", tags=["vendor"])


class _Instructions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: ClaimMethod
    text: str
    magic_link_url: str | None = None


class _CreateClaimBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    method: ClaimMethod
    evidence_url: str | None = None


class _CreateClaimResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: VendorClaim
    token: str
    instructions: _Instructions


class _VerifyEvidence(BaseModel):
    """Discriminated by method on the parent body."""

    model_config = ConfigDict(extra="allow")


class _VerifyClaimBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: ClaimMethod
    evidence: dict[str, Any] = Field(default_factory=dict)


class _VerifyClaimResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: VendorClaim
    verification: ClaimVerification


def _build_instructions(method: ClaimMethod, claim_id: str, token: str, cfg: Config) -> _Instructions:
    if method == ClaimMethod.REPO:
        return _Instructions(
            method=method,
            text=(
                f"Place the token in your repo at .smadp/owner.txt and POST verify with"
                f" {{'repo_url': '<base raw URL>'}}. Token: {token}"
            ),
        )
    if method == ClaimMethod.DNS:
        return _Instructions(
            method=method,
            text=(
                f"Add a TXT record at _smadp-owner.<your-domain> with value {token}"
                f" and POST verify with {{'domain': '<your-domain>'}}."
            ),
        )
    if method == ClaimMethod.EMAIL:
        link = verifier.build_email_magic_link(
            public_base_url=cfg.public_base_url, claim_id=claim_id, token=token
        )
        return _Instructions(
            method=method,
            text=(
                "Visit the magic-link URL OR POST verify with {'token': '<token>'}."
                " The operator must deliver this URL to the vendor out-of-band; SMADP"
                " does not send email in this version."
            ),
            magic_link_url=link,
        )
    raise ValueError(f"unknown method: {method!r}")


def _coerce_evidence(method: ClaimMethod, raw: dict[str, Any]):
    if method == ClaimMethod.REPO:
        return RepoEvidence(**raw)
    if method == ClaimMethod.DNS:
        return DnsEvidence(**raw)
    if method == ClaimMethod.EMAIL:
        return TokenEvidence(**raw)
    raise ValueError(f"unknown method: {method!r}")


@router.post(
    "/claims",
    response_model=_CreateClaimResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_claim(
    body: _CreateClaimBody,
    workspace: Workspace = Depends(current_workspace),
    user_id: str = Depends(current_user_id),
    _role: None = Depends(require_role(Role.EDITOR)),
) -> Any:
    cfg = load_config()
    claim = store.create_claim(
        workspace_id=workspace.id,
        agent_id=body.agent_id,
        vendor_user_id=user_id,
        method=body.method,
        evidence_url=body.evidence_url,
        config=cfg,
    )
    instructions = _build_instructions(body.method, claim.id, claim.token, cfg)
    return _CreateClaimResponse(claim=claim, token=claim.token, instructions=instructions)


@router.get("/claims", response_model=list[VendorClaim])
def list_claims(
    agent_id: str | None = None,
    workspace: Workspace = Depends(current_workspace),
    _role: None = Depends(require_role(Role.EDITOR)),
) -> Any:
    claims = store.list_claims(workspace_id=workspace.id, agent_id=agent_id)
    # NEVER return the raw token on list — strip it
    return [c.model_copy(update={"token": "REDACTED"}) for c in claims]


@router.post(
    "/claims/{claim_id}/verify",
    response_model=_VerifyClaimResponse,
)
def verify_claim(
    claim_id: str,
    body: _VerifyClaimBody,
    workspace: Workspace = Depends(current_workspace),
    user_id: str = Depends(current_user_id),
    _role: None = Depends(require_role(Role.EDITOR)),
) -> Any:
    try:
        claim = store.get_claim(claim_id=claim_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if claim.workspace_id != workspace.id or claim.vendor_user_id != user_id:
        raise HTTPException(status_code=404, detail="claim not found in this workspace")
    if body.method != claim.method:
        raise HTTPException(
            status_code=400,
            detail=f"verify method ({body.method.value}) must match claim method ({claim.method.value})",
        )
    try:
        evidence = _coerce_evidence(body.method, body.evidence)
    except Exception as exc:  # ValidationError or ValueError
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result = verifier.verify(claim=claim, evidence=evidence)
    if result.verified:
        store.mark_claim_verified(claim_id=claim_id)
        claim = store.get_claim(claim_id=claim_id)
        return _VerifyClaimResponse(claim=claim, verification=result)
    # Surface mismatch as 409 so the operator sees it as a state conflict, not a server error
    return _verify_failed_response(claim, result)


def _verify_failed_response(claim: VendorClaim, result: ClaimVerification):
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=409,
        content=_VerifyClaimResponse(claim=claim, verification=result).model_dump(mode="json"),
    )


@router.post("/claims/{claim_id}/revoke", response_model=VendorClaim)
def revoke_claim(
    claim_id: str,
    workspace: Workspace = Depends(current_workspace),
    user_id: str = Depends(current_user_id),
    _role: None = Depends(require_role(Role.EDITOR)),
) -> Any:
    try:
        claim = store.get_claim(claim_id=claim_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if claim.workspace_id != workspace.id or claim.vendor_user_id != user_id:
        raise HTTPException(status_code=404, detail="claim not found in this workspace")
    store.revoke_claim(claim_id=claim_id)
    return store.get_claim(claim_id=claim_id)


__all__ = ["router"]
```

Modify `smadp/api/routes/__init__.py` — add the import in alphabetical position and append `vendor.router` to ROUTERS. Read the file first if you're unsure of the exact pattern; mirror it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_vendor_api_claims.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add smadp/vendor/api.py smadp/api/routes/__init__.py tests/unit/test_vendor_api_claims.py
git commit -m "feat(vendor): add /api/vendor/claims router (create/list/verify/revoke)"
```

---

## Task 9: Vendor API — responses + disputes routes

**Files:**
- Modify: `smadp/vendor/api.py`
- Create: `tests/unit/test_vendor_api_responses.py`
- Create: `tests/unit/test_vendor_api_disputes.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_vendor_api_responses.py`:

```python
"""Unit tests for /api/vendor/responses."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from smadp.api.app import build_app
from smadp.config import Config
from smadp.schemas.tenancy import Plan, Role
from smadp.tenancy import store as tenancy


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    monkeypatch.setenv("SMADP_PUBLIC_BASE_URL", "https://smadp.example")
    return Config()


@pytest.fixture
def workspace_id(cfg: Config) -> str:
    ws = tenancy.create_workspace(name="V", plan=Plan.PUBLIC, config=cfg)
    tenancy.add_member(workspace_id=ws.id, user_id="user_a", role=Role.EDITOR, config=cfg)
    return ws.id


@pytest.fixture
def client(cfg: Config) -> TestClient:
    return TestClient(build_app())


def _hdrs(workspace_id: str, user_id: str = "user_a") -> dict[str, str]:
    return {"X-SMADP-Workspace": workspace_id, "X-SMADP-User": user_id}


def test_post_response_requires_verified_claim(client: TestClient, workspace_id: str):
    r = client.post(
        "/api/vendor/responses",
        json={"verdict_id": "vdt_X", "agent_id": "claude-code", "body_md": "hello"},
        headers=_hdrs(workspace_id),
    )
    assert r.status_code == 403
    assert "verified claim" in r.json()["detail"].lower()


@respx.mock
def test_post_response_after_verify(client: TestClient, workspace_id: str):
    # Create + verify claim via API
    create = client.post(
        "/api/vendor/claims",
        json={"agent_id": "claude-code", "method": "repo", "evidence_url": "https://github.com/o/r/raw/main"},
        headers=_hdrs(workspace_id),
    )
    cid = create.json()["claim"]["id"]
    token = create.json()["token"]
    respx.get("https://github.com/o/r/raw/main/.smadp/owner.txt").mock(
        return_value=httpx.Response(200, text=token)
    )
    client.post(
        f"/api/vendor/claims/{cid}/verify",
        json={"method": "repo", "evidence": {"repo_url": "https://github.com/o/r/raw/main"}},
        headers=_hdrs(workspace_id),
    )
    r = client.post(
        "/api/vendor/responses",
        json={"verdict_id": "vdt_X", "agent_id": "claude-code", "body_md": "we mitigated"},
        headers=_hdrs(workspace_id),
    )
    assert r.status_code == 201
    assert r.json()["body_md"] == "we mitigated"


def test_list_responses_for_verdict(client: TestClient, workspace_id: str):
    r = client.get("/api/vendor/responses", params={"verdict_id": "vdt_X"}, headers=_hdrs(workspace_id))
    assert r.status_code == 200
    assert r.json() == []
```

Create `tests/unit/test_vendor_api_disputes.py`:

```python
"""Unit tests for /api/vendor/disputes."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from smadp.api.app import build_app
from smadp.config import Config
from smadp.schemas.tenancy import Plan, Role
from smadp.tenancy import store as tenancy


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    monkeypatch.setenv("SMADP_PUBLIC_BASE_URL", "https://smadp.example")
    return Config()


@pytest.fixture
def workspace_id(cfg: Config) -> str:
    ws = tenancy.create_workspace(name="V", plan=Plan.PUBLIC, config=cfg)
    tenancy.add_member(workspace_id=ws.id, user_id="user_a", role=Role.EDITOR, config=cfg)
    tenancy.add_member(workspace_id=ws.id, user_id="op_admin", role=Role.ADMIN, config=cfg)
    return ws.id


@pytest.fixture
def client(cfg: Config) -> TestClient:
    return TestClient(build_app())


def _hdrs(workspace_id: str, user_id: str = "user_a") -> dict[str, str]:
    return {"X-SMADP-Workspace": workspace_id, "X-SMADP-User": user_id}


@respx.mock
def _verify_claim(client, workspace_id) -> None:
    create = client.post(
        "/api/vendor/claims",
        json={"agent_id": "claude-code", "method": "repo", "evidence_url": "https://github.com/o/r/raw/main"},
        headers=_hdrs(workspace_id),
    )
    cid = create.json()["claim"]["id"]
    token = create.json()["token"]
    respx.get("https://github.com/o/r/raw/main/.smadp/owner.txt").mock(
        return_value=httpx.Response(200, text=token)
    )
    client.post(
        f"/api/vendor/claims/{cid}/verify",
        json={"method": "repo", "evidence": {"repo_url": "https://github.com/o/r/raw/main"}},
        headers=_hdrs(workspace_id),
    )


def test_file_dispute_requires_verified_claim(client: TestClient, workspace_id: str):
    r = client.post(
        "/api/vendor/disputes",
        json={
            "verdict_id": "vdt_X",
            "agent_id": "claude-code",
            "argument_md": "we contest",
            "requested_outcome": "reeval",
        },
        headers=_hdrs(workspace_id),
    )
    assert r.status_code == 403


def test_file_dispute_after_verify(client: TestClient, workspace_id: str):
    _verify_claim(client, workspace_id)
    r = client.post(
        "/api/vendor/disputes",
        json={
            "verdict_id": "vdt_X",
            "agent_id": "claude-code",
            "argument_md": "we contest because ...",
            "requested_outcome": "reeval",
        },
        headers=_hdrs(workspace_id),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "triage"
    assert body["id"].startswith("dsp_")


def test_triage_substantive_then_resolve_stands(client: TestClient, workspace_id: str):
    _verify_claim(client, workspace_id)
    f = client.post(
        "/api/vendor/disputes",
        json={
            "verdict_id": "vdt_X",
            "agent_id": "claude-code",
            "argument_md": "we contest because ...",
            "requested_outcome": "reeval",
        },
        headers=_hdrs(workspace_id),
    )
    did = f.json()["id"]
    op = client.patch(
        f"/api/vendor/disputes/{did}",
        json={"decision": "substantive"},
        headers=_hdrs(workspace_id, "op_admin"),
    )
    assert op.status_code == 200
    assert op.json()["status"] == "pending_review"
    assert op.json()["sla_breached_at"] is not None

    res = client.patch(
        f"/api/vendor/disputes/{did}",
        json={"decision": "stands", "rationale_md": "evidence reviewed; verdict confirmed"},
        headers=_hdrs(workspace_id, "op_admin"),
    )
    assert res.status_code == 200
    assert res.json()["status"] == "resolved_stands"


def test_triage_requires_admin(client: TestClient, workspace_id: str):
    _verify_claim(client, workspace_id)
    f = client.post(
        "/api/vendor/disputes",
        json={
            "verdict_id": "vdt_X",
            "agent_id": "claude-code",
            "argument_md": "we contest because ...",
            "requested_outcome": "reeval",
        },
        headers=_hdrs(workspace_id),
    )
    did = f.json()["id"]
    # editor (user_a) cannot triage
    op = client.patch(
        f"/api/vendor/disputes/{did}",
        json={"decision": "substantive"},
        headers=_hdrs(workspace_id, "user_a"),
    )
    assert op.status_code == 403


def test_invalid_transition_409(client: TestClient, workspace_id: str):
    _verify_claim(client, workspace_id)
    f = client.post(
        "/api/vendor/disputes",
        json={
            "verdict_id": "vdt_X",
            "agent_id": "claude-code",
            "argument_md": "we contest because ...",
            "requested_outcome": "reeval",
        },
        headers=_hdrs(workspace_id),
    )
    did = f.json()["id"]
    # Skip triage — try resolved_stands directly
    res = client.patch(
        f"/api/vendor/disputes/{did}",
        json={"decision": "stands", "rationale_md": "x"},
        headers=_hdrs(workspace_id, "op_admin"),
    )
    assert res.status_code == 409
    assert "invalid" in res.json()["detail"].lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_vendor_api_responses.py tests/unit/test_vendor_api_disputes.py -v`
Expected: 404s — endpoints don't exist.

- [ ] **Step 3: Implement responses + disputes routes**

Append to `smadp/vendor/api.py`:

```python
from smadp.schemas.dispute import (
    Dispute,
    DisputeDecision,
    DisputeStatus,
    RequestedOutcome,
)
from smadp.schemas.vendor import VendorResponse


class _PostResponseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict_id: str
    agent_id: str
    body_md: str = Field(min_length=1, max_length=8192)


@router.post(
    "/responses",
    response_model=VendorResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_response(
    body: _PostResponseBody,
    workspace: Workspace = Depends(current_workspace),
    user_id: str = Depends(current_user_id),
    _role: None = Depends(require_role(Role.EDITOR)),
) -> Any:
    found = store.find_verified_claim(
        workspace_id=workspace.id, vendor_user_id=user_id, agent_id=body.agent_id
    )
    if found is None:
        raise HTTPException(
            status_code=403, detail="posting requires a verified claim for this agent"
        )
    return store.post_response(
        workspace_id=workspace.id,
        verdict_id=body.verdict_id,
        vendor_user_id=user_id,
        body_md=body.body_md,
    )


@router.get("/responses", response_model=list[VendorResponse])
def list_responses(
    verdict_id: str,
    workspace: Workspace = Depends(current_workspace),
    _role: None = Depends(require_role(Role.EDITOR)),
) -> Any:
    return store.list_responses(workspace_id=workspace.id, verdict_id=verdict_id)


class _FileDisputeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict_id: str
    agent_id: str
    argument_md: str = Field(min_length=1, max_length=16384)
    requested_outcome: RequestedOutcome


@router.post(
    "/disputes",
    response_model=Dispute,
    status_code=status.HTTP_201_CREATED,
)
def file_dispute(
    body: _FileDisputeBody,
    workspace: Workspace = Depends(current_workspace),
    user_id: str = Depends(current_user_id),
    _role: None = Depends(require_role(Role.EDITOR)),
) -> Any:
    found = store.find_verified_claim(
        workspace_id=workspace.id, vendor_user_id=user_id, agent_id=body.agent_id
    )
    if found is None:
        raise HTTPException(
            status_code=403, detail="filing requires a verified claim for this agent"
        )
    return store.file_dispute(
        workspace_id=workspace.id,
        verdict_id=body.verdict_id,
        vendor_user_id=user_id,
        argument_md=body.argument_md,
        requested_outcome=body.requested_outcome,
    )


@router.get("/disputes", response_model=list[Dispute])
def list_disputes(
    verdict_id: str | None = None,
    workspace: Workspace = Depends(current_workspace),
    _role: None = Depends(require_role(Role.EDITOR)),
) -> Any:
    return store.list_disputes(workspace_id=workspace.id, verdict_id=verdict_id)


class _UpdateDisputeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: DisputeDecision
    rationale_md: str | None = None


@router.patch("/disputes/{dispute_id}", response_model=Dispute)
def update_dispute(
    dispute_id: str,
    body: _UpdateDisputeBody,
    workspace: Workspace = Depends(current_workspace),
    _role: None = Depends(require_role(Role.ADMIN)),
) -> Any:
    try:
        existing = store.get_dispute(dispute_id=dispute_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if existing.workspace_id != workspace.id:
        raise HTTPException(status_code=404, detail="dispute not found in this workspace")
    try:
        return store.update_dispute_status(
            dispute_id=dispute_id,
            decision=body.decision,
            rationale_md=body.rationale_md,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_vendor_api_responses.py tests/unit/test_vendor_api_disputes.py tests/unit/test_vendor_api_claims.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add smadp/vendor/api.py tests/unit/test_vendor_api_responses.py tests/unit/test_vendor_api_disputes.py
git commit -m "feat(vendor): add responses + disputes routes (file/triage/resolve)"
```

---

## Task 10: Vendor CLI subgroup

**Files:**
- Create: `smadp/vendor/cli.py`
- Modify: `smadp/cli.py`
- Create: `tests/unit/test_vendor_cli.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_vendor_cli.py`:

```python
"""Smoke tests for the vendor CLI subgroup."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from click.testing import CliRunner

from smadp.cli import cli
from smadp.config import Config
from smadp.schemas.tenancy import Plan, Role
from smadp.tenancy import store as tenancy


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    monkeypatch.setenv("SMADP_PUBLIC_BASE_URL", "https://smadp.example")
    return Config()


@pytest.fixture
def workspace_id(cfg: Config, monkeypatch: pytest.MonkeyPatch) -> str:
    ws = tenancy.create_workspace(name="V", plan=Plan.PUBLIC, config=cfg)
    tenancy.add_member(workspace_id=ws.id, user_id="user_a", role=Role.ADMIN, config=cfg)
    monkeypatch.setenv("SMADP_WORKSPACE_ID", ws.id)
    monkeypatch.setenv("SMADP_USER_ID", "user_a")
    return ws.id


def test_claims_create_outputs_token(cfg: Config, workspace_id: str):
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "vendor", "claims", "create",
            "--agent-id", "claude-code",
            "--method", "repo",
            "--evidence-url", "https://github.com/o/r/raw/main",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "vc_" in result.output
    assert "token:" in result.output.lower()


def test_claims_ls_redacts_token(cfg: Config, workspace_id: str):
    runner = CliRunner()
    runner.invoke(
        cli,
        [
            "vendor", "claims", "create",
            "--agent-id", "claude-code",
            "--method", "repo",
            "--evidence-url", "https://github.com/o/r/raw/main",
        ],
    )
    result = runner.invoke(cli, ["vendor", "claims", "ls"])
    assert result.exit_code == 0
    assert "claude-code" in result.output


@respx.mock
def test_claims_verify_repo(cfg: Config, workspace_id: str):
    runner = CliRunner()
    create = runner.invoke(
        cli,
        [
            "vendor", "claims", "create",
            "--agent-id", "claude-code",
            "--method", "repo",
            "--evidence-url", "https://github.com/o/r/raw/main",
        ],
    )
    # Extract claim id from "vc_XXXXXXXX" in output
    cid = next(line for line in create.output.splitlines() if "vc_" in line).split()[-1]
    token = next(line for line in create.output.splitlines() if "token:" in line.lower()).split()[-1]
    respx.get("https://github.com/o/r/raw/main/.smadp/owner.txt").mock(
        return_value=httpx.Response(200, text=token)
    )
    result = runner.invoke(
        cli,
        [
            "vendor", "claims", "verify", cid,
            "--evidence-json", json.dumps({"repo_url": "https://github.com/o/r/raw/main"}),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "verified" in result.output.lower()


def test_disputes_file_then_triage(cfg: Config, workspace_id: str):
    """Skip claim verification by directly seeding store."""
    from smadp.schemas.vendor import ClaimMethod
    from smadp.vendor import store

    claim = store.create_claim(
        workspace_id=workspace_id,
        agent_id="claude-code",
        vendor_user_id="user_a",
        method=ClaimMethod.REPO,
        evidence_url="https://github.com/o/r/raw/main",
        config=cfg,
    )
    store.mark_claim_verified(claim_id=claim.id, config=cfg)

    runner = CliRunner()
    f = runner.invoke(
        cli,
        [
            "vendor", "disputes", "file",
            "--verdict-id", "vdt_X",
            "--agent-id", "claude-code",
            "--argument-md", "we contest because ...",
            "--requested-outcome", "reeval",
        ],
    )
    assert f.exit_code == 0, f.output
    did = next(line for line in f.output.splitlines() if "dsp_" in line).split()[-1]
    triage = runner.invoke(
        cli,
        ["vendor", "disputes", "triage", did, "--decision", "substantive"],
    )
    assert triage.exit_code == 0, triage.output
    assert "pending_review" in triage.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_vendor_cli.py -v`
Expected: ImportError on `vendor` subgroup not registered.

- [ ] **Step 3: Implement the CLI subgroup**

Create `smadp/vendor/cli.py`:

```python
"""Click subgroup: smadp vendor {claims,responses,disputes} ..."""

from __future__ import annotations

import json
import os
import sys

import click
from rich.console import Console
from rich.table import Table

from smadp.config import load_config
from smadp.schemas.dispute import DisputeDecision, RequestedOutcome
from smadp.schemas.vendor import (
    ClaimMethod,
    DnsEvidence,
    RepoEvidence,
    TokenEvidence,
)
from smadp.vendor import store, verifier

_console = Console()


def _workspace_id() -> str:
    v = os.environ.get("SMADP_WORKSPACE_ID")
    if not v:
        click.echo("SMADP_WORKSPACE_ID env or --workspace-id is required", err=True)
        sys.exit(2)
    return v


def _user_id() -> str:
    v = os.environ.get("SMADP_USER_ID")
    if not v:
        click.echo("SMADP_USER_ID env or --user-id is required", err=True)
        sys.exit(2)
    return v


@click.group(name="vendor")
def vendor_group() -> None:
    """Vendor flows: claims, responses, disputes."""


@vendor_group.group("claims")
def _claims() -> None:
    """Vendor claim management."""


@_claims.command("create")
@click.option("--agent-id", required=True)
@click.option("--method", type=click.Choice(["repo", "dns", "email"]), required=True)
@click.option("--evidence-url", default=None, help="Required for method=repo (the repo raw base URL).")
def _claims_create(agent_id: str, method: str, evidence_url: str | None) -> None:
    cfg = load_config()
    claim = store.create_claim(
        workspace_id=_workspace_id(),
        agent_id=agent_id,
        vendor_user_id=_user_id(),
        method=ClaimMethod(method),
        evidence_url=evidence_url,
        config=cfg,
    )
    _console.print(f"created  {claim.id}")
    _console.print(f"token:   {claim.token}")
    if method == "email":
        link = verifier.build_email_magic_link(
            public_base_url=cfg.public_base_url, claim_id=claim.id, token=claim.token
        )
        _console.print(f"magic-link: {link}")


@_claims.command("ls")
@click.option("--agent-id", default=None)
def _claims_ls(agent_id: str | None) -> None:
    claims = store.list_claims(workspace_id=_workspace_id(), agent_id=agent_id)
    table = Table(title="Vendor Claims")
    for col in ("id", "agent", "method", "status", "created_at"):
        table.add_column(col)
    for c in claims:
        table.add_row(c.id, c.agent_id, c.method.value, c.status.value, c.created_at.isoformat())
    _console.print(table)


@_claims.command("verify")
@click.argument("claim_id")
@click.option("--evidence-json", required=True, help="JSON object matching the claim method.")
def _claims_verify(claim_id: str, evidence_json: str) -> None:
    raw = json.loads(evidence_json)
    claim = store.get_claim(claim_id=claim_id)
    if claim.method == ClaimMethod.REPO:
        evidence = RepoEvidence(**raw)
    elif claim.method == ClaimMethod.DNS:
        evidence = DnsEvidence(**raw)
    else:
        evidence = TokenEvidence(**raw)
    result = verifier.verify(claim=claim, evidence=evidence)
    if result.verified:
        store.mark_claim_verified(claim_id=claim_id)
        _console.print(f"[green]verified[/green]  {result.detail}")
    else:
        _console.print(f"[red]not verified[/red]  {result.detail}")
        sys.exit(1)


@_claims.command("revoke")
@click.argument("claim_id")
def _claims_revoke(claim_id: str) -> None:
    store.revoke_claim(claim_id=claim_id)
    _console.print(f"revoked  {claim_id}")


@vendor_group.group("responses")
def _responses() -> None:
    """Vendor responses on verdicts."""


@_responses.command("post")
@click.option("--verdict-id", required=True)
@click.option("--agent-id", required=True)
@click.option("--body-md", required=True)
def _responses_post(verdict_id: str, agent_id: str, body_md: str) -> None:
    if store.find_verified_claim(
        workspace_id=_workspace_id(), vendor_user_id=_user_id(), agent_id=agent_id
    ) is None:
        click.echo("error: posting requires a verified claim for this agent", err=True)
        sys.exit(2)
    r = store.post_response(
        workspace_id=_workspace_id(),
        verdict_id=verdict_id,
        vendor_user_id=_user_id(),
        body_md=body_md,
    )
    _console.print(f"posted  {r.id}")


@_responses.command("ls")
@click.option("--verdict-id", required=True)
def _responses_ls(verdict_id: str) -> None:
    rows = store.list_responses(workspace_id=_workspace_id(), verdict_id=verdict_id)
    table = Table(title=f"Responses — {verdict_id}")
    for col in ("id", "vendor_user_id", "created_at"):
        table.add_column(col)
    for r in rows:
        table.add_row(r.id, r.vendor_user_id, r.created_at.isoformat())
    _console.print(table)


@vendor_group.group("disputes")
def _disputes() -> None:
    """Vendor disputes."""


@_disputes.command("file")
@click.option("--verdict-id", required=True)
@click.option("--agent-id", required=True)
@click.option("--argument-md", required=True)
@click.option("--requested-outcome", type=click.Choice(["reeval", "withdraw", "amend"]), required=True)
def _disputes_file(verdict_id: str, agent_id: str, argument_md: str, requested_outcome: str) -> None:
    if store.find_verified_claim(
        workspace_id=_workspace_id(), vendor_user_id=_user_id(), agent_id=agent_id
    ) is None:
        click.echo("error: filing requires a verified claim for this agent", err=True)
        sys.exit(2)
    d = store.file_dispute(
        workspace_id=_workspace_id(),
        verdict_id=verdict_id,
        vendor_user_id=_user_id(),
        argument_md=argument_md,
        requested_outcome=RequestedOutcome(requested_outcome),
    )
    _console.print(f"filed  {d.id}")


@_disputes.command("triage")
@click.argument("dispute_id")
@click.option("--decision", type=click.Choice(["spam", "substantive"]), required=True)
def _disputes_triage(dispute_id: str, decision: str) -> None:
    d = store.update_dispute_status(
        dispute_id=dispute_id,
        decision=DisputeDecision(decision),
        rationale_md=None,
    )
    _console.print(f"triaged  {d.id}  {d.status.value}")


@_disputes.command("resolve")
@click.argument("dispute_id")
@click.option("--decision", type=click.Choice(["reeval", "stands"]), required=True)
@click.option("--rationale-md", required=True)
def _disputes_resolve(dispute_id: str, decision: str, rationale_md: str) -> None:
    d = store.update_dispute_status(
        dispute_id=dispute_id,
        decision=DisputeDecision(decision),
        rationale_md=rationale_md,
    )
    _console.print(f"resolved  {d.id}  {d.status.value}")


@_disputes.command("ls")
@click.option("--verdict-id", default=None)
def _disputes_ls(verdict_id: str | None) -> None:
    rows = store.list_disputes(workspace_id=_workspace_id(), verdict_id=verdict_id)
    table = Table(title="Disputes")
    for col in ("id", "verdict_id", "status", "filed_at", "sla_breached_at"):
        table.add_column(col)
    for r in rows:
        table.add_row(
            r.id,
            r.verdict_id,
            r.status.value,
            r.filed_at.isoformat(),
            r.sla_breached_at.isoformat() if r.sla_breached_at else "—",
        )
    _console.print(table)
```

Modify `smadp/cli.py` — add the import alphabetically (e.g., near `from smadp.webhooks.cli import webhook_group`) and `cli.add_command(vendor_group)` next to the existing `cli.add_command(webhook_group)` call.

```python
from smadp.vendor.cli import vendor_group
# ... existing imports ...

# Inside the cli registration block (mirror webhook_group placement):
cli.add_command(vendor_group)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_vendor_cli.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add smadp/vendor/cli.py smadp/cli.py tests/unit/test_vendor_cli.py
git commit -m "feat(vendor): add smadp vendor CLI subgroup (claims/responses/disputes)"
```

---

## Task 11: Webhooks schema — IntegrationKind + Subscription extension

**Files:**
- Modify: `smadp/schemas/webhooks.py`
- Modify: `tests/unit/test_schemas_webhooks.py` (assumed to exist from Plan 3)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_schemas_webhooks.py`:

```python
def test_integration_kind_values_locked():
    from smadp.schemas.webhooks import IntegrationKind

    assert {k.value for k in IntegrationKind} == {"generic", "vanta", "drata", "slack"}


def test_subscription_default_integration_is_generic():
    from datetime import UTC, datetime

    from smadp.schemas.webhooks import EventType, IntegrationKind, Subscription

    sub = Subscription(
        id="sub_AB12CD34",
        workspace_id="ws_ABCD1234",
        url="https://example.com/wh",
        event_types=[EventType.PASSPORT_GENERATED],
        active=True,
        created_at=datetime.now(UTC),
    )
    assert sub.integration_kind == IntegrationKind.GENERIC
    assert sub.integration_config == {}


def test_subscription_accepts_native_integration():
    from datetime import UTC, datetime

    from smadp.schemas.webhooks import EventType, IntegrationKind, Subscription

    sub = Subscription(
        id="sub_AB12CD34",
        workspace_id="ws_ABCD1234",
        url="https://hooks.slack.com/services/abc/def",
        event_types=[EventType.PASSPORT_GENERATED],
        active=True,
        created_at=datetime.now(UTC),
        integration_kind=IntegrationKind.SLACK,
        integration_config={"channel": "#smadp-alerts"},
    )
    assert sub.integration_kind == IntegrationKind.SLACK
    assert sub.integration_config == {"channel": "#smadp-alerts"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_schemas_webhooks.py -v -k integration`
Expected: ImportError on `IntegrationKind`.

- [ ] **Step 3: Add IntegrationKind + extend Subscription**

In `smadp/schemas/webhooks.py`:

Add the enum near the top (after `EventType`, before `DeliveryStatus`):

```python
class IntegrationKind(StrEnum):
    GENERIC = "generic"
    VANTA = "vanta"
    DRATA = "drata"
    SLACK = "slack"
```

Modify `Subscription` to add two new fields. After `created_at: datetime`:

```python
    integration_kind: IntegrationKind = IntegrationKind.GENERIC
    integration_config: dict[str, Any] = Field(default_factory=dict)
```

Add `Field` to the pydantic import:

```python
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
```

Append `IntegrationKind` to `__all__`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_schemas_webhooks.py -v`
Expected: all PASS (pre-existing tests still pass; new ones pass).

- [ ] **Step 5: Commit**

```bash
git add smadp/schemas/webhooks.py tests/unit/test_schemas_webhooks.py
git commit -m "feat(webhooks): add IntegrationKind enum + extend Subscription"
```

---

## Task 12: Webhooks store — integration columns

**Files:**
- Modify: `smadp/webhooks/store.py`
- Modify: `tests/unit/test_webhooks_store.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_webhooks_store.py`:

```python
def test_create_subscription_with_native_integration(cfg: Config, workspace_id: str):
    from smadp.schemas.webhooks import IntegrationKind

    sub, _ = store.create_subscription(
        workspace_id=workspace_id,
        url="https://hooks.slack.com/services/abc/def",
        event_types=[EventType.PASSPORT_GENERATED],
        config=cfg,
        integration_kind=IntegrationKind.SLACK,
        integration_config={"channel": "#smadp-alerts"},
    )
    assert sub.integration_kind == IntegrationKind.SLACK
    assert sub.integration_config == {"channel": "#smadp-alerts"}
    loaded = store.get_subscription(subscription_id=sub.id, config=cfg)
    assert loaded.integration_kind == IntegrationKind.SLACK
    assert loaded.integration_config == {"channel": "#smadp-alerts"}


def test_create_subscription_default_is_generic(cfg: Config, workspace_id: str):
    from smadp.schemas.webhooks import IntegrationKind

    sub, _ = store.create_subscription(
        workspace_id=workspace_id,
        url="https://example.com/wh",
        event_types=[EventType.PASSPORT_GENERATED],
        config=cfg,
    )
    assert sub.integration_kind == IntegrationKind.GENERIC
    assert sub.integration_config == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_webhooks_store.py -v -k integration`
Expected: TypeError — `create_subscription` does not accept `integration_kind`.

- [ ] **Step 3: Modify the store**

In `smadp/webhooks/store.py`:

Update imports:

```python
from smadp.schemas.webhooks import EventType, IntegrationKind, Subscription
```

In `_SCHEMA_SQL`, add the two new columns to the existing CREATE TABLE (so fresh DBs get them) AND add idempotent ALTERs after the CREATE/INDEX statements:

```python
_SCHEMA_SQL: Final[str] = """
CREATE TABLE IF NOT EXISTS subscriptions (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    url TEXT NOT NULL,
    event_types TEXT NOT NULL,
    active INTEGER NOT NULL,
    nonce BLOB NOT NULL,
    secret_encrypted BLOB NOT NULL,
    created_at TEXT NOT NULL,
    integration_kind TEXT NOT NULL DEFAULT 'generic',
    integration_config TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS subscriptions_workspace
    ON subscriptions(workspace_id, active);
"""


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_SQL)
    # Idempotent ALTERs for DBs created before integration columns existed.
    cols = {row[1] for row in conn.execute("PRAGMA table_info(subscriptions)")}
    if "integration_kind" not in cols:
        conn.execute(
            "ALTER TABLE subscriptions ADD COLUMN integration_kind TEXT NOT NULL DEFAULT 'generic'"
        )
    if "integration_config" not in cols:
        conn.execute(
            "ALTER TABLE subscriptions ADD COLUMN integration_config TEXT NOT NULL DEFAULT '{}'"
        )
```

Update `create_subscription` signature + body:

```python
def create_subscription(
    *,
    workspace_id: str,
    url: str,
    event_types: list[EventType],
    config: Config | None = None,
    integration_kind: IntegrationKind = IntegrationKind.GENERIC,
    integration_config: dict | None = None,
) -> tuple[Subscription, str]:
    cfg = config or load_config()
    sub_id = _generate_subscription_id()
    secret = _generate_secret()
    nonce, encrypted = _encrypt(secret.encode("utf-8"), workspace_id=workspace_id)
    now_iso = utcnow().isoformat(timespec="seconds").replace("+00:00", "Z")
    types_json = json.dumps([t.value for t in event_types], sort_keys=True)
    config_json = json.dumps(integration_config or {}, sort_keys=True)
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        with _transaction(conn):
            conn.execute(
                "INSERT INTO subscriptions"
                "(id, workspace_id, url, event_types, active, nonce,"
                " secret_encrypted, created_at, integration_kind, integration_config)"
                " VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?)",
                (
                    sub_id, workspace_id, url, types_json,
                    nonce, encrypted, now_iso,
                    integration_kind.value, config_json,
                ),
            )
        log.info(
            "webhooks.subscription.created",
            workspace_id=workspace_id,
            subscription_id=sub_id,
            url=url,
            integration_kind=integration_kind.value,
        )
        return (
            Subscription(
                id=sub_id,
                workspace_id=workspace_id,
                url=url,
                event_types=event_types,
                active=True,
                created_at=datetime.fromisoformat(now_iso.replace("Z", "+00:00")),
                integration_kind=integration_kind,
                integration_config=integration_config or {},
            ),
            secret,
        )
    finally:
        conn.close()
```

Update `_row_to_subscription`:

```python
def _row_to_subscription(row: sqlite3.Row) -> Subscription:
    return Subscription(
        id=row["id"],
        workspace_id=row["workspace_id"],
        url=row["url"],
        event_types=[EventType(v) for v in json.loads(row["event_types"])],
        active=bool(row["active"]),
        created_at=datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")),
        integration_kind=IntegrationKind(row["integration_kind"]),
        integration_config=json.loads(row["integration_config"]),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_webhooks_store.py -v`
Expected: all PASS (existing + new).

- [ ] **Step 5: Commit**

```bash
git add smadp/webhooks/store.py tests/unit/test_webhooks_store.py
git commit -m "feat(webhooks): add integration_kind/integration_config to subscriptions"
```

---

## Task 13: Webhooks API — accept integration fields

**Files:**
- Modify: `smadp/webhooks/api.py`
- Modify: `tests/integration/test_webhooks_api.py` (assumed to exist from Plan 3 — if it doesn't, create a small companion test file)

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_webhooks_api.py` (or create `tests/integration/test_webhooks_api_native.py` if Plan 3 didn't ship the API integration test):

```python
def test_create_subscription_with_native_integration(client, workspace_id):
    r = client.post(
        "/api/webhooks/subscriptions",
        json={
            "url": "https://hooks.slack.com/services/abc/def",
            "event_types": ["passport.generated"],
            "integration_kind": "slack",
            "integration_config": {"channel": "#smadp-alerts"},
        },
        headers={"X-SMADP-Workspace": workspace_id, "X-SMADP-User": "u"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["subscription"]["integration_kind"] == "slack"
    assert body["subscription"]["integration_config"] == {"channel": "#smadp-alerts"}


def test_create_subscription_default_integration_generic(client, workspace_id):
    r = client.post(
        "/api/webhooks/subscriptions",
        json={"url": "https://example.com/wh", "event_types": ["passport.generated"]},
        headers={"X-SMADP-Workspace": workspace_id, "X-SMADP-User": "u"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["subscription"]["integration_kind"] == "generic"
```

If `tests/integration/test_webhooks_api.py` does not exist, create the new file with appropriate fixtures (mirror `test_vendor_api_claims.py` for `cfg`/`workspace_id`/`client` fixtures).

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/integration/test_webhooks_api.py -v -k integration`
Expected: 422 — body has unknown fields (`integration_kind`).

- [ ] **Step 3: Modify the body model + handler**

In `smadp/webhooks/api.py`:

```python
from typing import Any
from smadp.schemas.webhooks import EventType, IntegrationKind, Subscription
from pydantic import BaseModel, ConfigDict, Field, field_validator


class _CreateSubscriptionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    event_types: list[EventType]
    integration_kind: IntegrationKind = IntegrationKind.GENERIC
    integration_config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("url")
    @classmethod
    def _url_scheme(cls, v: str) -> str:
        parsed = urlparse(v)
        if parsed.scheme == "https":
            return v
        if parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}:
            return v
        raise ValueError("Subscription URL must be https:// (or http://localhost for dev)")

    @field_validator("event_types")
    @classmethod
    def _nonempty(cls, v: list[EventType]) -> list[EventType]:
        if not v:
            raise ValueError("event_types must not be empty")
        return v
```

Update `create_subscription`:

```python
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
        integration_kind=body.integration_kind,
        integration_config=body.integration_config,
    )
    return _CreateSubscriptionResponse(subscription=sub, secret=secret)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/integration/test_webhooks_api.py -v`
Expected: all PASS (existing + new).

- [ ] **Step 5: Commit**

```bash
git add smadp/webhooks/api.py tests/integration/test_webhooks_api.py
git commit -m "feat(webhooks): accept integration_kind/integration_config in API"
```

---

## Task 14: Integrations base — Protocol + registry + GenericAdapter

**Files:**
- Create: `smadp/integrations/__init__.py`
- Create: `smadp/integrations/base.py`
- Create: `smadp/integrations/generic.py`
- Create: `tests/unit/test_integrations_registry.py`

- [ ] **Step 1: Write the failing test**

Create `smadp/integrations/__init__.py`:

```python
"""Native integration adapters: vanta, drata, slack."""
```

Create `tests/unit/test_integrations_registry.py`:

```python
"""Unit tests for integrations registry."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from smadp.integrations import base, get_adapter
from smadp.schemas.webhooks import EventType, IntegrationKind, WebhookEnvelope


def _envelope() -> WebhookEnvelope:
    return WebhookEnvelope(
        id="evt_20260503120000_abcdef",
        type=EventType.PASSPORT_GENERATED,
        created_at=datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC),
        workspace_id="ws_ABCD1234",
        data={"verdict_id": "vdt_X"},
        signature_meta={"transparency_log_id": 1},
    )


def test_registry_has_all_kinds():
    for kind in IntegrationKind:
        adapter = get_adapter(kind)
        assert adapter.kind == kind


def test_unknown_kind_raises():
    with pytest.raises(KeyError):
        # Forge a value not in IntegrationKind
        base.get_adapter("nonsense")  # type: ignore[arg-type]


def test_generic_adapter_returns_canonical_envelope_bytes():
    adapter = get_adapter(IntegrationKind.GENERIC)
    body = adapter.translate(_envelope(), config={})
    assert body.startswith(b"{")
    assert b'"id":"evt_20260503120000_abcdef"' in body
    assert adapter.headers(_envelope(), config={}) == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_integrations_registry.py -v`
Expected: ImportError on `smadp.integrations.base`.

- [ ] **Step 3: Implement base + generic**

Create `smadp/integrations/base.py`:

```python
"""Adapter Protocol + registry for native webhook integrations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from smadp.schemas.webhooks import IntegrationKind, WebhookEnvelope


class Adapter(Protocol):
    kind: IntegrationKind

    def translate(self, envelope: WebhookEnvelope, *, config: Mapping[str, object]) -> bytes:
        ...

    def headers(self, envelope: WebhookEnvelope, *, config: Mapping[str, object]) -> dict[str, str]:
        ...


_REGISTRY: dict[IntegrationKind, Adapter] = {}


def register_adapter(adapter: Adapter) -> None:
    if adapter.kind in _REGISTRY:
        raise ValueError(f"adapter for {adapter.kind!r} already registered")
    _REGISTRY[adapter.kind] = adapter


def get_adapter(kind: IntegrationKind) -> Adapter:
    if kind not in _REGISTRY:
        raise KeyError(f"no adapter registered for kind={kind!r}")
    return _REGISTRY[kind]


__all__ = ["Adapter", "get_adapter", "register_adapter"]
```

Create `smadp/integrations/generic.py`:

```python
"""Generic adapter — passes the canonical envelope bytes through unchanged."""

from __future__ import annotations

from collections.abc import Mapping

from smadp.integrations.base import register_adapter
from smadp.schemas.webhooks import IntegrationKind, WebhookEnvelope
from smadp.webhooks.envelope import canonical_envelope_bytes


class GenericAdapter:
    kind = IntegrationKind.GENERIC

    def translate(self, envelope: WebhookEnvelope, *, config: Mapping[str, object]) -> bytes:
        return canonical_envelope_bytes(envelope)

    def headers(self, envelope: WebhookEnvelope, *, config: Mapping[str, object]) -> dict[str, str]:
        return {}


register_adapter(GenericAdapter())


__all__ = ["GenericAdapter"]
```

Update `smadp/integrations/__init__.py` to wire registration on import:

```python
"""Native integration adapters: vanta, drata, slack."""

from smadp.integrations import generic  # noqa: F401  - registration side-effect
from smadp.integrations.base import Adapter, get_adapter, register_adapter

__all__ = ["Adapter", "get_adapter", "register_adapter"]
```

Note: At this stage Vanta/Drata/Slack are not yet registered — `test_registry_has_all_kinds` will fail for them. We will add the imports for those in Task 15-17 to extend the registration. **For now**, modify the test to filter out kinds that aren't registered yet:

Update the failing test temporarily to:

```python
def test_registry_has_all_kinds():
    # Tasks 15-17 register vanta/drata/slack; this test re-runs after each.
    registered = {IntegrationKind.GENERIC}
    for kind in registered:
        adapter = get_adapter(kind)
        assert adapter.kind == kind
```

We'll widen `registered` in Tasks 15, 16, 17 and finally drop the filter in Task 17.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_integrations_registry.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add smadp/integrations/__init__.py smadp/integrations/base.py smadp/integrations/generic.py tests/unit/test_integrations_registry.py
git commit -m "feat(integrations): add Adapter Protocol + registry + GenericAdapter"
```

---

## Task 15: Vanta translator

**Files:**
- Create: `smadp/integrations/vanta.py`
- Create: `tests/unit/test_integrations_vanta.py`
- Modify: `smadp/integrations/__init__.py`
- Modify: `tests/unit/test_integrations_registry.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_integrations_vanta.py`:

```python
"""Unit tests for VantaAdapter translator."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from smadp.integrations import get_adapter
from smadp.schemas.webhooks import EventType, IntegrationKind, WebhookEnvelope


def _envelope(event_type: EventType = EventType.PASSPORT_GENERATED) -> WebhookEnvelope:
    return WebhookEnvelope(
        id="evt_20260503120000_abcdef",
        type=event_type,
        created_at=datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC),
        workspace_id="ws_ABCD1234",
        data={
            "verdict_id": "vdt_X",
            "composite_score": 0.42,
            "passport_url": "https://smadp.example/passports/vdt_X.html",
        },
        signature_meta={"transparency_log_id": 7},
    )


def test_vanta_translator_payload_shape():
    adapter = get_adapter(IntegrationKind.VANTA)
    body = adapter.translate(_envelope(), config={"token": "tok", "evidence_request_id": "req_1"})
    obj = json.loads(body)
    assert obj["evidenceType"] == "smadp_passport"
    assert obj["evidenceId"] == "vdt_X"
    assert obj["passedAt"] == "2026-05-03T12:00:00Z"
    assert obj["evidenceRequestId"] == "req_1"
    assert obj["metadata"]["composite_score"] == 0.42


def test_vanta_translator_missing_token_raises():
    adapter = get_adapter(IntegrationKind.VANTA)
    with pytest.raises(ValueError, match="token"):
        adapter.translate(_envelope(), config={"evidence_request_id": "req_1"})


def test_vanta_translator_missing_request_id_raises():
    adapter = get_adapter(IntegrationKind.VANTA)
    with pytest.raises(ValueError, match="evidence_request_id"):
        adapter.translate(_envelope(), config={"token": "tok"})


def test_vanta_headers_authorization_bearer():
    adapter = get_adapter(IntegrationKind.VANTA)
    h = adapter.headers(_envelope(), config={"token": "abc123", "evidence_request_id": "req_1"})
    assert h == {"Authorization": "Bearer abc123", "Content-Type": "application/json"}


def test_vanta_translator_handles_missing_data_fields():
    adapter = get_adapter(IntegrationKind.VANTA)
    env = WebhookEnvelope(
        id="evt_20260503120000_abcdef",
        type=EventType.VERDICT_UPDATED,
        created_at=datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC),
        workspace_id="ws_ABCD1234",
        data={},  # nothing
        signature_meta={"transparency_log_id": 7},
    )
    body = adapter.translate(env, config={"token": "tok", "evidence_request_id": "req_1"})
    obj = json.loads(body)
    assert obj["evidenceId"] == "n/a"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_integrations_vanta.py -v`
Expected: KeyError on `IntegrationKind.VANTA` (not registered).

- [ ] **Step 3: Implement VantaAdapter**

Create `smadp/integrations/vanta.py`:

```python
"""Vanta evidence-update adapter."""

from __future__ import annotations

import json
from collections.abc import Mapping

from smadp.integrations.base import register_adapter
from smadp.schemas.webhooks import IntegrationKind, WebhookEnvelope


class VantaAdapter:
    kind = IntegrationKind.VANTA

    def _config(self, config: Mapping[str, object]) -> tuple[str, str]:
        token = config.get("token")
        request_id = config.get("evidence_request_id")
        if not isinstance(token, str) or not token:
            raise ValueError("vanta config missing 'token'")
        if not isinstance(request_id, str) or not request_id:
            raise ValueError("vanta config missing 'evidence_request_id'")
        return token, request_id

    def translate(self, envelope: WebhookEnvelope, *, config: Mapping[str, object]) -> bytes:
        _token, request_id = self._config(config)
        verdict_id = envelope.data.get("verdict_id", "n/a")
        passed_at = envelope.created_at.isoformat(timespec="seconds").replace("+00:00", "Z")
        payload = {
            "evidenceType": "smadp_passport",
            "evidenceRequestId": request_id,
            "evidenceId": verdict_id,
            "passedAt": passed_at,
            "metadata": dict(envelope.data),
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def headers(self, envelope: WebhookEnvelope, *, config: Mapping[str, object]) -> dict[str, str]:
        token, _ = self._config(config)
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


register_adapter(VantaAdapter())


__all__ = ["VantaAdapter"]
```

Update `smadp/integrations/__init__.py` to import vanta:

```python
from smadp.integrations import generic, vanta  # noqa: F401
```

Widen `tests/unit/test_integrations_registry.py::test_registry_has_all_kinds`:

```python
def test_registry_has_all_kinds():
    registered = {IntegrationKind.GENERIC, IntegrationKind.VANTA}
    for kind in registered:
        adapter = get_adapter(kind)
        assert adapter.kind == kind
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_integrations_vanta.py tests/unit/test_integrations_registry.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add smadp/integrations/vanta.py smadp/integrations/__init__.py tests/unit/test_integrations_vanta.py tests/unit/test_integrations_registry.py
git commit -m "feat(integrations): add VantaAdapter (evidence-update payload)"
```

---

## Task 16: Drata translator

**Files:**
- Create: `smadp/integrations/drata.py`
- Create: `tests/unit/test_integrations_drata.py`
- Modify: `smadp/integrations/__init__.py`
- Modify: `tests/unit/test_integrations_registry.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_integrations_drata.py`:

```python
"""Unit tests for DrataAdapter translator."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from smadp.integrations import get_adapter
from smadp.schemas.webhooks import EventType, IntegrationKind, WebhookEnvelope


def _envelope() -> WebhookEnvelope:
    return WebhookEnvelope(
        id="evt_20260503120000_abcdef",
        type=EventType.PASSPORT_GENERATED,
        created_at=datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC),
        workspace_id="ws_ABCD1234",
        data={
            "verdict_id": "vdt_X",
            "composite_score": 0.42,
            "passport_url": "https://smadp.example/passports/vdt_X.html",
        },
        signature_meta={"transparency_log_id": 7},
    )


def test_drata_payload_shape():
    adapter = get_adapter(IntegrationKind.DRATA)
    body = adapter.translate(_envelope(), config={"token": "tok", "control_id": "ctrl_42"})
    obj = json.loads(body)
    assert obj["controlId"] == "ctrl_42"
    assert obj["occurredAt"] == "2026-05-03T12:00:00Z"
    assert obj["evidence"]["verdict_id"] == "vdt_X"
    assert obj["evidence"]["score"] == 0.42
    assert obj["evidence"]["passport_url"] == "https://smadp.example/passports/vdt_X.html"


def test_drata_missing_token_raises():
    adapter = get_adapter(IntegrationKind.DRATA)
    with pytest.raises(ValueError, match="token"):
        adapter.translate(_envelope(), config={"control_id": "ctrl_42"})


def test_drata_missing_control_id_raises():
    adapter = get_adapter(IntegrationKind.DRATA)
    with pytest.raises(ValueError, match="control_id"):
        adapter.translate(_envelope(), config={"token": "tok"})


def test_drata_headers():
    adapter = get_adapter(IntegrationKind.DRATA)
    h = adapter.headers(_envelope(), config={"token": "abc", "control_id": "ctrl_42"})
    assert h == {
        "Authorization": "Bearer abc",
        "X-Drata-Source": "smadp",
        "Content-Type": "application/json",
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_integrations_drata.py -v`
Expected: KeyError on DRATA.

- [ ] **Step 3: Implement DrataAdapter**

Create `smadp/integrations/drata.py`:

```python
"""Drata evidence-update adapter."""

from __future__ import annotations

import json
from collections.abc import Mapping

from smadp.integrations.base import register_adapter
from smadp.schemas.webhooks import IntegrationKind, WebhookEnvelope


class DrataAdapter:
    kind = IntegrationKind.DRATA

    def _config(self, config: Mapping[str, object]) -> tuple[str, str]:
        token = config.get("token")
        control_id = config.get("control_id")
        if not isinstance(token, str) or not token:
            raise ValueError("drata config missing 'token'")
        if not isinstance(control_id, str) or not control_id:
            raise ValueError("drata config missing 'control_id'")
        return token, control_id

    def translate(self, envelope: WebhookEnvelope, *, config: Mapping[str, object]) -> bytes:
        _token, control_id = self._config(config)
        occurred = envelope.created_at.isoformat(timespec="seconds").replace("+00:00", "Z")
        evidence = {
            "verdict_id": envelope.data.get("verdict_id", "n/a"),
            "score": envelope.data.get("composite_score"),
            "passport_url": envelope.data.get("passport_url"),
            "event_type": envelope.type.value,
        }
        payload = {
            "controlId": control_id,
            "occurredAt": occurred,
            "evidence": evidence,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def headers(self, envelope: WebhookEnvelope, *, config: Mapping[str, object]) -> dict[str, str]:
        token, _ = self._config(config)
        return {
            "Authorization": f"Bearer {token}",
            "X-Drata-Source": "smadp",
            "Content-Type": "application/json",
        }


register_adapter(DrataAdapter())


__all__ = ["DrataAdapter"]
```

Update `smadp/integrations/__init__.py`:

```python
from smadp.integrations import drata, generic, vanta  # noqa: F401
```

Widen `tests/unit/test_integrations_registry.py::test_registry_has_all_kinds`:

```python
def test_registry_has_all_kinds():
    registered = {IntegrationKind.GENERIC, IntegrationKind.VANTA, IntegrationKind.DRATA}
    for kind in registered:
        adapter = get_adapter(kind)
        assert adapter.kind == kind
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_integrations_drata.py tests/unit/test_integrations_registry.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add smadp/integrations/drata.py smadp/integrations/__init__.py tests/unit/test_integrations_drata.py tests/unit/test_integrations_registry.py
git commit -m "feat(integrations): add DrataAdapter (control evidence)"
```

---

## Task 17: Slack translator

**Files:**
- Create: `smadp/integrations/slack.py`
- Create: `tests/unit/test_integrations_slack.py`
- Modify: `smadp/integrations/__init__.py`
- Modify: `tests/unit/test_integrations_registry.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_integrations_slack.py`:

```python
"""Unit tests for SlackAdapter translator."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from smadp.integrations import get_adapter
from smadp.schemas.webhooks import EventType, IntegrationKind, WebhookEnvelope


def _passport_envelope() -> WebhookEnvelope:
    return WebhookEnvelope(
        id="evt_20260503120000_abcdef",
        type=EventType.PASSPORT_GENERATED,
        created_at=datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC),
        workspace_id="ws_ABCD1234",
        data={
            "verdict_id": "vdt_X",
            "composite_score": 0.42,
            "passport_url": "https://smadp.example/passports/vdt_X.html",
            "agent_pair": ["a/x", "b/y"],
        },
        signature_meta={"transparency_log_id": 7},
    )


def test_slack_passport_message_shape():
    adapter = get_adapter(IntegrationKind.SLACK)
    body = adapter.translate(_passport_envelope(), config={})
    obj = json.loads(body)
    assert "text" in obj
    assert "Passport generated" in obj["text"]
    assert isinstance(obj["blocks"], list)
    assert any("vdt_X" in json.dumps(b) for b in obj["blocks"])


def test_slack_verdict_message_shape():
    env = WebhookEnvelope(
        id="evt_20260503120000_abcdef",
        type=EventType.VERDICT_UPDATED,
        created_at=datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC),
        workspace_id="ws_ABCD1234",
        data={"verdict_id": "vdt_Y", "agent_pair": ["a/x", "b/y"], "composite_score": 0.7},
        signature_meta={"transparency_log_id": 1},
    )
    adapter = get_adapter(IntegrationKind.SLACK)
    obj = json.loads(adapter.translate(env, config={}))
    assert "Verdict updated" in obj["text"]
    assert any("a/x" in json.dumps(b) for b in obj["blocks"])


def test_slack_no_passport_url_omits_button():
    env = WebhookEnvelope(
        id="evt_20260503120000_abcdef",
        type=EventType.PASSPORT_GENERATED,
        created_at=datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC),
        workspace_id="ws_ABCD1234",
        data={"verdict_id": "vdt_X"},
        signature_meta={"transparency_log_id": 7},
    )
    adapter = get_adapter(IntegrationKind.SLACK)
    obj = json.loads(adapter.translate(env, config={}))
    flat = json.dumps(obj)
    assert "actions" not in flat or "button" not in flat


def test_slack_headers_minimal():
    adapter = get_adapter(IntegrationKind.SLACK)
    h = adapter.headers(_passport_envelope(), config={})
    assert h == {"Content-Type": "application/json"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_integrations_slack.py -v`
Expected: KeyError on SLACK.

- [ ] **Step 3: Implement SlackAdapter**

Create `smadp/integrations/slack.py`:

```python
"""Slack incoming-webhook adapter (Block Kit)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from smadp.integrations.base import register_adapter
from smadp.schemas.webhooks import EventType, IntegrationKind, WebhookEnvelope


class SlackAdapter:
    kind = IntegrationKind.SLACK

    def _build_text(self, envelope: WebhookEnvelope) -> str:
        verdict_id = envelope.data.get("verdict_id", "n/a")
        if envelope.type == EventType.PASSPORT_GENERATED:
            return f"Passport generated for {verdict_id}"
        if envelope.type in {EventType.VERDICT_CREATED, EventType.VERDICT_UPDATED}:
            pair = envelope.data.get("agent_pair") or ["?", "?"]
            return f"Verdict updated: {pair[0]} ↔ {pair[1]}"
        return f"{envelope.type.value} ({verdict_id})"

    def translate(self, envelope: WebhookEnvelope, *, config: Mapping[str, object]) -> bytes:
        text = self._build_text(envelope)
        verdict_id = envelope.data.get("verdict_id", "n/a")
        score = envelope.data.get("composite_score")
        pair = envelope.data.get("agent_pair") or ["n/a", "n/a"]
        passport_url = envelope.data.get("passport_url")

        blocks: list[dict[str, Any]] = [
            {"type": "header", "text": {"type": "plain_text", "text": text}},
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Verdict ID:* `{verdict_id}`"},
                    {"type": "mrkdwn", "text": f"*Pair:* `{pair[0]}` ↔ `{pair[1]}`"},
                    {
                        "type": "mrkdwn",
                        "text": f"*Score:* {score if score is not None else 'n/a'}",
                    },
                    {"type": "mrkdwn", "text": f"*Event:* `{envelope.type.value}`"},
                ],
            },
        ]
        if isinstance(passport_url, str) and passport_url:
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Open passport"},
                            "url": passport_url,
                        }
                    ],
                }
            )
        payload = {"text": text, "blocks": blocks}
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def headers(self, envelope: WebhookEnvelope, *, config: Mapping[str, object]) -> dict[str, str]:
        return {"Content-Type": "application/json"}


register_adapter(SlackAdapter())


__all__ = ["SlackAdapter"]
```

Update `smadp/integrations/__init__.py`:

```python
from smadp.integrations import drata, generic, slack, vanta  # noqa: F401
```

Update `tests/unit/test_integrations_registry.py::test_registry_has_all_kinds` (drop the filter — all 4 kinds are now registered):

```python
def test_registry_has_all_kinds():
    for kind in IntegrationKind:
        adapter = get_adapter(kind)
        assert adapter.kind == kind
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_integrations_slack.py tests/unit/test_integrations_registry.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add smadp/integrations/slack.py smadp/integrations/__init__.py tests/unit/test_integrations_slack.py tests/unit/test_integrations_registry.py
git commit -m "feat(integrations): add SlackAdapter (Block Kit message)"
```

---

## Task 18: Dispatcher uses adapter; deliveries carries headers_overlay

**Files:**
- Modify: `smadp/webhooks/dispatcher.py`
- Modify: `smadp/webhooks/deliveries.py`
- Create: `tests/unit/test_webhooks_dispatcher_native.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_webhooks_dispatcher_native.py`:

```python
"""Unit tests for dispatcher routing native subscriptions through adapters."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from smadp.config import Config
from smadp.schemas.tenancy import Plan
from smadp.schemas.webhooks import EventType, IntegrationKind
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


def test_dispatch_uses_slack_adapter_for_slack_sub(cfg: Config, workspace_id: str):
    sub, _ = store.create_subscription(
        workspace_id=workspace_id,
        url="https://hooks.slack.com/services/abc/def",
        event_types=[EventType.PASSPORT_GENERATED],
        config=cfg,
        integration_kind=IntegrationKind.SLACK,
        integration_config={},
    )
    dispatcher.dispatch_event(
        event_type=EventType.PASSPORT_GENERATED,
        payload={"verdict_id": "vdt_X", "passport_url": "https://smadp.example/p/vdt_X"},
        workspace_id=workspace_id,
        signature_meta={"transparency_log_id": 1},
        config=cfg,
    )
    rows = list(deliveries.iter_all(config=cfg))
    assert len(rows) == 1
    body = rows[0].body.decode("utf-8")
    obj = json.loads(body)
    assert "Passport generated" in obj["text"]


def test_dispatch_generic_sub_uses_canonical_envelope(cfg: Config, workspace_id: str):
    sub, _ = store.create_subscription(
        workspace_id=workspace_id,
        url="https://example.com/wh",
        event_types=[EventType.PASSPORT_GENERATED],
        config=cfg,
    )
    dispatcher.dispatch_event(
        event_type=EventType.PASSPORT_GENERATED,
        payload={"verdict_id": "vdt_X"},
        workspace_id=workspace_id,
        signature_meta={"transparency_log_id": 1},
        config=cfg,
    )
    rows = list(deliveries.iter_all(config=cfg))
    body = rows[0].body
    assert b'"id":"evt_' in body
    assert b'"workspace_id":"' + workspace_id.encode() + b'"' in body


def test_dispatch_native_sub_persists_headers_overlay(cfg: Config, workspace_id: str):
    sub, _ = store.create_subscription(
        workspace_id=workspace_id,
        url="https://api.drata.com/wh",
        event_types=[EventType.PASSPORT_GENERATED],
        config=cfg,
        integration_kind=IntegrationKind.DRATA,
        integration_config={"token": "tok", "control_id": "ctrl_42"},
    )
    dispatcher.dispatch_event(
        event_type=EventType.PASSPORT_GENERATED,
        payload={"verdict_id": "vdt_X", "composite_score": 0.5},
        workspace_id=workspace_id,
        signature_meta={"transparency_log_id": 1},
        config=cfg,
    )
    rows = list(deliveries.iter_all(config=cfg))
    assert rows[0].headers_overlay == {
        "Authorization": "Bearer tok",
        "X-Drata-Source": "smadp",
        "Content-Type": "application/json",
    }


def test_dispatch_two_subs_translate_independently(cfg: Config, workspace_id: str):
    store.create_subscription(
        workspace_id=workspace_id,
        url="https://example.com/generic",
        event_types=[EventType.PASSPORT_GENERATED],
        config=cfg,
    )
    store.create_subscription(
        workspace_id=workspace_id,
        url="https://hooks.slack.com/services/abc/def",
        event_types=[EventType.PASSPORT_GENERATED],
        config=cfg,
        integration_kind=IntegrationKind.SLACK,
        integration_config={},
    )
    dispatcher.dispatch_event(
        event_type=EventType.PASSPORT_GENERATED,
        payload={"verdict_id": "vdt_X"},
        workspace_id=workspace_id,
        signature_meta={"transparency_log_id": 1},
        config=cfg,
    )
    rows = list(deliveries.iter_all(config=cfg))
    assert len(rows) == 2
    bodies = {r.body for r in rows}
    assert any(b'"text":"Passport generated for vdt_X"' in b for b in bodies)
    assert any(b'"workspace_id":"' + workspace_id.encode() + b'"' in b for b in bodies)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_webhooks_dispatcher_native.py -v`
Expected: AttributeError on `WebhookDelivery.headers_overlay` (or test_dispatch_uses_slack_adapter fails because all bodies are still envelope JSON).

- [ ] **Step 3: Add `headers_overlay` to deliveries**

In `smadp/webhooks/deliveries.py`:

Add to imports near the top:

```python
import json
```

(Skip if already imported.)

Update `_SCHEMA_SQL` to include the new column on fresh DBs:

```python
_SCHEMA_SQL: Final[str] = """
CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id TEXT PRIMARY KEY,
    subscription_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    body BLOB NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL,
    next_attempt_at TEXT NOT NULL,
    last_error TEXT,
    created_at TEXT NOT NULL,
    delivered_at TEXT,
    headers_overlay TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS webhook_deliveries_pending
    ON webhook_deliveries(status, next_attempt_at);
"""
```

Update `_ensure_schema`:

```python
def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_SQL)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(webhook_deliveries)")}
    if "headers_overlay" not in cols:
        conn.execute(
            "ALTER TABLE webhook_deliveries ADD COLUMN headers_overlay TEXT NOT NULL DEFAULT '{}'"
        )
```

Modify `enqueue` signature + body to accept headers_overlay (default `{}`):

```python
def enqueue(
    *,
    subscription_id: str,
    event_id: str,
    event_type: EventType,
    body: bytes,
    headers_overlay: dict[str, str] | None = None,
    config: Config | None = None,
) -> WebhookDelivery:
    cfg = config or load_config()
    now = utcnow()
    delivery_id = _generate_delivery_id(now)
    now_iso = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    overlay_json = json.dumps(headers_overlay or {}, sort_keys=True)
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        with _transaction(conn):
            conn.execute(
                "INSERT INTO webhook_deliveries"
                "(id, subscription_id, event_id, event_type, body, status,"
                " attempts, next_attempt_at, last_error, created_at, delivered_at,"
                " headers_overlay)"
                " VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, NULL, ?, NULL, ?)",
                (
                    delivery_id, subscription_id, event_id, event_type.value,
                    body, now_iso, now_iso, overlay_json,
                ),
            )
        return get_delivery(delivery_id=delivery_id, config=cfg)
    finally:
        conn.close()
```

(If your existing `enqueue` body differs in column ordering or helper calls, mirror what's there — only the headers_overlay parameter and the JSON serialisation are new.)

Modify `WebhookDelivery` Pydantic model in `smadp/schemas/webhooks.py` to add the new field:

```python
class WebhookDelivery(BaseModel):
    # ... existing fields ...
    headers_overlay: dict[str, str] = Field(default_factory=dict)
```

Modify `_row_to_delivery` (in `deliveries.py`) to read the column:

```python
def _row_to_delivery(row: sqlite3.Row) -> WebhookDelivery:
    return WebhookDelivery(
        id=row["id"],
        subscription_id=row["subscription_id"],
        event_id=row["event_id"],
        event_type=EventType(row["event_type"]),
        body=bytes(row["body"]),
        status=DeliveryStatus(row["status"]),
        attempts=row["attempts"],
        next_attempt_at=datetime.fromisoformat(row["next_attempt_at"].replace("Z", "+00:00")),
        last_error=row["last_error"],
        created_at=datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")),
        delivered_at=(
            datetime.fromisoformat(row["delivered_at"].replace("Z", "+00:00"))
            if row["delivered_at"] else None
        ),
        headers_overlay=json.loads(row["headers_overlay"]),
    )
```

- [ ] **Step 4: Modify the dispatcher to call adapters**

In `smadp/webhooks/dispatcher.py`:

```python
from smadp.integrations import get_adapter
from smadp.schemas.webhooks import EventType, IntegrationKind
```

Replace the `body = canonical_envelope_bytes(envelope)` + enqueue loop with per-sub adapter dispatch:

```python
    enqueued = 0
    for sub in matches:
        if sub.integration_kind == IntegrationKind.GENERIC:
            body = canonical_envelope_bytes(envelope)
            headers_overlay: dict[str, str] = {}
        else:
            adapter = get_adapter(sub.integration_kind)
            try:
                body = adapter.translate(envelope, config=sub.integration_config)
                headers_overlay = adapter.headers(envelope, config=sub.integration_config)
            except ValueError as exc:
                # Misconfigured native sub: log and skip — do not poison the queue.
                log.warning(
                    "webhooks.dispatch.adapter_misconfig",
                    subscription_id=sub.id,
                    integration_kind=sub.integration_kind.value,
                    error=str(exc),
                )
                continue
        deliveries.enqueue(
            subscription_id=sub.id,
            event_id=event_id,
            event_type=event_type,
            body=body,
            headers_overlay=headers_overlay,
            config=cfg,
        )
        enqueued += 1
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_webhooks_dispatcher_native.py tests/unit/test_webhooks_dispatcher.py tests/unit/test_webhooks_deliveries.py -v`
Expected: all PASS (existing dispatcher/deliveries unit tests still pass — `headers_overlay` defaults to `{}`).

- [ ] **Step 6: Commit**

```bash
git add smadp/webhooks/dispatcher.py smadp/webhooks/deliveries.py smadp/schemas/webhooks.py tests/unit/test_webhooks_dispatcher_native.py
git commit -m "feat(webhooks): dispatcher routes through native adapters; deliveries carry headers_overlay"
```

---

## Task 19: Worker merges headers_overlay (reserved keys win)

**Files:**
- Modify: `smadp/webhooks/worker.py`
- Create: `tests/unit/test_webhooks_worker_headers.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_webhooks_worker_headers.py`:

```python
"""Worker merges integration headers; reserved SMADP headers win conflicts."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from smadp.config import Config
from smadp.schemas.tenancy import Plan
from smadp.schemas.webhooks import DeliveryStatus, EventType, IntegrationKind
from smadp.tenancy import keys
from smadp.tenancy import store as tenancy
from smadp.webhooks import deliveries, dispatcher, store, worker


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    base = datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(deliveries, "_now", lambda: base)
    monkeypatch.setattr(worker, "_now", lambda: base)
    return Config()


@pytest.fixture
def workspace_id(cfg: Config) -> str:
    ws = tenancy.create_workspace(name="W", plan=Plan.PUBLIC, config=cfg)
    keys.upload_signing_key(
        workspace_id=ws.id, private_key=Ed25519PrivateKey.generate(), config=cfg
    )
    return ws.id


@respx.mock
def test_worker_merges_overlay_headers(cfg: Config, workspace_id: str):
    store.create_subscription(
        workspace_id=workspace_id,
        url="https://api.drata.com/wh",
        event_types=[EventType.PASSPORT_GENERATED],
        config=cfg,
        integration_kind=IntegrationKind.DRATA,
        integration_config={"token": "tok", "control_id": "ctrl_42"},
    )
    dispatcher.dispatch_event(
        event_type=EventType.PASSPORT_GENERATED,
        payload={"verdict_id": "vdt_X"},
        workspace_id=workspace_id,
        signature_meta={"transparency_log_id": 1},
        config=cfg,
    )
    captured: dict[str, str] = {}

    def _capture(req: httpx.Request) -> httpx.Response:
        for k, v in req.headers.items():
            captured[k.lower()] = v
        return httpx.Response(200)

    respx.post("https://api.drata.com/wh").mock(side_effect=_capture)
    assert worker.process_one_pending(config=cfg) is True

    assert captured.get("authorization") == "Bearer tok"
    assert captured.get("x-drata-source") == "smadp"
    # Reserved headers still present:
    assert captured.get("x-smadp-signature", "").startswith("sha256=")
    assert captured.get("x-smadp-event-type") == "passport.generated"

    rows = list(deliveries.iter_all(config=cfg))
    assert rows[0].status == DeliveryStatus.DELIVERED


@respx.mock
def test_worker_overlay_cannot_override_reserved(cfg: Config, workspace_id: str):
    store.create_subscription(
        workspace_id=workspace_id,
        url="https://api.drata.com/wh",
        event_types=[EventType.PASSPORT_GENERATED],
        config=cfg,
        integration_kind=IntegrationKind.GENERIC,
    )
    # Force a delivery row with a malicious overlay (bypass dispatcher):
    deliveries.enqueue(
        subscription_id=store.list_subscriptions(workspace_id=workspace_id, config=cfg)[0].id,
        event_id="evt_20260503120000_abcdef",
        event_type=EventType.PASSPORT_GENERATED,
        body=b"{}",
        headers_overlay={
            "X-SMADP-Signature": "sha256=DEADBEEF",
            "X-SMADP-Event-Type": "spoofed.event",
            "X-Custom": "ok",
        },
        config=cfg,
    )

    captured: dict[str, str] = {}

    def _capture(req: httpx.Request) -> httpx.Response:
        for k, v in req.headers.items():
            captured[k.lower()] = v
        return httpx.Response(200)

    respx.post("https://api.drata.com/wh").mock(side_effect=_capture)
    assert worker.process_one_pending(config=cfg) is True

    # Reserved headers come from worker, NOT overlay:
    assert captured["x-smadp-event-type"] == "passport.generated"
    assert not captured["x-smadp-signature"].endswith("DEADBEEF")
    # Custom header still passes through:
    assert captured.get("x-custom") == "ok"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_webhooks_worker_headers.py -v`
Expected: FAIL — overlay headers are not merged into the request.

- [ ] **Step 3: Modify the worker**

In `smadp/webhooks/worker.py`, find the `process_one_pending` body (or whichever helper builds the POST headers) and update it to merge `delivery.headers_overlay` BEFORE the reserved headers are set:

```python
_RESERVED_HEADERS: Final[frozenset[str]] = frozenset(
    {"x-smadp-signature", "x-smadp-event-type", "x-smadp-delivery-id", "content-type"}
)


def _build_headers(*, delivery: WebhookDelivery, signature: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for k, v in (delivery.headers_overlay or {}).items():
        if k.lower() in _RESERVED_HEADERS:
            log.info(
                "webhooks.worker.header_conflict_dropped",
                delivery_id=delivery.id,
                header=k,
            )
            continue
        headers[k] = v
    headers["Content-Type"] = "application/json"
    headers["X-SMADP-Signature"] = signature
    headers["X-SMADP-Event-Type"] = delivery.event_type.value
    headers["X-SMADP-Delivery-Id"] = delivery.id
    return headers
```

Then where the worker currently builds headers inline before `httpx.Client.post(...)`, replace with `headers = _build_headers(delivery=delivery, signature=sig)`.

(If your existing worker code already extracts a `_build_headers`, modify that function instead.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_webhooks_worker_headers.py tests/unit/test_webhooks_worker.py -v`
Expected: all PASS (Plan 3 worker tests still pass; new ones pass).

- [ ] **Step 5: Commit**

```bash
git add smadp/webhooks/worker.py tests/unit/test_webhooks_worker_headers.py
git commit -m "feat(webhooks): worker merges headers_overlay; reserved SMADP headers win"
```

---

## Task 20: Vendor full lifecycle integration test

**Files:**
- Create: `tests/integration/test_vendor_full_lifecycle.py`

- [ ] **Step 1: Write the test**

Create `tests/integration/test_vendor_full_lifecycle.py`:

```python
"""End-to-end vendor lifecycle: claim → verify → response → dispute → resolve."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from smadp.api.app import build_app
from smadp.config import Config
from smadp.schemas.tenancy import Plan, Role
from smadp.tenancy import store as tenancy


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    monkeypatch.setenv("SMADP_PUBLIC_BASE_URL", "https://smadp.example")
    return Config()


@pytest.fixture
def workspace_id(cfg: Config) -> str:
    ws = tenancy.create_workspace(name="L", plan=Plan.PUBLIC, config=cfg)
    tenancy.add_member(workspace_id=ws.id, user_id="vendor_u", role=Role.EDITOR, config=cfg)
    tenancy.add_member(workspace_id=ws.id, user_id="op_admin", role=Role.ADMIN, config=cfg)
    return ws.id


@pytest.fixture
def client(cfg: Config) -> TestClient:
    return TestClient(build_app())


def _vendor(ws):
    return {"X-SMADP-Workspace": ws, "X-SMADP-User": "vendor_u"}


def _admin(ws):
    return {"X-SMADP-Workspace": ws, "X-SMADP-User": "op_admin"}


@respx.mock
def test_full_lifecycle_repo_claim_to_resolved_dispute(client: TestClient, workspace_id: str):
    # 1. Create claim (repo)
    create = client.post(
        "/api/vendor/claims",
        json={
            "agent_id": "claude-code",
            "method": "repo",
            "evidence_url": "https://github.com/o/r/raw/main",
        },
        headers=_vendor(workspace_id),
    )
    assert create.status_code == 201
    cid = create.json()["claim"]["id"]
    token = create.json()["token"]

    # 2. Verify (mock the repo)
    respx.get("https://github.com/o/r/raw/main/.smadp/owner.txt").mock(
        return_value=httpx.Response(200, text=token)
    )
    verify = client.post(
        f"/api/vendor/claims/{cid}/verify",
        json={"method": "repo", "evidence": {"repo_url": "https://github.com/o/r/raw/main"}},
        headers=_vendor(workspace_id),
    )
    assert verify.status_code == 200
    assert verify.json()["claim"]["status"] == "verified"

    # 3. Post a response on a verdict
    resp = client.post(
        "/api/vendor/responses",
        json={
            "verdict_id": "vdt_LIFECYCLE",
            "agent_id": "claude-code",
            "body_md": "we have mitigated the issue in v1.2",
        },
        headers=_vendor(workspace_id),
    )
    assert resp.status_code == 201
    rid = resp.json()["id"]

    # 4. List responses
    listed = client.get(
        "/api/vendor/responses",
        params={"verdict_id": "vdt_LIFECYCLE"},
        headers=_vendor(workspace_id),
    )
    assert listed.status_code == 200
    assert any(r["id"] == rid for r in listed.json())

    # 5. File a dispute
    f = client.post(
        "/api/vendor/disputes",
        json={
            "verdict_id": "vdt_LIFECYCLE",
            "agent_id": "claude-code",
            "argument_md": "score should be 0.7 not 0.4 because we shipped patches",
            "requested_outcome": "reeval",
        },
        headers=_vendor(workspace_id),
    )
    assert f.status_code == 201
    did = f.json()["id"]
    assert f.json()["status"] == "triage"

    # 6. Operator triages as substantive
    triage = client.patch(
        f"/api/vendor/disputes/{did}",
        json={"decision": "substantive"},
        headers=_admin(workspace_id),
    )
    assert triage.status_code == 200
    assert triage.json()["status"] == "pending_review"
    assert triage.json()["sla_breached_at"] is not None

    # 7. Operator resolves with stands + rationale
    res = client.patch(
        f"/api/vendor/disputes/{did}",
        json={"decision": "stands", "rationale_md": "additional review confirms verdict"},
        headers=_admin(workspace_id),
    )
    assert res.status_code == 200
    assert res.json()["status"] == "resolved_stands"
    assert res.json()["decision_rationale_md"] == "additional review confirms verdict"

    # 8. Cross-workspace isolation: a different workspace cannot see this dispute
    from smadp.tenancy import store as tenancy_store
    from smadp.config import load_config

    cfg = load_config()
    other = tenancy_store.create_workspace(name="O", plan=Plan.PUBLIC, config=cfg)
    tenancy_store.add_member(workspace_id=other.id, user_id="other_u", role=Role.ADMIN, config=cfg)
    other_list = client.get(
        "/api/vendor/disputes",
        headers={"X-SMADP-Workspace": other.id, "X-SMADP-User": "other_u"},
    )
    assert other_list.status_code == 200
    assert all(d["id"] != did for d in other_list.json())
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/integration/test_vendor_full_lifecycle.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_vendor_full_lifecycle.py
git commit -m "test(vendor): full lifecycle integration (claim→verify→response→dispute→resolve)"
```

---

## Task 21: Webhook native integration lifecycle test

**Files:**
- Create: `tests/integration/test_webhook_native_lifecycle.py`

- [ ] **Step 1: Write the test**

Create `tests/integration/test_webhook_native_lifecycle.py`:

```python
"""End-to-end native integration: render passport → worker delivers translated body."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from smadp.config import Config
from smadp.passport.render import render_passport
from smadp.schemas.passport import SigningStrategy
from smadp.schemas.tenancy import Plan
from smadp.schemas.webhooks import DeliveryStatus, EventType, IntegrationKind
from smadp.tenancy import keys
from smadp.tenancy import store as tenancy
from smadp.webhooks import deliveries, store, worker


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return Config()


@respx.mock
def test_slack_subscription_receives_translated_block_kit(cfg: Config):
    ws = tenancy.create_workspace(name="L", plan=Plan.PUBLIC, config=cfg)
    keys.upload_signing_key(
        workspace_id=ws.id, private_key=Ed25519PrivateKey.generate(), config=cfg
    )
    store.create_subscription(
        workspace_id=ws.id,
        url="https://hooks.slack.com/services/abc/def",
        event_types=[EventType.PASSPORT_GENERATED],
        config=cfg,
        integration_kind=IntegrationKind.SLACK,
        integration_config={},
    )

    captured: dict[str, object] = {}

    def _capture(req: httpx.Request) -> httpx.Response:
        captured["body"] = req.content.decode("utf-8")
        captured["sig"] = req.headers.get("X-SMADP-Signature")
        captured["event_type"] = req.headers.get("X-SMADP-Event-Type")
        captured["content_type"] = req.headers.get("Content-Type")
        return httpx.Response(200)

    respx.post("https://hooks.slack.com/services/abc/def").mock(side_effect=_capture)

    render_passport(
        verdict={
            "verdict_id": "vdt_NATIVE",
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

    # Pre-worker: delivery row pending and body is already Slack-shaped.
    rows = list(deliveries.iter_all(config=cfg))
    assert len(rows) == 1
    assert rows[0].status == DeliveryStatus.PENDING
    pre_obj = json.loads(rows[0].body)
    assert "Passport generated" in pre_obj["text"]

    assert worker.process_one_pending(config=cfg) is True
    rows_after = list(deliveries.iter_all(config=cfg))
    assert rows_after[0].status == DeliveryStatus.DELIVERED

    # Post-worker: Slack got the Block Kit body, signature header is present.
    assert captured["event_type"] == "passport.generated"
    assert captured["content_type"] == "application/json"
    assert captured["sig"].startswith("sha256=")
    obj = json.loads(captured["body"])
    assert "Passport generated for vdt_NATIVE" in obj["text"]
    assert isinstance(obj["blocks"], list)
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/integration/test_webhook_native_lifecycle.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_webhook_native_lifecycle.py
git commit -m "test(integrations): full native-integration delivery lifecycle (slack)"
```

---

## Task 22: Golden translated payloads + CI smoke + final sweep

**Files:**
- Create: `tests/golden/test_integration_payloads_golden.py`
- Modify: `.github/workflows/ci.yml`
- Final sweep: ruff + spec cross-check

### Part A — Golden payloads

- [ ] **Step 1: Write the golden test**

Create `tests/golden/test_integration_payloads_golden.py`:

```python
"""Golden tests: byte-stable Vanta/Drata/Slack translated payloads."""

from __future__ import annotations

from datetime import UTC, datetime

from smadp.integrations import get_adapter
from smadp.schemas.webhooks import EventType, IntegrationKind, WebhookEnvelope


_FIXED_ENVELOPE = WebhookEnvelope(
    id="evt_20260503120000_abcdef",
    type=EventType.PASSPORT_GENERATED,
    created_at=datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC),
    workspace_id="ws_GOLDEN12",
    data={
        "verdict_id": "vdt_GOLDEN",
        "agent_pair": ["anthropic/claude", "openai/gpt"],
        "composite_score": 0.42,
        "passport_url": "https://smadp.example/passports/vdt_GOLDEN.html",
    },
    signature_meta={"transparency_log_id": 7},
)


_VANTA_EXPECTED = (
    b'{"evidenceId":"vdt_GOLDEN",'
    b'"evidenceRequestId":"req_GOLDEN",'
    b'"evidenceType":"smadp_passport",'
    b'"metadata":{"agent_pair":["anthropic/claude","openai/gpt"],'
    b'"composite_score":0.42,'
    b'"passport_url":"https://smadp.example/passports/vdt_GOLDEN.html",'
    b'"verdict_id":"vdt_GOLDEN"},'
    b'"passedAt":"2026-05-03T12:00:00Z"}'
)


_DRATA_EXPECTED = (
    b'{"controlId":"ctrl_GOLDEN",'
    b'"evidence":{"event_type":"passport.generated",'
    b'"passport_url":"https://smadp.example/passports/vdt_GOLDEN.html",'
    b'"score":0.42,'
    b'"verdict_id":"vdt_GOLDEN"},'
    b'"occurredAt":"2026-05-03T12:00:00Z"}'
)


_SLACK_EXPECTED = (
    b'{"blocks":[{"text":{"text":"Passport generated for vdt_GOLDEN",'
    b'"type":"plain_text"},"type":"header"},'
    b'{"fields":[{"text":"*Verdict ID:* `vdt_GOLDEN`","type":"mrkdwn"},'
    b'{"text":"*Pair:* `anthropic/claude` \xe2\x86\x94 `openai/gpt`","type":"mrkdwn"},'
    b'{"text":"*Score:* 0.42","type":"mrkdwn"},'
    b'{"text":"*Event:* `passport.generated`","type":"mrkdwn"}],"type":"section"},'
    b'{"elements":[{"text":{"text":"Open passport","type":"plain_text"},'
    b'"type":"button","url":"https://smadp.example/passports/vdt_GOLDEN.html"}],'
    b'"type":"actions"}],'
    b'"text":"Passport generated for vdt_GOLDEN"}'
)


def test_vanta_golden():
    adapter = get_adapter(IntegrationKind.VANTA)
    body = adapter.translate(
        _FIXED_ENVELOPE, config={"token": "tok", "evidence_request_id": "req_GOLDEN"}
    )
    assert body == _VANTA_EXPECTED


def test_drata_golden():
    adapter = get_adapter(IntegrationKind.DRATA)
    body = adapter.translate(
        _FIXED_ENVELOPE, config={"token": "tok", "control_id": "ctrl_GOLDEN"}
    )
    assert body == _DRATA_EXPECTED


def test_slack_golden():
    adapter = get_adapter(IntegrationKind.SLACK)
    body = adapter.translate(_FIXED_ENVELOPE, config={})
    assert body == _SLACK_EXPECTED
```

- [ ] **Step 2: Run the golden tests**

Run: `pytest tests/golden/test_integration_payloads_golden.py -v`

If `_VANTA_EXPECTED` / `_DRATA_EXPECTED` / `_SLACK_EXPECTED` mismatch the actual bytes (insertion order vs sort order, escaping of `↔`), **adjust the expected bytes literal to match the actual output verbatim** — these are golden fixtures, not behavioral assertions. Re-run until PASS. Do **not** loosen the equality check.

Expected: PASS after at most one fixup pass.

- [ ] **Step 3: Commit**

```bash
git add tests/golden/test_integration_payloads_golden.py
git commit -m "test(integrations): byte-stable golden payloads for Vanta/Drata/Slack"
```

### Part B — CI smoke for vendor claim verify

- [ ] **Step 4: Add a CI smoke step**

Read `.github/workflows/ci.yml`. Insert a new step between the existing `Smoke — webhook full lifecycle` step and the `catalog-lint` step (or wherever Plan 3 placed the smoke):

```yaml
      - name: Smoke — vendor repo-claim verify
        run: |
          python - <<'PY'
          import http.server, threading, os, tempfile
          from smadp.config import Config
          from smadp.schemas.tenancy import Plan, Role
          from smadp.schemas.vendor import ClaimMethod, RepoEvidence
          from smadp.tenancy import store as tenancy
          from smadp.vendor import store, verifier

          os.environ["SMADP_CACHE_DIR"] = tempfile.mkdtemp()
          os.environ["SMADP_KEK_MASTER"] = "0" * 64
          os.environ["SMADP_PUBLIC_BASE_URL"] = "http://localhost:8765"
          cfg = Config()

          ws = tenancy.create_workspace(name="ci", plan=Plan.PUBLIC, config=cfg)
          tenancy.add_member(workspace_id=ws.id, user_id="ci", role=Role.ADMIN, config=cfg)
          claim = store.create_claim(
              workspace_id=ws.id, agent_id="ci-agent", vendor_user_id="ci",
              method=ClaimMethod.REPO,
              evidence_url="http://localhost:8765",
              config=cfg,
          )

          token = claim.token

          class H(http.server.BaseHTTPRequestHandler):
              def do_GET(self):
                  if self.path.endswith("/.smadp/owner.txt"):
                      body = token.encode()
                      self.send_response(200)
                      self.send_header("Content-Length", str(len(body)))
                      self.end_headers()
                      self.wfile.write(body)
                  else:
                      self.send_response(404); self.end_headers()
              def log_message(self, *a, **k): pass

          srv = http.server.HTTPServer(("127.0.0.1", 8765), H)
          t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
          try:
              result = verifier.verify_repo(
                  claim=claim, evidence=RepoEvidence(repo_url="http://localhost:8765"),
              )
              assert result.verified, result.detail
              store.mark_claim_verified(claim_id=claim.id, config=cfg)
              loaded = store.get_claim(claim_id=claim.id, config=cfg)
              assert loaded.status.value == "verified"
              print("vendor smoke ok")
          finally:
              srv.shutdown()
          PY
```

- [ ] **Step 5: Locally validate the CI script (no GitHub run needed)**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"`
Expected: no parse errors.

Run the heredoc body locally:

```bash
mkdir -p /tmp/smadp-vendor-smoke && \
SMADP_CACHE_DIR=/tmp/smadp-vendor-smoke \
SMADP_KEK_MASTER=$(python -c "print('0'*64)") \
SMADP_PUBLIC_BASE_URL=http://localhost:8765 \
python <<'PY'
# (Paste the same script body here.)
PY
```

Expected output: `vendor smoke ok`.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci(vendor): add repo-claim verify smoke step"
```

### Part C — Final sweep (ruff + spec cross-check)

- [ ] **Step 7: Run ruff fix + format + full test suite**

```bash
uv run ruff check --fix smadp/ tests/
uv run ruff format smadp/ tests/
uv run pytest -ra
```

Expected: 0 ruff issues; all tests PASS.

If `ruff check` flags issues that auto-fix did not resolve, fix them manually (DO NOT use `# noqa` to silence them). Common Plan 4 cases: `RUF059` unused tuple unpack (use `_` prefix), `UP007` `Optional[X]` → `X | None` (already enforced).

- [ ] **Step 8: Spec cross-check (record deviations)**

Review against `docs/superpowers/specs/2026-05-03-v2-d-audience-cd-design.md`. Anything in §6.6, §6.8, §7.3, §7.4, §7.5, §8.1, §8.3 that we did NOT ship is a known deferral — record it in this commit message:

Known deferrals from spec → Plan 4:
- SMTP delivery for email-magic-link (Pre-flight: deferred to Plan 5/6)
- Refresh queue integration on dispute resolve_reeval (Pre-flight: Plan 5 owns refresh; we record the intent in `dispute.resolved` transparency event, do not import refresh)
- Live Vanta/Drata API credential testing (spec §10.5: gated on `SMADP_INTEGRATION_TESTS=1`; we ship mock-shape translators)
- Automated SLA breach paging / dashboard badge (spec §9: "humans must resolve"; landing in Plan 6 frontend)
- Agent-card editing (spec §6.6 lists "vendor edits, dispute filing"; agent-card surface deferred to Plan 5)

Spec features shipped exactly as written: claim verification (3 methods), dispute two-stage state machine, vendor responses, native integrations (vanta/drata/slack), per-subscription integration_kind/integration_config, dispatcher pre-translation, worker header overlay.

Spec deviations (vs literal text): none beyond the deferrals above.

- [ ] **Step 9: Commit the sweep**

```bash
git add -A
git commit -m "chore(plan-4): final sweep — ruff + format + spec cross-check

Known deferrals (recorded in plan):
- SMTP for email magic-link (Plan 5/6)
- Refresh queue integration on dispute_resolve_reeval (Plan 5)
- Live Vanta/Drata credentials in CI (gated by SMADP_INTEGRATION_TESTS)
- SLA breach paging/badge (Plan 6 frontend)
- Agent-card editing surface (Plan 5)

All 22 tasks shipped per plan; full test suite green."
```

---

## Done

After Task 22, the following surfaces are live:

- `smadp.vendor.{store,verifier,api,cli}` — claims (3 methods), responses, disputes (2-stage state machine)
- `smadp.integrations.{base,generic,vanta,drata,slack}` — adapter registry + 4 translators
- Webhooks API/store/dispatcher/worker support per-subscription `integration_kind` + `integration_config`
- New deps: `dnspython>=2.6`
- New env: `SMADP_PUBLIC_BASE_URL`
- New SQLite file: `<cache_dir>/vendor.db`
- New SQLite columns: `subscriptions.integration_kind`, `subscriptions.integration_config`, `webhook_deliveries.headers_overlay` (idempotent ALTERs)

Next plan in v2-D queue: **Plan 5 — Refresh + Frameworks** (`smadp.refresh.*` watchers + `smadp.frameworks.*` cross-walks; consumes the `dispute.resolved` transparency event from Plan 4 to drive `trigger='dispute'` refresh runs).
