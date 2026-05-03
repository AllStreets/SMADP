# SMADP v2-D — Audience C/D Coverage

**Status:** Approved design — ready for implementation planning
**Date:** 2026-05-03
**Backlog item:** D from `docs/v2-backlog.md`
**Successor of:** SMADP v1 (shipped, see `git log` and `docs/architecture.md`)

---

## 1. Overview

v1 produces auditable verdicts on whether two AI agents can safely run together. The artifacts are catalog files and a static Astro dashboard — fine for developers and operators, insufficient for the four other audiences who decide whether SMADP is bought, deployed, and trusted:

| Persona | Wants |
|---|---|
| External SOC 2 / ISO auditor | Tamper-evident evidence mapped to specific controls |
| Enterprise procurement / vendor-risk | Comparable cross-vendor risk packets, framework cross-walks, security-questionnaire pre-fills |
| Internal compliance / GRC | Portfolio view of "agents we've deployed," continuous freshness signals |
| CISO / exec buyer | One-page risk summary with traffic-light verdicts and a defensible decision |

v2-D adds the surfaces, artifacts, and integrations that serve all four personas from one generalized platform without forking the product.

---

## 2. Goals

- A single live dashboard that serves all four personas with a persona-switched home and progressive disclosure (collapsible panels)
- A signed, self-contained HTML "passport" artifact that any auditor can verify offline
- A webhook delivery surface so customers' GRC systems (Vanta, Drata, Slack at launch) auto-consume verdict events
- Cross-walks of every verdict to **eleven** frameworks: NIST AI RMF, ISO 42001, OWASP LLM Top 10 (already in v1) + EU AI Act, SOC 2, HIPAA, PCI DSS, GDPR (Art. 22 + 35), FedRAMP Moderate, CAIQ/SIG, NIST CSF 2.0
- A verifiable, public-by-default catalog with private workspaces for enterprises and claimed listings for vendors
- Event-driven verdict refresh with a 90-day TTL backstop so passports are never silently stale

## 3. Non-goals

- Live user-facing Lab (browser-based interactive sandbox) — backlog item A
- Capability adapters for closed-source agents — backlog item B
- Multi-agent chains of 3+ agents — backlog item C
- Federation across SMADP instances — explicitly out of scope; single hosted instance + private workspaces
- Pricing / billing implementation — product concern, not in this spec
- Full coverage of HIPAA Privacy Rule, complete PCI DSS audit prep, or FedRAMP authorization paperwork — we map verdicts to controls; we do not become an auditor

---

## 4. Established decisions (locked during brainstorm)

| Decision | Choice |
|---|---|
| Personas | All four served from one surface |
| Artifacts | Live dashboard + signed HTML passport + webhook |
| Frameworks | All 8 new (in addition to v1's 3) |
| Trust model | Sigstore-style transparency log (default) + optional BYOK signing keys |
| Tenancy | Single hosted instance: public catalog + private workspaces + claimed vendor listings |
| Verdict refresh | Event-driven + 90-day TTL backstop |
| Refresh triggers | 7 trigger types: repo release tag, dependency CVE, LLM model bump, framework version update, scoring weights bump, manual trigger, vendor agent-card update (skip: every-commit-on-default-branch) |
| Dashboard IA | Hybrid persona-switched home with cards into deployments / framework coverage / catalog / exec summary; all collapsible |
| UI/UX | Modern, attractive, dark/violet theme; collapsible panels; **icons only — no emojis** |
| Webhook events | 6 types — `verdict.created`, `verdict.updated`, `verdict.expired`, `framework_coverage.changed`, `passport.generated`, `passport.revoked` |
| Webhook delivery | At-least-once with HMAC-SHA256, 5 retries, exponential backoff |
| Subscription scope | Per-workspace |
| Native integrations | Vanta + Drata + Slack at v2-D launch; ServiceNow + Jira deferred to v2.x |
| Vendor verification | All three methods (repo-file / DNS-TXT / email magic-link), vendor picks |
| Vendor edits | Metadata + agent card + verdict response |
| Disputes | Two-stage (triage → if substantive, 5-business-day SLA) |

---

## 5. Architecture

### 5.1 Process model (hybrid: monolith + isolated worker)

**Process A — FastAPI app** (extends v1, single deploy unit). Handles every synchronous workload: catalog reads, dashboard JSON, passport generation, vendor flows, webhook subscription CRUD, transparency log writes.

**Process B — Webhook delivery worker** (separate, runs alongside the API). Consumes a SQLite-backed queue (same pattern as v1's `smadp/sandbox/queue.py`). Isolated so a slow Slack subscriber cannot starve API requests.

The hybrid was chosen over (a) a pure monolith (would couple delivery latency to the API process) and (b) a three-service split (premature for v2-D's load). Webhook delivery can be promoted to its own service later if traffic demands it.

### 5.2 Storage

- **SQLite, WAL mode** stays primary (matches v1)
- New tables: `workspaces`, `workspace_members`, `subscriptions`, `webhook_deliveries`, `signing_keys`, `signed_events`, `vendor_claims`, `vendor_responses`, `disputes`, `refresh_queue` (full schema in §8)
- Modified table: `verdicts` gains `last_refresh_trigger`, `last_refresh_detail`, `next_refresh_due`
- New catalog files: `catalog/_meta/refresh_triggers.json`; entries added to `catalog/_meta/frameworks.json` for the 8 new frameworks

### 5.3 Frontend

The Astro site grows new sections without changing build/deploy shape: `/home`, `/workspaces/...`, `/frameworks/...`, `/passports/...`, `/vendor/...`. Static paths stay statically built; dynamic surfaces (workspace dashboards, passport viewers) hit the FastAPI backend via the existing client lib. Lucide icons inlined as SVG (or equivalent — picked during plan phase). **No emoji as UI affordance, anywhere.**

### 5.4 External dependencies (new)

- Sigstore Python client (or self-hosted Rekor mirror — picked during plan phase)
- `cryptography` for Ed25519 signing of passports
- Vanta + Drata REST clients (lightweight, no SDKs)
- Slack incoming-webhook (no SDK needed)
- `dnspython` for DNS-TXT vendor verification

---

## 6. Components

Each component is small enough to hold in context, has one purpose, and is tested in isolation.

### 6.1 `smadp.tenancy`
- **Does:** workspaces, members, roles (`viewer` / `editor` / `admin` / `owner`), BYOK signing-key storage with at-rest encryption (AES-GCM, workspace-derived KEK).
- **Public:** `Workspace`, `Member` Pydantic models; `current_workspace(request)` and `require_role(role)` FastAPI dependencies.

### 6.2 `smadp.transparency`
- **Does:** append-only signed-event journal. Every state change is `{event_type, payload, ts, prev_hash, signature}`. Optionally mirrors entries to public Rekor.
- **Public:** `append_event(event_type, payload) -> SignedEntry`, `verify_chain() -> bool`, `get_inclusion_proof(entry_id) -> Proof`.

### 6.3 `smadp.passport`
- **Does:** renders a verdict + 11-framework cross-walks + evidence into a single self-contained signed HTML file. Embeds JSON evidence as a base64 `<data>` attachment for download.
- **Public:** `render_passport(verdict_id, *, signing_strategy) -> bytes`, `verify_passport(html_bytes) -> VerificationResult`.

### 6.4 `smadp.webhooks.api`
- **Does:** CRUD on subscriptions; enqueues deliveries when bus events fire.
- **Public:** FastAPI router; `dispatch_event(event_type, payload, workspace_id)`.

### 6.5 `smadp.webhooks.worker`
- **Does:** separate process. Polls `webhook_deliveries`, signs and POSTs, retries with exponential backoff (1s/4s/16s/64s/256s, then `exhausted`).
- **Public:** `python -m smadp.webhooks.worker` entry point.

### 6.6 `smadp.vendor`
- **Does:** claim verification (3 methods), vendor edits, dispute filing.
- **Public:** FastAPI router; `claim_verify(method, evidence) -> ClaimResult`; `file_dispute(verdict_id, vendor_id, argument) -> Dispute`.

### 6.7 `smadp.refresh`
- **Does:** watchers for the 7 trigger types. Each writes to `refresh_queue`; the existing v1 evaluator drains it.
- **Public:** `python -m smadp.refresh.poller` entry per trigger; `enqueue_manual_refresh(verdict_id, reason)`.

### 6.8 `smadp.integrations.{vanta,drata,slack}`
- **Does:** per-vendor adapters that translate the generic webhook envelope into the vendor's native API call.
- **Public:** `deliver(payload, integration_config)` per integration.

---

## 7. Data flows

### 7.1 Verdict refresh (the heartbeat)

```
refresh.poller (any of 7 watchers) → detects change
  → INSERT refresh_queue (verdict_id, trigger, ts)
v1 evaluator → drains refresh_queue
  → re-runs profile + judge + sandbox as needed
  → UPDATE verdicts (last_refresh_trigger, next_refresh_due = now+90d)
  → transparency.append_event("verdict.updated", {...})
  → webhooks.api.dispatch_event("verdict.updated", payload, workspace_id)
  → for each matching subscription: INSERT webhook_deliveries (pending)
webhook_deliveries → consumed by worker (separate process)
```

The trigger reason flows all the way to the passport, which renders e.g. *"Refreshed because anthropic/claude-sonnet-4.7 was released."*

### 7.2 Passport generation & signing

```
GET /passports/{verdict_id}.html
  → tenancy: resolve workspace, check viewer role
  → tenancy: resolve signing strategy (sigstore default | BYOK key for this workspace)
  → passport.render_passport(verdict_id, signing_strategy)
      → load verdict + framework mappings (11 frameworks) + evidence index
      → render Jinja2 template with inlined SVG icons
      → embed evidence JSON as base64 <data> attachment
      → sign payload with Ed25519 (sigstore: ephemeral key + cert; BYOK: workspace key)
      → transparency.append_event("passport.generated", {...})
      → if sigstore: submit to Rekor; embed inclusion proof in <meta> tags
  → return signed HTML bytes (Content-Disposition: inline)
  → fire webhook event passport.generated
```

Verifier (`smadp passport verify foo.html` or drag-drop to `/passport-verify`) reverses the signing: extract sig + Rekor proof from `<meta>`, recompute hash, walk the chain.

### 7.3 Webhook delivery

```
worker loop (separate process):
  SELECT * FROM webhook_deliveries
   WHERE status='pending' AND next_attempt_at <= now LIMIT 100
  for each row (with BEGIN IMMEDIATE):
    sig = HMAC-SHA256(subscription.secret, body)
    POST subscription.url, headers={X-SMADP-Event, X-SMADP-Signature, X-SMADP-Delivery-Id}
    on 2xx: status='delivered'
    on 4xx (no retry): status='failed', last_error
    on 5xx/timeout: attempts+=1, next_attempt_at=now+backoff(attempts)
                    if attempts >= 5: status='exhausted', transparency event written
```

Native integrations (vanta/drata/slack) sit upstream of the worker: when subscription targets a native integration, dispatcher writes the *translated* payload into the queue. Worker loop is uniform; only the body shape differs.

### 7.4 Vendor claim

```
POST /vendor/claims  body: {agent_id, method: "repo|dns|email"}
  → vendor.create_claim → returns {token, instructions}
vendor adds proof (file in repo / DNS TXT / email click-through)
POST /vendor/claims/{claim_id}/verify
  → vendor.claim_verify(method, evidence)
      → repo:  httpx.get(repo_url + "/.smadp/owner.txt"), check token
      → dns:   dnspython lookup _smadp-owner.<domain>, check token
      → email: validate magic link
  → on success: status='verified', granted_at=now
                vendor user gets editor role on their agent
                transparency.append_event("vendor.claim_verified", {...})
```

Post-verification, vendor can edit metadata, agent card, or post verdict responses. Each edit is its own transparency event so audit trail shows vendor-vs-SMADP authorship.

### 7.5 Dispute (two-stage)

```
verified vendor → POST /verdicts/{id}/disputes  body: {argument, requested_outcome}
  → status='triage', transparency event, internal Slack ping

SMADP triage → PATCH /disputes/{id}  body: {decision: "spam|substantive"}
  if spam: status='closed', no public surface
  if substantive:
    status='pending_review' (5-business-day SLA)
    passport + dashboard render "Dispute Pending — vendor argues..." badge
    SMADP must commit to either:
      - re-eval (triggers §7.1 refresh with trigger="dispute"), or
      - publish "dispute resolved — verdict stands" with rationale
    transparency.append_event("dispute.resolved", ...)
```

---

## 8. Schemas & data model

### 8.1 New SQLite tables

```sql
workspaces (id PK, name, plan ENUM('public','private'), created_at)
workspace_members (workspace_id, user_id, role ENUM, PK(workspace_id,user_id))

subscriptions (
  id PK, workspace_id, url, secret_hash, event_types JSON,
  active BOOL, created_at
)

webhook_deliveries (
  id PK, subscription_id, event_id, body BLOB,
  status ENUM('pending','delivered','failed','exhausted'),
  attempts INT, next_attempt_at, last_error,
  created_at, delivered_at,
  INDEX (status, next_attempt_at)
)

signing_keys (
  workspace_id PK, algorithm='ed25519',
  public_key BLOB, private_key_encrypted BLOB,
  created_at, rotated_from
)

signed_events (
  id PK AUTOINCREMENT, event_type, payload, ts,
  prev_hash, signature BLOB, rekor_uuid NULLABLE
)

vendor_claims (
  id PK, agent_id, vendor_user_id,
  method ENUM, token,
  status ENUM('pending','verified','revoked'),
  granted_at, revoked_at
)

vendor_responses (id PK, verdict_id, vendor_user_id, body_md, created_at)

disputes (
  id PK, verdict_id, vendor_user_id, argument_md,
  requested_outcome ENUM('reeval','withdraw','amend'),
  status ENUM('triage','pending_review','resolved_reeval','resolved_stands','spam'),
  decision_rationale_md,
  filed_at, triaged_at, resolved_at
)

refresh_queue (
  id PK AUTOINCREMENT, verdict_id,
  trigger ENUM(9 values: 7 trigger types + 'ttl' + 'dispute'),
  trigger_detail JSON,
  enqueued_at, claimed_at, done_at,
  INDEX (claimed_at, enqueued_at)
)
```

### 8.2 Modified table

```sql
ALTER TABLE verdicts ADD last_refresh_trigger TEXT;
ALTER TABLE verdicts ADD last_refresh_detail TEXT;   -- JSON
ALTER TABLE verdicts ADD next_refresh_due TIMESTAMP;
```

### 8.3 Pydantic models (live in `smadp/schemas/`, all `extra="forbid"`)

- `tenancy.py`: `Workspace`, `Member`, `Role` enum
- `webhooks.py`: `Subscription`, `EventType` enum, `WebhookDelivery`, `WebhookEnvelope`
- `passport.py`: `PassportRenderRequest`, `SigningStrategy` enum, `VerificationResult`
- `transparency.py`: `SignedEvent`, `InclusionProof`
- `vendor.py`: `VendorClaim`, `ClaimMethod` enum, `VendorResponse`, `ClaimVerificationEvidence` (discriminated union)
- `dispute.py`: `Dispute`, `DisputeStatus` enum, `DisputeDecision` enum
- `refresh.py`: `RefreshTrigger` enum (9 values), `RefreshQueueItem`

### 8.4 Webhook envelope (stable contract)

```json
{
  "id": "evt_01HXXX",
  "type": "verdict.updated",
  "created_at": "2026-05-03T12:34:56.789Z",
  "workspace_id": "ws_01HYYY",
  "data": {
    "verdict_id": "vdt_01HZZZ",
    "agent_pair": ["anthropic/claude-research", "openai/swe-agent"],
    "composite_score": 0.42,
    "previous_score": 0.31,
    "trigger": "model_bump",
    "trigger_detail": {"provider": "anthropic", "model": "claude-sonnet-4.7"},
    "passport_url": "https://smadp.io/passports/vdt_01HZZZ.html",
    "framework_coverage_delta": {"nist_ai_rmf": ["GOVERN-1.4"]}
  },
  "signature_meta": {
    "transparency_log_id": 4827193,
    "prev_event_hash": "sha256:..."
  }
}
```

Headers on POST: `X-SMADP-Signature: sha256=<hmac>`, `X-SMADP-Delivery-Id`, `X-SMADP-Event-Type`.

---

## 9. Error handling & failure modes

| Failure | Behavior |
|---|---|
| **Inbound API errors** | Uniform with v1's RFC-7807 envelope. New error types include `passport_not_found`, `passport_signature_invalid`, `subscription_url_unreachable_at_create`, `vendor_claim_token_mismatch`, `dispute_already_filed`, `byok_key_missing_for_workspace`. |
| **Outbound webhook delivery** | Worker retries 5 times with exponential backoff. After exhaustion: row marked `exhausted`, transparency event written, dashboard shows red badge on subscription. Operator can re-enqueue. Each event is independent — exhausted delivery does not block subsequent deliveries. |
| **Sigstore / Rekor unreachable** | Passport generation falls back to *self-signed* mode; `transparency_status: "deferred"` written in `<meta>`. Background task retries Rekor every 60s; on success, inclusion proof is patched into next render. Verifier accepts either, with warning on `deferred`. |
| **BYOK key missing or corrupted** | Passport generation hard-fails with 500 + RFC-7807. **Never silently fall back to sigstore** — would invalidate BYOK trust contract. Workspace settings page banners the missing key. |
| **Refresh worker crash mid-eval** | `refresh_queue.claimed_at` has a 5-minute lease. Reaper re-queues any row where `claimed_at < now - 5min` and `done_at IS NULL`. Idempotent at the evaluator level — re-runs are deterministic. |
| **Vendor claim network errors** | `httpx` 10s timeout, 2 retries with backoff. On exhaustion, claim stays `pending` with explanatory error; vendor can switch methods. Token never expires until manually revoked. |
| **Tampered passport** | Verifier fails closed on any of: signature mismatch, prev_hash chain break, Rekor inclusion proof invalid, signing-strategy/cert-subject mismatch. Returns `VerificationResult(valid=False, reason=...)`. |
| **Concurrency on queue claims** | Both `webhook_deliveries` and `refresh_queue` use `BEGIN IMMEDIATE` + `UPDATE ... WHERE status='pending' RETURNING *` (matches v1 sandbox queue). Two workers cannot claim the same row. |
| **Dispute SLA breach** | If `pending_review` AND `triaged_at + 5 business days < now`, dashboard renders "SLA breached" badge (visible to vendor and reader). SMADP team paged via internal Slack. No automated state transition — humans must resolve. |
| **Transparency log corruption** | Nightly integrity job runs `verify_chain()`. On break: `transparency.append_event("integrity.alert", ...)` (the alert chains forward), on-call paged. Old entries are not retroactively repaired. |
| **Storage growth** | `signed_events` grows ~365MB/year per active workspace (1KB × 1000 events/day estimate). Acceptable. No GC. Offline export available via `smadp transparency export`. |
| **SQLite lock contention at scale** | Same risk profile as v1. Documented migration path (split `webhook_deliveries` to its own SQLite file → PG) is post-v2-D. |

---

## 10. Testing strategy

Mirrors v1's pyramid (`tests/unit/`, `tests/integration/`, `tests/golden/`); same `pytest -ra --strict-markers` config; CI matrix (Python 3.11 + 3.12) extended with new integrity steps.

### 10.1 Unit (per module, fast, no I/O)

- `tenancy`: full RBAC matrix, every workspace-isolation boundary
- `transparency`: chain append + `verify_chain` over fabricated logs; tamper detection on every column
- `passport`: render-without-signing produces stable structure; `verify_passport` rejects tampered HTML, swapped signatures, broken Rekor proof, signing-strategy mismatch
- `webhooks.api`: subscription matching; dispatcher enqueues correctly; HMAC matches hand-computed reference
- `webhooks.worker`: retry/backoff timing using freezegun; 4xx → no retry; 5xx → retry; >5 → exhausted; idempotency on duplicate claim
- `vendor`: each verification method (repo/DNS/email) — happy + token mismatch + transport error
- `refresh.{watcher}`: each watcher in isolation, mocking the upstream API
- `integrations.{vanta,drata,slack}`: payload-shape unit tests against vendor docs

### 10.2 Integration (real SQLite, FastAPI TestClient, `respx` for outbound HTTP)

- Full webhook lifecycle: dispatch → row → worker → fake server receives signed POST → `delivered`
- Full passport lifecycle: trigger → re-eval → render → transparency event → webhook fires → verifier accepts
- Vendor end-to-end per method, then post-claim: agent-card edit → re-eval → vendor response on verdict
- Dispute end-to-end: file → triage spam (silent close) + triage substantive (badges) → re-eval resolves → badges clear, transparency event recorded
- BYOK: upload key → render → verify with workspace pubkey, NOT sigstore key
- Sigstore unreachable: simulate Rekor 503 → `deferred` rendered → background retry succeeds → next render carries proof

### 10.3 Golden (byte-stable for fixed input)

- Passport HTML render of a fixed verdict (per Python version)
- Webhook envelope JSON for each of the 6 event types
- Transparency event canonicalization (signature input)
- Framework cross-walk output for each of the 11 frameworks
- Sigstore inclusion-proof embedding format

### 10.4 Security-specific

- Tampered-passport corpus (10+ varieties) — each must fail verification with a specific `reason`
- Cross-workspace data leak: every endpoint hit with `workspace_id=other` must 403
- Webhook signature replay: subscriber-side responsibility, but our `X-SMADP-Delivery-Id` is unique and tested

### 10.5 Native integrations

- Vanta + Drata: against sandbox APIs when CI has credentials; otherwise `respx` against recorded fixtures. Marked `@pytest.mark.integration`, gated on `SMADP_INTEGRATION_TESTS=1`.
- Slack: against captured webhook URL in private test channel; `respx`-mocked in CI by default.

### 10.6 End-to-end smoke (`tests/e2e/test_v2d_smoke.py`, `@pytest.mark.slow`)

Spin up API + worker as subprocesses → register workspace → subscribe webhook → trigger manual refresh on fixture verdict → assert: webhook received with valid HMAC, passport downloadable and verifies, transparency log includes both events, dashboard renders new freshness band.

### 10.7 CI additions

Extend `.github/workflows/ci.yml`:
- `smadp transparency verify --since=...` (chain integrity)
- `smadp passport verify` smoke test on freshly rendered fixture passport

### 10.8 Coverage gate

Same as v1 (`pytest-cov`). New modules expected ≥85% line coverage. CI fails below threshold.

---

## 11. What this spec does NOT cover

These are deliberate scope cuts, recorded for the implementer:

- **Pricing tiers and billing** — product concern. Spec assumes existence of a "private workspace plan"; the billing implementation is separate.
- **Federation across SMADP instances** — out of scope.
- **Choice between hosted Sigstore Public Good Instance vs. self-hosted Rekor** — both are designed for; the picker happens during the implementation plan based on ops appetite.
- **Choice of icon library** (Lucide / Phosphor / Heroicons) — picked during plan. The constraint is "real SVG icons, no emoji."
- **Concrete UI mockups for each persona view** — high-level IA is locked (hybrid persona-switched home with collapsible cards); per-view layouts are produced during the implementation plan in coordination with frontend design.
- **Cost model for sigstore submission** — assumed free under Sigstore Public Good Instance terms; revisited if usage exceeds reasonable limits.

---

## 12. Implementation note

The next step is the writing-plans skill, which will turn this spec into a sequenced implementation plan (modules to build, tests-first ordering, CI gating, risk-ranked rollout). Each section of this spec maps to one or more plan stages.
