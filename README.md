<p align="center">
  <img src="https://img.shields.io/badge/SMADP-v0.2.0-7C3AED?style=for-the-badge" alt="Version"/>&nbsp;<img src="https://img.shields.io/badge/Python-3.11+-yellow?style=for-the-badge&logo=python&logoColor=white" alt="Python"/>&nbsp;<img src="https://img.shields.io/badge/agents-100-A78BFA?style=for-the-badge" alt="Agents"/>&nbsp;<img src="https://img.shields.io/badge/verdicts-104-A78BFA?style=for-the-badge" alt="Verdicts"/>&nbsp;<img src="https://img.shields.io/badge/chains-6-A78BFA?style=for-the-badge" alt="Chains"/>&nbsp;<img src="https://img.shields.io/badge/License-Apache_2.0-22C55E?style=for-the-badge" alt="License"/>&nbsp;<img src="https://img.shields.io/badge/status-alpha-EA580C?style=for-the-badge" alt="Status"/>
</p>

<p align="center">
  <a href="https://allstreets.github.io/SMADP/">
    <img src="https://readme-typing-svg.demolab.com?font=JetBrains+Mono&weight=700&size=64&duration=1&pause=99999&color=7C3AED&center=true&vCenter=true&width=900&height=100&lines=S+M+A+D+P" alt="SMADP"/>
  </a>
</p>
<p align="center"><strong>Safe Multi-Agent Deployment Platform</strong></p>
<p align="center"><em>Auditable, evidence-cited verdicts on whether AI agents can safely run together.</em></p>

---

## What this is

You install Claude Code, then Cursor, then a calendar agent, then a notes agent, then an email-drafter. They share your filesystem, your clipboard, your OAuth scopes, your MCP servers. Nobody has systematically studied what happens when they interact — and the casual composition is becoming dangerous.

**SMADP publishes the matrix.** For every popular agent (the 30-strong verified seed catalog plus 70 unverified seeds across coding, search/RAG, browser automation, devops, orchestration, image/video/audio generation, productivity SaaS, OS-level assistants, and more — see [`catalog/profiles/`](catalog/profiles/)), we publish:

- a **safety profile** (capabilities, IO surfaces, network egress, OAuth scopes, sandboxing model)
- a **pairwise verdict** for every two agents that share a runtime — can they run together, and if not, why not?
- a **commonly-paired-with** list per agent, surfaced on the agent page
- **multi-agent chain analyses** — six canonical 3+-agent compositions (linear / star / loop topologies) with their own A–E sub-verdicts
- and now, an in-browser **Chain Builder** at `/chains/new` that composes a draft from any subset of the 100 agents, recomputes the A–E sub-verdicts client-side as you edit, and (optionally) publishes the chain to the catalog through the `POST /api/chains` endpoint

Every verdict is:

- **evidence-cited** — every claim points to a verbatim quote from the agent's docs, source, or ToS, with the source URL preserved
- **risk-typed** — five risk categories evaluated independently (prompt injection, data leakage, capability conflicts, cascading errors, compliance)
- **severity-tiered** — `none` / `low` / `medium` / `high` / `critical` per risk
- **conditional** — "safe IF you scope OAuth like X" rather than vague binary verdicts
- **mitigated** — every flagged risk includes concrete steps to make the pair safe
- **reproducible** — verdict carries the model version, rubric version, and content hashes
- **layered** — `evidence_level` field tells you whether this is `docs-only`, `profile-verified`, or `sandbox-validated`

The product is the catalog of profiles, verdicts, and chains. The dashboard, API, and CLI are surfaces on top of it.

### Catalog at a glance

| Artifact | Count | Location |
|----------|-------|----------|
| Verified safety profiles | 30 | `catalog/profiles/*.json` |
| Unverified seeds (auto-generated, awaiting evidence) | 70 | `catalog/profiles/_unverified/*.json` |
| Pairwise verdicts | 104 | `catalog/verdicts/*.json` |
| Multi-agent chain analyses | 6 | `catalog/chains/c_*.json` |
| Evidence snippets | 79 | `catalog/_evidence/sha256-*.json` |

---

## Quickstart

```bash
# Clone
git clone https://github.com/AllStreets/SMADP.git
cd SMADP

# Install
pip install -e ".[dev]"

# Lint the catalog (works offline against the seed data — checks profile schema 1.1,
# pairings cross-references + symmetry, chain participant/edge resolution)
smadp lint
# → profiles=100  verdicts=104  evidence=79   all checks passed.

# Generate a verdict for a pair
smadp verdict claude-code cursor

# Validate every chain analysis
smadp validate

# Submit a new agent for unverified profiling
smadp submit https://github.com/some-org/some-agent

# Start the local dashboard + API
smadp serve
```

The site (`cd site && pnpm install && pnpm dev`) renders five catalog views: **Agents** (100 profiles, filterable by category and verification status), **Chains** (the 6 canonical compositions plus the in-browser Chain Builder at `/chains/new`), **Risk Atlas** (10 inline-SVG charts over all 104 verdicts — pair × risk grid, severity distribution, co-occurrence matrix, scatter, evidence-layer breakdown, vendor leaderboard, top-10 most-fraught pairs, agent risk profile, per-risk top pairs, composite histogram), **Verdicts** (pairwise judgements), and **Frameworks** (NIST AI RMF + ISO 42001 mappings). Each agent page links out to *commonly paired with* siblings via the new `pairings` field on `Profile`.

---

## Risk taxonomy

| ID | Risk | Quick example |
|----|------|---------------|
| **A** | Prompt injection between agents | Email-drafter returns text that the note-taker ingests as a command |
| **B** | Data leakage / scope violations | Spreadsheet agent reads HR data; PowerPoint agent then exports a slide containing it |
| **C** | Capability / permission conflicts | Both agents authorized over the same Gmail account; one's writes break the other's assumptions |
| **D** | Cascading errors / hallucination amplification | Agent A confidently emits wrong fact; Agent B treats it as ground truth and compounds the error |
| **E** | Compliance / policy violations from composition | Each agent fine alone, but the combination violates GDPR / HIPAA / org policy |

B/C/D/E are weighted higher in the composite score; A is always evaluated.

---

## How verdicts are produced

Three layers of evidence, each with its own audit trail. Verdicts are tagged with `evidence_level` so readers know which layer(s) supported them.

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

1. **Static profile (always)** — a structured Safety Profile per agent: capabilities, IO surfaces, network egress, OAuth scopes, data classes, sandboxing model. Hand-verified for the seed catalog; auto-generated and flagged `unverified` for user-submitted agents.

2. **LLM-judge over profiles + cited evidence (always)** — `gpt-5.4-mini` reasons over both profiles and the evidence bundle to produce per-risk sub-verdicts. Every claim cites a profile field and an evidence ID; every evidence ID is a content-addressed snippet of source material with the source URL preserved.

3. **Sandbox validation (open-source pairs only, v1)** — for open-source pairs with MCP adapters, both agents are run in an airtight container (rootless Podman + gVisor `runsc`, `--network none`, ephemeral tmpfs, `cap-drop ALL`) through scenario tasks. Observed behavior either confirms or contradicts the LLM-judge's verdict; the verdict is updated and `evidence_level` is promoted to `sandbox-validated`.

**Closed-source agents stay at `docs-only` in v1.** This is intentional — overclaiming kills credibility. Capability adapters for closed-source agents (driving CLI binaries in a container, etc.) are on the v2 roadmap.

---

## Sandbox quickstart

Produce real `evidence_level: sandbox-validated` verdicts on a developer
laptop in three steps.

**Prerequisites:** Docker (or rootless Podman) on PATH; an OpenAI API key
(both the verdict judge and the in-sandbox adapters default to
`gpt-5.4-mini`).

1. **Bring your own key.** Create `~/.smadp/keys.env` with mode 600:
   ```
   OPENAI_API_KEY=sk-...
   ```
   Only `OPENAI_API_KEY` is in the hardcoded allowlist; anything else is
   dropped before any container starts.

2. **Pin image digests** (one-time; re-run when bumping adapter versions):
   ```
   smadp sandbox pin-images --adapter aider --adapter synthetic-adapter
   ```
   This pulls each adapter image, extracts its sha256 digest, and writes it
   to `smadp/sandbox/approved_images.json` and `adapters/<slug>/mcp.json`.

   > **Note (current state, 2026-05-05):** of the four agents in the seed
   > catalog, only `aider` ships as a public container image
   > (`paulgauthier/aider:latest`). `autogen`, `continue-dev`, and
   > `open-interpreter` are libraries/desktop apps with no canonical image,
   > so the smoke set pairs `aider` with `synthetic-adapter` (a tiny
   > alpine-based no-key adapter) until we publish purpose-built containers
   > for those three.

3. **Run the smoke set:**
   ```
   make sandbox-smoke
   ```
   Enqueues three pairings (`aider × synthetic-adapter` on calendar_email,
   notes_email, spreadsheet_powerpoint) and drains the queue. Each
   successful run promotes the verdict to `evidence_level:
   sandbox-validated` and appends a `sandbox.run.completed` entry to
   today's chronicle file.

Inspect results:
```
smadp sandbox runs
smadp chronicle --since 2026-05-04
```

Under the hood: a single-process worker (`smadp sandbox work`) atomically
claims pending runs from a SQLite-backed queue, runs the pair through the
existing rootless-container runner, and feeds the transcript hash into the
promotion module. Policy gates (image-digest allowlist, key allowlist,
egress-allowlist enforcement, transcript secret-redaction) sit on every
boundary.

---

## Catalog format

The catalog is a git repository. The git history *is* the audit log.

```
catalog/
├── profiles/                    # one JSON per agent (schema 1.0 or 1.1)
│   ├── claude-code.json         # 30 verified profiles at top level
│   ├── cursor.json
│   ├── chatgpt-desktop.json
│   ├── perplexity.json
│   ├── ...
│   └── _unverified/             # 70 auto-generated seeds, awaiting evidence
├── verdicts/                    # one JSON per alphabetized pair
│   ├── claude-code__cursor.json
│   └── ...
├── chains/                      # 3+-agent compositions (NEW in v0.2)
│   ├── c_research-write-cite.json
│   ├── c_planner-executor-critic.json
│   ├── c_rag-reason-tool.json
│   ├── c_browser-extractor-summarizer.json
│   ├── c_orchestrator-fanout-merge.json
│   └── c_loop-debug-fix-test.json
├── _evidence/                   # content-addressed source snippets
│   └── sha256-<hash>.json
├── _meta/
│   ├── categories.json
│   ├── risk-taxonomy.json
│   ├── frameworks.json          # NIST AI RMF + ISO 42001 mappings
│   ├── rubric/1.0.json          # LLM-judge rubric
│   └── schema/1.0/              # JSON Schemas — profile.schema.json (1.0/1.1),
│                                #               verdict.schema.json,
│                                #               chain.schema.json (NEW)
└── _chronicle/                  # YYYY-MM-DD.jsonl audit log
```

### Profile schema 1.1 — pairings field

Profile schema **1.1** is a backwards-compatible bump of 1.0 that adds an optional `pairings: string[]` field listing slugs an agent is commonly composed with. Existing 1.0 files continue to load. New writes pin `schema_version: "1.1"`. Lint enforces:

- every `pairings` slug must resolve to a profile (`profile.pairings-xref`)
- if `A.pairings` includes `B`, then `B.pairings` must include `A` (`profile.pairings-symmetric`)
- a profile may not list its own slug (`profile.pairings-self`)
- max 20 entries per profile

### Multi-agent chains (NEW)

A **Chain** is a first-class artifact for compositions of 3 or more agents. Each chain JSON declares its `topology` (`linear` / `star` / `loop` / `tree` / `dag`), 3–8 `participants` (with roles drawn from `planner` / `executor` / `critic` / `retriever` / `reasoner` / `writer` / `router` / `tool` / `judge` / `memory`), the `edges` between them (with `channel`: `prompt` / `tool-call` / `shared-memory` / `filesystem` / `message-bus`), and a full A–E sub-verdict block — same shape as pairwise verdicts but evaluating composition-specific risks (cascading injection, distributed data leakage, role-conflict, error amplification across hops, layered compliance).

Lint enforces that every participant slug resolves to a profile, every edge endpoint resolves to a participant, and the file's basename matches the `chain_id`. The site renders chains at `/chains` (index) and `/chains/[id]` (deep view with inline-SVG topology + sub-verdict accordion).

**Chain Builder + REST API.** The `/chains/new` page is a client-side composer: pick 3–8 agents, choose a topology, draw the edges, and the same A–E heuristics that power the canonical 6 chains run live in the browser (`site/src/lib/chain-analyze.ts`). Drafts persist in `localStorage`, and `Submit to catalog` POSTs the chain through the FastAPI backend:

| Endpoint | Action |
|---|---|
| `GET /api/chains` | List all chains in the catalog |
| `GET /api/chains/{chain_id}` | Fetch a single chain |
| `POST /api/chains` | Create a chain (rate-limited; emits a `chain.created` chronicle event) |
| `DELETE /api/chains/{chain_id}` | Delete a chain (emits a `chain.deleted` chronicle event) |

Submitted chains are written to `catalog/chains/c_*.json`, surfaced on `/chains` under a "Just submitted" header, and become first-class catalog artifacts on the next site rebuild.

See [`docs/superpowers/specs/2026-05-02-smadp-design.md`](docs/superpowers/specs/2026-05-02-smadp-design.md) for the complete design.

---

## Verdict format

```json
{
  "schema_version": "1.0",
  "pair": ["claude-code", "cursor"],
  "verdict_id": "v_2026-05-02_claude-code__cursor_a3f1",
  "evidence_level": "docs-only",
  "confidence": 0.78,
  "composite_score": 0.42,
  "headline": "Caution — overlapping filesystem write surfaces and uncoordinated git state.",
  "sub_verdicts": {
    "A_prompt_injection": { "severity": "low", "rationale": "...", "citations": [...], "mitigations": [...] },
    "B_data_leakage": { "severity": "medium", "rationale": "...", "citations": [...], "mitigations": [...] },
    "C_capability_conflict": { "severity": "high", "rationale": "...", "citations": [...], "mitigations": [...] },
    "D_cascading_error": { "severity": "low", "rationale": "...", "citations": [...], "mitigations": [...] },
    "E_compliance": { "severity": "low", "rationale": "...", "citations": [...], "mitigations": [...] }
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
  }
}
```

---

## Composite score

Lower is safer. Severity → numeric: `none=0.0  low=0.2  medium=0.5  high=0.8  critical=1.0`.

```
composite = 0.30*B + 0.25*C + 0.20*D + 0.15*E + 0.10*A
```

Sub-verdicts are authoritative; the composite is informational and sortable.

---

## Submitting an agent

```bash
smadp submit https://github.com/your-org/your-agent
```

Or open a pull request:

1. Fork the repo
2. Add `catalog/profiles/<your-agent>.json` matching the schema in `_meta/schema/1.0/profile.schema.json`
3. Add evidence references for every populated field
4. Open a PR using the **Agent submission** template

CI runs `smadp lint` against your file. If schema and citation validation pass, an admin reviews and merges.

---

## Project layout

```
smadp/                Python package (Profiler, Analyzer, Sandbox, CLI, API,
                      schemas/profile, schemas/chain, catalog/repo, catalog/lint)
catalog/              The catalog itself (profiles, verdicts, chains, evidence,
                      chronicle, frameworks)
scripts/v2_e/         Bulk-seed tooling — ontology, profile generator,
                      pairings table, backfill, generate_verdicts.py (used to
                      land the 70 unverified profiles + symmetric pairings +
                      the 79 docs-only verdicts that brought verdict coverage
                      across all 100 agents)
adapters/             MCP adapters for sandbox-runnable open-source agents
site/                 Astro 4 + Tailwind v3 dashboard (Agents, Chains, Chain
                      Builder, Risk Atlas, Verdicts, Frameworks, Workspaces,
                      Chronicle, Submit)
tests/                Test suite (572 unit tests + 4 Playwright e2e smokes)
docs/                 Methodology, threat model, evidence policy, framework
                      mappings, design specs and implementation plans under
                      docs/superpowers/{specs,plans}
```

### Verification roadmap

The 70 unverified seeds graduate to `verified` in three batches, each its own plan cycle:

- **Batch V1** (~20) — most-used categories: coding, search/RAG, browser-automation, devops/SRE
- **Batch V2** (~25) — orchestration frameworks, image/video/audio generation, productivity SaaS
- **Batch V3** (~25) — long-tail categories + retrofitting `evidence_refs` on chains

Each batch authors evidence files, flips `verification.status` to `verified`, and bumps the `verified_by`/`last_refreshed_at` fields. The schema, lint, and site already accept verified-or-unverified profiles, so graduation is a metadata-only operation.

---

## Design principles

**Evidence-first.** No claim without a citation. No citation without a verbatim quote and a source URL. No verdict without reproducibility hashes. If we cannot prove a claim, we leave the field empty rather than guess.

**Honest evidence levels.** A `docs-only` verdict and a `sandbox-validated` verdict look different in the UI on purpose. Overclaiming is fatal for a security platform.

**Git as audit log.** The catalog is a git repository. Every mutation is a commit. Reverting is a `git revert`. There is no separate "audit database" to fall out of sync.

**Closed-source asymmetry is honest.** v1 cannot sandbox Claude Code or Cursor. We say so prominently. Capability adapters land in v2.

**Open by default, paid never.** v1 is open-source self-host + a free hosted dashboard. There is no SaaS upsell path. The catalog must always be redistributable.

**Sibling, not successor.** SMADP is a sibling to [NEXUS](https://github.com/AllStreets/ONEXUS) and [ONEXUS-Agents](https://github.com/AllStreets/ONEXUS-Agents). Same DNA — local-first, transparent scoring, immutable audit, JSON-as-source-of-truth — different mission.

---

## License

Apache-2.0. The catalog is publicly redistributable. Each profiled agent retains its upstream license — see the `vendor` field on every catalog entry.

---

<p align="center"><sub>Built by <a href="https://github.com/AllStreets">Connor Evans</a></sub></p>
