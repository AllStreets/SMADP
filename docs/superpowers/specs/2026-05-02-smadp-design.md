# SMADP — Safe Multi-Agent Deployment Platform

**Spec date:** 2026-05-02
**Spec author:** Connor Evans (with Claude)
**Target repo:** https://github.com/AllStreets/SMADP
**Status:** v1 design — approved for implementation

---

## 1. Mission

SMADP is a public, open-source platform that publishes auditable, evidence-cited verdicts on whether two or more AI agents can safely run in the same environment. The platform exists because nobody has systematically studied what happens when popular agents (open-source from the ONEXUS-Agents catalog, plus closed-source flagships like Claude Code, Cursor, ChatGPT Desktop, Perplexity, Windsurf, Devin, Replit Agent, Copilot, Gemini CLI, Notion AI) interact with each other through shared filesystems, clipboards, OAuth scopes, MCP servers, or orchestrators — and that gap is becoming dangerous as people compose agents casually.

**The product is the catalog of verdicts.** Everything else (dashboard, API, CLI, sandbox) is a surface on top of it.

## 2. Risks in scope

The platform analyzes five risk categories. All five are tracked in every verdict; B/C/D/E are the primary focus, A is secondary but always evaluated.

| ID | Risk | Example |
|----|------|---------|
| **A** | **Prompt injection between agents** | Email-generator returns a draft containing instructions the note-taker ingests as a command |
| **B** | **Data leakage / scope violations** | Spreadsheet agent sees HR data; PowerPoint agent then exports a slide containing it |
| **C** | **Capability / permission conflicts** | Both agents authorized over same Gmail account; one's writes break the other's assumptions |
| **D** | **Cascading errors / hallucination amplification** | Agent A confidently emits wrong fact; Agent B treats it as ground truth and compounds |
| **E** | **Compliance / policy violations from composition** | Each agent fine alone, but combination violates GDPR / HIPAA / org policy |

## 3. Methodology — hybrid, layered

Three layers of evidence, each with its own audit trail. Verdicts are tagged with `evidence_level` so readers know which layer(s) supported them.

1. **Static profile (always)** — a structured Safety Profile per agent, hand-verified for the seed catalog and auto-generated + flagged `unverified` for user-submitted agents.
2. **LLM-judge over profiles + cited evidence (always)** — a frontier model (Claude Sonnet 4.6 or Opus 4.7) reasons over both profiles and source evidence to produce sub-verdicts per risk category. Every sub-verdict cites specific profile fields and evidence IDs.
3. **Sandbox validation (open-source only, v1)** — for open-source pairs, an airtight container runs both agents through scenario tasks. Observed behavior either confirms or contradicts the LLM-judge's verdict; the verdict is updated and `evidence_level` is promoted to `sandbox-validated`. **Closed-source pairs stay at `docs-only` in v1.**

The honesty about evidence level is itself a feature — security audiences cannot trust a platform that overclaims.

## 4. Audience

**Primary (B):** Security / compliance / procurement engineers at enterprises evaluating agents before approving them.

**Secondary surfaces:**
- **A:** Developers building multi-agent systems → REST API + CLI + machine-readable JSON
- **C:** Power users → traffic-light badges + plain-language verdict summaries
- **D:** Researchers → reproducibility metadata in every verdict (model, rubric version, seeds, run hashes)

## 5. Scope decomposition (v1 vs. later)

### v1 (this spec)
1. **Agent Registry** — ~30 hand-verified Safety Profiles + on-demand path for user-submitted agents
2. **Profiler** — extracts Safety Profiles from sources (with citation extraction)
3. **Pairwise Analyzer** — produces rich Verdict objects per pair
4. **Sandbox Validator** — hidden, async, queue-driven (open-source pairs only)
5. **Catalog** — git-backed JSON files, immutable audit via git history + `_chronicle/`
6. **CLI** — `smadp` command
7. **REST API** — FastAPI server
8. **Web Dashboard** — Astro + Tailwind multi-page static site

### v2 (separate brainstorm)
- Live user-facing **Lab** (interactive sandbox UI with real-time observation)
- **Capability adapters** for closed-source agents (Path B from Q6 — Claude Code via Anthropic API + binary in container, etc.)
- **Multi-agent chains** of 3+ agents
- Federation between SMADP instances

## 6. Architecture

```
                        +-----------+
                        |   USER    |
                        +-----+-----+
                              |
                      browse / submit / query
                              v
+==============================================================+
|                          S M A D P                           |
|                                                              |
|    +---------------------------------------------------+     |
|    |        Web Dashboard  /  REST API  /  CLI         |     |
|    +-------+-------------------+----------------+------+     |
|            |                   |                |            |
|         browse              submit           verdict         |
|            v                   v                v            |
|    +---------------------------------------------------+     |
|    |               CATALOG  (git-backed)               |     |
|    |   profiles/<slug>.json      verdicts/a__b.json    |     |
|    |   _evidence/      _meta/    _chronicle/           |     |
|    +-------+--------------------+----------------------+     |
|            ^                    ^                            |
|            |                    |                            |
|    +-------+--------+    +------+---------+                  |
|    |    Profiler    |    |    Pairwise    |                  |
|    |  (LLM + ext.)  |--->|    Analyzer    |                  |
|    +----------------+    |  (LLM-judge)   |                  |
|                          +--------+-------+                  |
|                                   |                          |
|                                   v                          |
|                          +----------------+                  |
|                          |    Sandbox     |                  |
|                          |   Validator    |                  |
|                          | (airtight, OS) |                  |
|                          +--------+-------+                  |
+===================================|==========================+
                                    |
                           +--------+----------+
                           |  Open-source MCP  |
                           |   agent runtime   |
                           |  (gVisor / Fcrk)  |
                           +-------------------+

  Sources for the Profiler:  GitHub / HuggingFace / vendor docs / user submissions.
```

### Components

| Layer | Role | Storage |
|-------|------|---------|
| **Sources** | GitHub, HuggingFace, vendor docs, user submissions | — |
| **Profiler** | Extract Safety Profile from sources w/ citations | `profiles/<slug>.json` + `_evidence/<sha>.json` |
| **Pairwise Analyzer** | LLM-judge over both profiles + evidence → Verdict | `verdicts/<a>__<b>.json` |
| **Sandbox Validator** | Airtight container runs of open-source pairs | Updates verdict + appends transcript |
| **Catalog** | Git-backed JSON, FTS index, schema versioned | Filesystem |
| **Surfaces** | Dashboard, API, CLI | — |

## 7. Data model

### 7.1 Safety Profile (`profiles/<slug>.json`)

```json
{
  "schema_version": "1.0",
  "slug": "claude-code",
  "name": "Claude Code",
  "tagline": "Anthropic's official CLI for Claude.",
  "vendor": { "type": "company", "handle": "Anthropic", "url": "https://anthropic.com" },
  "source_type": "closed-source",
  "category": "coding",
  "homepage": "https://claude.com/claude-code",
  "docs_urls": ["https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview"],
  "repo_url": null,
  "verification": {
    "status": "verified",
    "verified_by": "smadp-team",
    "verified_at": "2026-05-02T00:00:00Z",
    "method": "manual-review-of-llm-extraction"
  },
  "capabilities": {
    "execute_shell": true,
    "read_filesystem": true,
    "write_filesystem": true,
    "network_egress": "broad",
    "spawn_subprocesses": true,
    "use_mcp": true,
    "modify_git_state": true,
    "install_packages": true,
    "run_browsers": false
  },
  "io_surfaces": {
    "stdin_stdout": true,
    "files": ["working-directory"],
    "clipboard": false,
    "screen_capture": false,
    "audio": false,
    "calls_apis": ["anthropic.com/api/v1"]
  },
  "permissions_requested": {
    "oauth_scopes": [],
    "secrets_handled": ["ANTHROPIC_API_KEY"],
    "elevated_privileges": ["sudo-when-user-approves"]
  },
  "data_classes_touched": ["source-code", "shell-output", "user-prompts"],
  "sandboxing": {
    "self_isolation": "permission-prompt-per-action",
    "subagent_model": "explicit-Task-tool-spawning",
    "tool_use_pattern": "anthropic-tool-use"
  },
  "concurrency_model": {
    "session_scope": "per-cwd",
    "shared_state_with_other_instances": "filesystem-only",
    "supports_multiple_instances": true
  },
  "evidence_refs": ["sha256:abc...", "sha256:def..."],
  "first_seen_at": "2026-05-02T00:00:00Z",
  "last_refreshed_at": "2026-05-02T00:00:00Z"
}
```

Every populated field has at least one entry in `evidence_refs` (a content-addressed snippet under `_evidence/`).

### 7.2 Verdict (`verdicts/<slug-a>__<slug-b>.json`)

Slugs are alphabetized to make pair identity canonical: `claude-code__cursor.json` (not `cursor__claude-code.json`).

```json
{
  "schema_version": "1.0",
  "pair": ["claude-code", "cursor"],
  "verdict_id": "v_2026-05-02_claude-code__cursor_a3f1",
  "generated_at": "2026-05-02T03:14:00Z",
  "model": { "name": "claude-sonnet-4-6", "id": "claude-sonnet-4-6", "rubric_version": "1.0" },
  "evidence_level": "docs-only",
  "confidence": 0.78,
  "composite_score": 0.42,
  "headline": "Caution — overlapping filesystem write surfaces and uncoordinated git state.",
  "sub_verdicts": {
    "A_prompt_injection": {
      "severity": "low",
      "rationale": "Neither agent ingests the other's outputs by default; injection requires a user copying text manually.",
      "citations": [
        {"profile_field": "claude-code.io_surfaces.clipboard", "evidence_ref": "sha256:..."}
      ],
      "conditions": [],
      "mitigations": ["Disable shared-clipboard MCP servers when both are running."]
    },
    "B_data_leakage": {
      "severity": "medium",
      "rationale": "Both write into the working directory; Cursor uploads file contents to its inference backend by default.",
      "citations": [...],
      "conditions": ["Sensitive files in the working directory."],
      "mitigations": ["Set Cursor's privacy mode to 'on' for repos containing secrets."]
    },
    "C_capability_conflict": {
      "severity": "high",
      "rationale": "Both agents hold simultaneous filesystem write authority and modify git state without coordination, leading to lost edits.",
      "citations": [...],
      "conditions": [],
      "mitigations": [
        "Use one agent at a time per working directory.",
        "Configure pre-commit hook that locks the index when either agent is active."
      ]
    },
    "D_cascading_error": { "severity": "low", "rationale": "...", "citations": [...], "conditions": [], "mitigations": [...] },
    "E_compliance": { "severity": "low", "rationale": "...", "citations": [...], "conditions": [], "mitigations": [...] }
  },
  "framework_mappings": {
    "nist_ai_rmf": ["MEASURE-2.7", "MANAGE-2.3"],
    "iso_42001": ["A.7.4"]
  },
  "reproducibility": {
    "rubric_url": "/_meta/rubric/1.0.json",
    "profile_a_hash": "sha256:...",
    "profile_b_hash": "sha256:...",
    "evidence_bundle_hash": "sha256:..."
  },
  "sandbox_runs": []
}
```

### 7.3 Evidence (`_evidence/<sha>.json`)

```json
{
  "sha256": "abc123...",
  "source_url": "https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview",
  "fetched_at": "2026-05-02T02:11:00Z",
  "fetcher": "smadp-profiler",
  "media_type": "text/html",
  "quote": "Claude Code requests permission before writing files...",
  "context": "Section: Permissions",
  "fingerprint": "etag-or-content-hash"
}
```

### 7.4 Chronicle (`_chronicle/YYYY-MM-DD.jsonl`)

Append-only structured audit log; each line is one event:

```json
{"ts":"2026-05-02T03:14:00Z","event":"verdict.generated","verdict_id":"v_...","pair":["claude-code","cursor"],"model":"claude-sonnet-4-6","by":"smadp@host"}
```

Events: `profile.created`, `profile.refreshed`, `evidence.added`, `verdict.generated`, `verdict.regenerated`, `sandbox.run.started`, `sandbox.run.completed`, `schema.migrated`.

## 8. Composite scoring

Composite score is a deterministic roll-up of sub-verdict severities. Severity → numeric:

```
none=0.0  low=0.2  medium=0.5  high=0.8  critical=1.0
```

Score per pair (lower = safer):

```
composite = 0.30*B + 0.25*C + 0.20*D + 0.15*E + 0.10*A
```

B/C/D/E weighted higher per Q1 priorities. The composite is informational; sub-verdicts are authoritative.

## 9. Profiler design

**Pipeline:**
1. **Source fetch** — pull README, docs, ToS, source code structure (for open-source: GitHub API; for closed-source: targeted doc URLs).
2. **Evidence extraction** — chunk fetched content, hash chunks, store under `_evidence/<sha>.json` with source URL + quote.
3. **LLM extraction** — Claude Sonnet 4.6 with prompt caching: given the evidence bundle, output a Safety Profile JSON with `evidence_refs` populated.
4. **Schema validation** — Pydantic + JSON Schema rejects malformed output.
5. **Citation validation** — every populated field's `evidence_refs` must point to existing evidence. Quotes must appear verbatim in the source.
6. **Verification gate** — for seed catalog entries: `verification.status = "draft"` until human reviewer flips to `"verified"`. For user-submitted: stays `"unverified"`.

**Anti-hallucination rules:**
- The model is forbidden from filling fields without citation; an empty field is preferable.
- Citations must include the verbatim quote AND the source URL; both are re-fetched and re-checked at validation time.
- A profile fails validation if any citation's quote no longer appears at its source URL.

## 10. Pairwise Analyzer design

**Pipeline:**
1. **Bundle assembly** — load both profiles, dereference all evidence_refs, assemble a single context bundle.
2. **Rubric load** — `_meta/rubric/<version>.json` defines per-risk-category scoring criteria.
3. **LLM-judge** — single Claude call: given the bundle + rubric, produce a Verdict JSON with all 5 sub-verdicts, each with citations to specific profile fields.
4. **Schema + citation validation** — same as Profiler.
5. **Composite computation** — deterministic from sub-verdict severities (NOT model-output).
6. **Reproducibility hashing** — hash the inputs, store in `verdict.reproducibility`.

The LLM never computes the composite score; it only assigns severities. This keeps the score auditable and stable across regenerations of the same inputs.

## 11. Sandbox Validator — isolation model

**Threat model:** the sandbox MUST NOT be the source of the very leakage / capability-conflict / data-exfiltration risks SMADP is meant to detect. A leaky sandbox would be catastrophic.

**v1 isolation stack:**
- **Runtime:** rootless Podman + gVisor runtime (`runsc`) for syscall-level isolation. Falls back to Docker + gVisor if Podman unavailable.
- **Network:** `--network none` by default. Each scenario optionally allow-lists specific outbound endpoints (e.g., the agent's required inference API), enforced via egress proxy with audit log.
- **Filesystem:** read-only base image; tmpfs for working directory; no host mount.
- **Secrets:** scenario-scoped synthetic secrets only; real secrets rejected at scheduler level.
- **Process:** `--user nobody`, `--cap-drop ALL`, `--security-opt no-new-privileges`, seccomp profile = restrictive default.
- **Resource:** CPU + memory + PID + IO caps via cgroups v2. Wall-clock kill at 5min.
- **Lifetime:** ephemeral; container destroyed at scenario end. Transcripts persisted, container state not.
- **Observability:** all stdin/stdout/file-IO/network attempts captured via auditd-equivalent + container logs.

**v1 scope:** sandbox runs only for open-source pairs where both agents have an MCP-server adapter in `adapters/<slug>/mcp.json` (modeled on the ONEXUS-Agents adapter pattern). Closed-source pairs are not sandbox-validated in v1 (verdict stays `docs-only`). This is documented prominently in the dashboard.

**Queue:** SQLite-backed job queue (no external broker). `validator/queue.db` with `pending`, `running`, `completed`, `failed` states. One worker process per host; horizontal scale by adding hosts (each pulls from a shared catalog repo via git remote).

## 12. On-demand profile generation

**Flow:**
1. User submits agent via UI/CLI/API: provide name + at least one source URL (repo / docs / homepage).
2. Profiler runs the same pipeline as for seed catalog, but `verification.status = "unverified"`.
3. UI/CLI confirms with the user; user can edit fields before publishing.
4. Profile is committed to a separate `profiles/_unverified/` subdirectory; promoted to `profiles/` only when manually verified.
5. Verdicts can be requested against unverified profiles, but those verdicts carry an `evidence_level` of `unverified-profile` and a confidence penalty.

This is the growth lane toward the "anyone can submit anything" future state.

## 13. Repo layout

```
SMADP/
├── README.md
├── LICENSE                          # Apache-2.0
├── pyproject.toml
├── uv.lock
├── .gitignore
├── .ruff.toml
├── .pre-commit-config.yaml
├── .github/
│   ├── workflows/ci.yml             # ruff + pytest + schema validate
│   └── PULL_REQUEST_TEMPLATE/
│       ├── agent-submission.md
│       └── verdict-correction.md
├── catalog/
│   ├── profiles/                    # one JSON per agent
│   │   ├── claude-code.json
│   │   ├── cursor.json
│   │   ├── ...
│   │   └── _unverified/             # user-submitted, not yet promoted
│   ├── verdicts/                    # one JSON per pair
│   ├── _evidence/                   # content-addressed source snippets
│   ├── _meta/
│   │   ├── categories.json
│   │   ├── risk-taxonomy.json
│   │   ├── frameworks.json          # NIST AI RMF + ISO 42001 mappings
│   │   ├── rubric/1.0.json          # LLM-judge rubric
│   │   └── schema/1.0/              # JSON Schemas
│   └── _chronicle/                  # YYYY-MM-DD.jsonl audit log
├── smadp/                           # Python package
│   ├── __init__.py
│   ├── config.py
│   ├── cli.py                       # `smadp` command
│   ├── schemas/                     # Pydantic models
│   │   ├── profile.py
│   │   ├── verdict.py
│   │   ├── evidence.py
│   │   └── chronicle.py
│   ├── catalog/
│   │   ├── repo.py                  # git-backed catalog operations
│   │   ├── index.py                 # FTS index for search
│   │   └── chronicle.py             # event logger
│   ├── profiler/
│   │   ├── fetcher.py               # source fetchers (github, hf, html)
│   │   ├── extractor.py             # LLM-driven profile extraction
│   │   ├── citations.py             # citation validation
│   │   └── pipeline.py
│   ├── analyzer/
│   │   ├── bundle.py                # assemble profile + evidence bundles
│   │   ├── judge.py                 # LLM-judge invocation
│   │   ├── scoring.py               # deterministic composite score
│   │   └── pipeline.py
│   ├── sandbox/
│   │   ├── isolation.py             # container spec / runsc / podman
│   │   ├── runner.py                # scenario execution
│   │   ├── scenarios/               # YAML scenario definitions
│   │   ├── transcripts.py
│   │   └── queue.py                 # SQLite job queue
│   ├── api/
│   │   ├── server.py                # FastAPI app
│   │   ├── routes/
│   │   └── models.py                # Pydantic request/response
│   ├── llm/
│   │   ├── client.py                # Anthropic client w/ caching
│   │   └── prompts/                 # versioned prompt templates
│   └── utils/
│       ├── hashing.py
│       ├── slug.py
│       └── time.py
├── adapters/                        # MCP adapters for open-source agents
│   └── <slug>/mcp.json
├── site/                            # Astro + Tailwind dashboard
│   ├── astro.config.mjs
│   ├── tailwind.config.ts
│   ├── package.json
│   ├── src/
│   │   ├── pages/
│   │   │   ├── index.astro
│   │   │   ├── agents/index.astro
│   │   │   ├── agents/[slug].astro
│   │   │   ├── matrix.astro
│   │   │   ├── verdicts/[a]__[b].astro
│   │   │   ├── submit.astro
│   │   │   ├── methodology.astro
│   │   │   ├── frameworks.astro
│   │   │   ├── chronicle.astro
│   │   │   └── search.astro
│   │   ├── components/
│   │   ├── layouts/
│   │   ├── styles/
│   │   └── data/                    # catalog loader (build-time)
│   └── public/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── golden/                      # frozen profile + verdict examples
└── docs/
    ├── methodology.md
    ├── threat-model.md
    ├── evidence-policy.md
    ├── sandbox-isolation.md
    ├── risk-taxonomy.md
    ├── framework-mappings.md
    ├── contributing.md
    └── superpowers/specs/2026-05-02-smadp-design.md
```

## 14. Refresh cadence

- **Profile freshness check**: weekly. Re-fetch source URLs; if hashes change, mark profile `stale` and queue re-extraction.
- **Verdict regeneration**: triggered by either profile in the pair changing.
- **Sandbox runs**: continuous queue worker; manual + scheduled triggers.
- **Audit**: every mutation to the catalog produces a git commit AND a `_chronicle/` event.

## 15. Public dashboard pages (v1)

Multi-page Astro + Tailwind v4 static site, dark theme matching NEXUS aesthetic.

| Page | Route | Purpose |
|------|-------|---------|
| Home | `/` | Hero, value prop, "view the matrix", recent verdicts ticker |
| Agents browse | `/agents` | Filterable grid of all profiles by category, source-type, verification |
| Agent detail | `/agents/[slug]` | Full Safety Profile rendered, citation tooltips, all verdicts involving this agent |
| Compatibility matrix | `/matrix` | NxN grid w/ traffic-light cells; click to drill into verdict |
| Verdict detail | `/verdicts/[a]__[b]` | Full Verdict rendered: per-risk sub-verdicts, severity bars, conditions, mitigations, citations, sandbox transcripts (if any), reproducibility hashes |
| Submit | `/submit` | Form to submit an agent for profiling OR submit a list to evaluate |
| Methodology | `/methodology` | Full methodology, rubric, scoring formula, evidence policy |
| Frameworks | `/frameworks` | NIST AI RMF + ISO 42001 mappings; filter verdicts by framework control |
| Chronicle | `/chronicle` | Live audit log view |
| Search | `/search?q=` | Full-text search across profiles and verdicts |
| Risk taxonomy | `/risks` | Detailed explanation of the 5 risk categories with examples |

**Aesthetic anchors (matching NEXUS / ONEXUS-Agents):** dark theme, monospace accents, neon-on-dark for severity bars (green/amber/red), glow effects on CTAs, large readable typography, generous whitespace. Site is fully static; rebuilds nightly on catalog changes.

## 16. CLI surface

```
smadp profile <agent-slug-or-url>          # generate or refresh a profile
smadp verdict <slug-a> <slug-b>            # generate or fetch a verdict
smadp validate                             # schema + citation check entire catalog
smadp submit <url>                         # submit an agent for unverified profiling
smadp evaluate <slug-a> <slug-b> [...]     # evaluate a list of agents (verdicts for all pairs)
smadp serve [--port 8000]                  # start REST API
smadp sandbox run <pair>                   # queue a sandbox run
smadp sandbox status                       # show queue state
smadp chronicle [--tail]                   # view audit log
smadp lint                                 # check repo conventions
```

## 17. REST API surface

```
GET    /api/agents                         # list profiles (filter by category, source-type, status)
GET    /api/agents/{slug}                  # single profile
GET    /api/verdicts                       # list verdicts (filter by risk, severity, evidence-level)
GET    /api/verdicts/{a}/{b}               # single verdict
POST   /api/agents                         # submit new agent (auth-gated in v1; open later)
POST   /api/evaluate                       # body: list of slugs/urls; returns verdict bundle
GET    /api/search?q=                      # FTS search
GET    /api/frameworks                     # list framework mappings
GET    /api/chronicle                      # audit log entries
WS     /api/sandbox/runs/{run_id}          # stream sandbox progress
GET    /api/health
```

## 18. Testing strategy

- **Unit tests** — every module in `smadp/` has unit tests targeting individual functions.
- **Schema golden-file tests** — frozen example profiles + verdicts in `tests/golden/`; CI fails if schema or scoring changes break them silently.
- **Citation validation tests** — fetch a known-good profile, verify all citations resolve and quotes appear at source URLs (mocked for offline CI; live job nightly).
- **Composite-score determinism** — given fixed sub-verdicts, composite score is reproducible to 3 decimal places.
- **Sandbox isolation tests** — synthetic "rogue" agent that attempts network egress, filesystem escape, fork bomb; sandbox MUST contain.
- **CLI smoke tests** — every CLI subcommand runs end-to-end on a tiny test catalog.
- **Site build test** — Astro builds without errors on the seed catalog.
- **CI** — GitHub Actions on PR: ruff, pytest, schema validation, site build.

## 19. Out of scope for v1

- Live user-facing Lab UI (queue & verdict-only in v1)
- Capability adapters for closed-source agents (path B from Q6)
- Multi-agent chains of 3+ agents (pairwise only)
- Federation between SMADP instances
- Authentication / accounts (v1 is a public read-mostly platform; submission is open but rate-limited)
- Paid tier / SaaS hosting (v1 is open-source self-host + free hosted dashboard)

## 20. Stretch / nice-to-have within v1

- Slack-style notifications for verdict regenerations on subscribed pairs
- "Compatibility set" UX: paste a list of agents → get the full pairwise matrix as one report
- Diff view between two versions of a verdict (when re-generated)
- PDF export for verdict pages (B-audience compliance reports)

## 21. Open questions / risks

- **Closed-source profile staleness**: vendor docs change frequently. Weekly re-fetch may not be enough; need stronger drift detection.
- **Citation quote brittleness**: vendors edit docs without changing URLs. Verbatim-quote validation will produce false negatives. Mitigation: store full evidence snapshots; treat quote-mismatch as `stale`, not `invalid`.
- **LLM-judge variance**: same input, different output across runs. Mitigation: temperature=0, prompt cache, hash inputs; if hash matches, return cached verdict.
- **Sandbox supply-chain risk**: an MCP adapter pulling a malicious image could compromise the sandbox host. Mitigation: pinned image digests, image signing, host-level eBPF monitoring.
