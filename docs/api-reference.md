# API Reference

The SMADP REST API serves the catalog. Every endpoint is read-only except `POST /api/agents` (submit a new agent for unverified profiling) and `POST /api/evaluate` (request verdicts for a list of agents). The API is implemented with FastAPI; the canonical machine-readable schema is at `/openapi.json` when the server is running.

Spec reference: §17. Code lives in `smadp/api/`.

Start the server:

```bash
smadp serve --port 8000
```

Base URL in examples: `http://localhost:8000`.

---

## GET /api/agents

List Safety Profiles, with optional filters.

**Query parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `category` | string | Filter by `category` field (e.g., `coding`, `notes`, `email`). |
| `source_type` | `open-source` \| `closed-source` | Filter by source type. |
| `verification` | `verified` \| `draft` \| `unverified` \| `stale` | Filter by `verification.status`. |
| `limit` | int (default 50) | Page size. |
| `cursor` | string | Opaque cursor for pagination. |

**Response 200:**

```json
{
  "items": [ { "slug": "claude-code", "name": "Claude Code", "category": "coding", "source_type": "closed-source", "verification_status": "verified" } ],
  "next_cursor": null
}
```

**Example:**

```bash
curl 'http://localhost:8000/api/agents?source_type=open-source&verification=verified'
```

---

## GET /api/agents/{slug}

Return a single Safety Profile by slug. Schema in spec §7.1.

**Path parameter:** `slug` — the canonical slug (lowercase, hyphenated).

**Response 200:** the full profile JSON, including `evidence_refs` (sha references; resolve with `/api/evidence/{sha}` if exposed in your build).

**Status codes:**

- `200` — found
- `404` — slug not in catalog (try `/api/search?q=` to find the right slug)

**Example:**

```bash
curl http://localhost:8000/api/agents/claude-code
```

---

## GET /api/verdicts

List Verdicts, with optional filters.

**Query parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `risk` | `A` \| `B` \| `C` \| `D` \| `E` | Filter to verdicts whose named risk is at least `min_severity`. |
| `min_severity` | `low` \| `medium` \| `high` \| `critical` | Minimum severity for the named risk. |
| `evidence_level` | `unverified-profile` \| `docs-only` \| `profile-verified` \| `sandbox-validated` | Filter by evidence level. |
| `agent` | string | Slug — return verdicts involving this agent. |
| `limit` | int (default 50) | Page size. |
| `cursor` | string | Opaque cursor for pagination. |

**Response 200:**

```json
{
  "items": [
    {
      "verdict_id": "v_2026-05-02_claude-code__cursor_a3f1",
      "pair": ["claude-code", "cursor"],
      "evidence_level": "docs-only",
      "composite_score": 0.42,
      "headline": "Caution — overlapping filesystem write surfaces and uncoordinated git state."
    }
  ],
  "next_cursor": null
}
```

**Example:**

```bash
curl 'http://localhost:8000/api/verdicts?risk=C&min_severity=high'
```

---

## GET /api/verdicts/{a}/{b}

Return the verdict for an alphabetized pair of slugs. Slugs are auto-alphabetized; `claude-code/cursor` and `cursor/claude-code` resolve to the same verdict.

**Response 200:** the full Verdict JSON, schema in spec §7.2. Fields include `sub_verdicts` (per-risk severity, rationale, citations, conditions, mitigations), `composite_score`, `framework_mappings`, `reproducibility`, `sandbox_runs`.

**Status codes:**

- `200` — found
- `404` — verdict not yet generated. Use `POST /api/evaluate` to request generation.

**Example:**

```bash
curl http://localhost:8000/api/verdicts/claude-code/cursor
```

---

## POST /api/agents

Submit a new agent for unverified profiling. The Profiler pipeline ([`methodology.md`](methodology.md) §2) runs and writes the result under `profiles/_unverified/<slug>.json`.

In v1 this endpoint is auth-gated to prevent abuse; the authentication scheme is deployment-specific. Public submission via the dashboard remains the primary path.

**Request body:**

```json
{
  "name": "My Agent",
  "homepage": "https://my-agent.example",
  "repo_url": "https://github.com/my-org/my-agent",
  "docs_urls": ["https://my-agent.example/docs"]
}
```

At least one of `repo_url` or `docs_urls` is required.

**Response 202 Accepted:**

```json
{
  "slug": "my-agent",
  "verification_status": "unverified",
  "profile_url": "/api/agents/my-agent",
  "chronicle_event": "profile.created"
}
```

**Status codes:** `202` accepted, `400` invalid request body, `409` slug already exists, `429` rate-limited.

**Example:**

```bash
curl -X POST http://localhost:8000/api/agents \
  -H 'Content-Type: application/json' \
  -d '{"name":"My Agent","repo_url":"https://github.com/my-org/my-agent"}'
```

---

## POST /api/evaluate

Request verdicts for a list of agents. Returns the full pairwise matrix.

**Request body:**

```json
{
  "agents": ["claude-code", "cursor", "gemini-cli"],
  "force_regenerate": false
}
```

`agents` is a list of slugs (or URLs to be auto-profiled into unverified slugs first). `force_regenerate` (default `false`) bypasses the verdict cache; otherwise verdicts whose reproducibility hashes match the current inputs are returned from cache.

**Response 200:**

```json
{
  "agents": ["claude-code", "cursor", "gemini-cli"],
  "verdicts": [
    { "pair": ["claude-code", "cursor"], "verdict_id": "v_...", "composite_score": 0.42, "evidence_level": "docs-only" },
    { "pair": ["claude-code", "gemini-cli"], "verdict_id": "v_...", "composite_score": 0.31, "evidence_level": "docs-only" },
    { "pair": ["cursor", "gemini-cli"], "verdict_id": "v_...", "composite_score": 0.55, "evidence_level": "docs-only" }
  ],
  "missing": [],
  "regenerated": []
}
```

`missing` lists pairs where the verdict could not be generated (e.g., one agent has no profile yet). `regenerated` lists pairs whose cached verdict was invalidated and re-run.

**Example:**

```bash
curl -X POST http://localhost:8000/api/evaluate \
  -H 'Content-Type: application/json' \
  -d '{"agents":["claude-code","cursor"]}'
```

---

## GET /api/search

Full-text search across profiles and verdicts.

**Query parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `q` | string (required) | Query string. |
| `type` | `profile` \| `verdict` \| `both` (default `both`) | Restrict to one document type. |
| `limit` | int (default 20) | Page size. |

**Response 200:**

```json
{
  "results": [
    { "type": "profile", "slug": "claude-code", "score": 0.91, "snippet": "...permission before writing files..." },
    { "type": "verdict", "verdict_id": "v_...", "pair": ["claude-code","cursor"], "score": 0.84, "snippet": "...overlapping filesystem write..." }
  ]
}
```

**Example:**

```bash
curl 'http://localhost:8000/api/search?q=oauth+scopes'
```

---

## GET /api/frameworks

List all framework mappings from `catalog/_meta/frameworks.json`. See [`framework-mappings.md`](framework-mappings.md).

**Response 200:** the contents of `frameworks.json` plus an `applied_count` field per control showing how many published verdicts cite that control.

**Example:**

```bash
curl http://localhost:8000/api/frameworks
```

---

## GET /api/chronicle

Return chronicle entries (audit log). See spec §7.4 for the event schema.

**Query parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `since` | ISO-8601 timestamp | Return events strictly after this timestamp. |
| `event` | string | Filter by event type (e.g., `verdict.generated`, `profile.refreshed`). |
| `limit` | int (default 100) | Page size. |

**Response 200:**

```json
{
  "events": [
    {"ts":"2026-05-02T03:14:00Z","event":"verdict.generated","verdict_id":"v_...","pair":["claude-code","cursor"]}
  ]
}
```

**Example:**

```bash
curl 'http://localhost:8000/api/chronicle?event=verdict.generated&limit=10'
```

---

## WS /api/sandbox/runs/{run_id}

WebSocket stream of sandbox-run progress. Each frame is a JSON object representing a captured event from the run (stdout chunk, file IO event, network attempt, status transition).

**Frame format:**

```json
{ "ts": "2026-05-02T03:14:01Z", "kind": "stdout", "agent": "agent-a", "data": "..." }
```

`kind` is one of `stdout`, `stderr`, `file_io`, `network_attempt`, `status`, `transcript_chunk`.

The connection closes when the run terminates (`completed` or `failed`), with a final `status` frame.

---

## GET /api/health

Liveness and readiness probe.

**Response 200:**

```json
{
  "status": "ok",
  "catalog_commit": "abc123...",
  "schema_version": "1.0",
  "rubric_version": "1.0",
  "uptime_seconds": 12345
}
```

---

## OpenAPI

The full machine-readable schema is published at `/openapi.json` when the server is running. The interactive documentation (Swagger UI) is at `/docs`. Both are generated from the FastAPI handlers and stay in sync with the implementation.

---

Last updated: 2026-05-02
