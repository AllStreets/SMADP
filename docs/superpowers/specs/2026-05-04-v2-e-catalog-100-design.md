# SMADP v2-E — Catalog Expansion to 100 Agents (+ Pairings + 3+-Agent Chains)

**Status:** Approved — A/B/B forks confirmed by user 2026-05-04. Eventual goal: all 70 net-new profiles reach `verified` status, in batches.

## Goal

Grow the SMADP catalog from 31 verified agent profiles to 100 (31 verified + 69 newly-added unverified seeds), introduce a structural `pairings` field on `Profile`, and add a new first-class `Chain` artifact for 3+-agent compositions. Wire the new data into the site so users can browse pairings and explore chain analyses.

## Non-Goals

- Authoring evidence files for the 69 new profiles (deferred — they ship as `unverified` and graduate via separate evidence-gather batches, tracked in v2-E follow-ups).
- Re-running the LLM judge to produce new pairwise verdicts for the new profiles (deferred — the existing 25 pairwise verdicts remain unchanged).
- Computing `composite_score` or framework-mapping logic for chains (deferred — chain fixtures are hand-authored seeds; analyzer support comes later).
- Changing the verdict schema or the pairwise judging pipeline. Chains are a separate artifact type.

## Design Decisions (already locked)

1. **Pairings live on the profile** as a new optional `pairings: string[]` field. Profile schema goes 1.0 → 1.1; pydantic model gains an optional field; existing 31 profiles get backfilled with their declared pairings.
2. **Chains are a new artifact** under `catalog/chains/<chain_id>.json` with their own JSON Schema, Pydantic model, and repo loader. Pairwise verdict invariants stay clean.
3. **Bulk additions ship as unverified** under the existing `catalog/profiles/_unverified/` directory (already wired into lint, repo, CLI). `verification.status: "unverified"`, `evidence_refs: []`, `verification.method: "auto-only"`.

## Architecture

### Profile schema 1.0 → 1.1

A backwards-compatible minor bump:

```diff
- "schema_version": {"const": "1.0"}
+ "schema_version": {"enum": ["1.0", "1.1"]}
+ "pairings": {
+   "type": "array",
+   "items": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]{1,63}$"},
+   "uniqueItems": true,
+   "maxItems": 20
+ }
```

`pairings` is optional. Existing 1.0 files load unchanged. New writes pin `schema_version: "1.1"`. Pydantic gains:

```python
class Profile(BaseModel):
    schema_version: Literal["1.0", "1.1"] = "1.1"
    ...
    pairings: list[str] = Field(default_factory=list, max_length=20)
```

Lint adds a cross-reference check: every `pairings` slug must exist as a profile (verified or unverified).

### Chain artifact

New JSON Schema at `catalog/_meta/schema/1.0/chain.schema.json`:

```json
{
  "$id": "https://smadp.dev/schema/1.0/chain.schema.json",
  "title": "SMADP Multi-Agent Chain",
  "type": "object",
  "required": ["schema_version", "chain_id", "name", "topology",
               "participants", "edges", "headline", "sub_verdicts",
               "framework_mappings", "first_seen_at", "last_refreshed_at"],
  "additionalProperties": false,
  "properties": {
    "schema_version": {"const": "1.0"},
    "chain_id": {"type": "string", "pattern": "^c_[a-z0-9-]{3,80}$"},
    "name": {"type": "string", "minLength": 1, "maxLength": 120},
    "tagline": {"type": "string", "maxLength": 240},
    "topology": {"enum": ["linear", "star", "loop", "tree", "dag"]},
    "participants": {
      "type": "array",
      "items": {"type": "object", "required": ["slug", "role"],
                "additionalProperties": false,
                "properties": {
                  "slug": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]{1,63}$"},
                  "role": {"enum": ["planner", "executor", "critic",
                                    "retriever", "reasoner", "writer",
                                    "router", "tool", "judge", "memory"]},
                  "notes": {"type": "string", "maxLength": 240}
                }},
      "minItems": 3, "maxItems": 8
    },
    "edges": {
      "type": "array",
      "items": {"type": "object", "required": ["from", "to", "channel"],
                "additionalProperties": false,
                "properties": {
                  "from": {"type": "string"},
                  "to": {"type": "string"},
                  "channel": {"enum": ["prompt", "tool-call", "shared-memory",
                                       "filesystem", "message-bus"]},
                  "carries": {"type": "array", "items": {"type": "string"}}
                }}
    },
    "headline": {"type": "string", "minLength": 1, "maxLength": 240},
    "sub_verdicts": { /* same A-E shape as verdict.schema.json — reused via $ref-style copy */ },
    "framework_mappings": {
      "type": "object",
      "additionalProperties": {"type": "array", "items": {"type": "string"}}
    },
    "evidence_refs": {"type": "array", "items": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}},
    "first_seen_at": {"type": "string", "format": "date-time"},
    "last_refreshed_at": {"type": "string", "format": "date-time"}
  }
}
```

Pydantic mirror at `smadp/schemas/chain.py`. Repo loader `CatalogRepo.list_chains()` / `load_chain(chain_id)`. Lint adds a `chain.cross-ref` check: every participant slug must exist as a profile; every `edges.from`/`edges.to` must reference a participant slug.

### Profile generation strategy

The 69 net-new profiles are generated from a small **ontology** kept in `scripts/v2_e/ontology.py`:

- A list of vendor/product seeds (name, slug, vendor, source_type, category, homepage, repo_url, brief tagline).
- Per-category default capability presets (e.g. category `browser-automation` → `run_browsers: true, network_egress: "broad"`; category `image-generation` → `network_egress: "vendor-only"`).
- Per-category default sandboxing/concurrency narrative strings.

`scripts/v2_e/generate_profiles.py` reads the ontology, fills in defaults, and writes one JSON file per seed under `catalog/profiles/_unverified/`. Output is deterministic and lint-clean. Re-running the script is idempotent (skip if file exists, unless `--force`).

This is the right tradeoff vs. pure LLM generation: deterministic, reviewable in PR diff, no hallucinated capabilities, easy to backfill the same fields with real evidence later.

### Pairings backfill

`scripts/v2_e/backfill_pairings.py` reads `pairings_table.py` (a hand-authored `dict[slug, list[slug]]` covering all 100 profiles) and writes the `pairings` field into each profile JSON in place. Idempotent. Bidirectional consistency is enforced by lint: if `A.pairings` includes `B`, then `B.pairings` must include `A`.

### Chain fixtures

Six canonical chains, hand-authored under `catalog/chains/`:

1. `c_research-write-cite` (linear) — perplexity → claude-code → claude-code (writer pass with citations check)
2. `c_planner-executor-critic` (linear) — claude-code (planner) → openhands (executor) → swe-agent (critic)
3. `c_rag-reason-tool` (linear) — khoj (retriever) → claude-code (reasoner) → cursor (tool)
4. `c_browser-extractor-summarizer` (linear) — replit-agent → claude-code → notion-ai
5. `c_orchestrator-fanout-merge` (star) — autogen (router) → claude-code + cursor + aider → autogen (judge)
6. `c_loop-debug-fix-test` (loop) — claude-code (planner) → cline (executor) → claude-code (critic) — loops until tests pass

Each comes with hand-written sub_verdicts in the A–E shape.

### Site changes

- `/agents` (existing, lightweight) — add filter chips by `verification.status` (verified / unverified) and category. Show `pairings` count badge per card.
- `/agents/[slug]` (existing) — render a "Commonly paired with" section as chips that link to the paired agent's page.
- **NEW** `/chains` index — table of all chains: name, topology, participant chips, headline, severity bar.
- **NEW** `/chains/[id]` deep view — topology diagram (inline SVG, simple node+edge layout), participant role badges, sub_verdict accordion, framework crosswalk. Mirrors the structure of the existing verdict deep view.
- Nav: add `Chains` to the **Catalog** dropdown alongside Agents/Matrix/Verdicts/Risks.

### Verification roadmap (batched, post-ship)

After v2-E lands, the 69 unverified profiles graduate in batches:
- **Batch V1** — verify ~20 profiles in the most-used categories (coding, search-rag, browser-automation, devops-sre).
- **Batch V2** — verify ~25 profiles in the next tier.
- **Batch V3** — verify the remaining ~24, plus retrofit `evidence_refs` on chains.

Each batch is its own plan cycle; v2-E itself only delivers the schema + bulk seeds + chains.

## Tests

- `tests/schemas/test_profile_pairings.py` — round-trip with/without pairings, schema 1.1 vs 1.0.
- `tests/schemas/test_chain_schema.py` — valid + invalid topology fixtures.
- `tests/catalog/test_lint_pairings_xref.py` — orphan and asymmetric pairings raise errors.
- `tests/catalog/test_chain_repo.py` — list/load/save round-trip.
- `tests/scripts/test_generate_profiles.py` — generator output is deterministic and lint-clean (uses tmp dir).
- `site/tests/e2e/smoke.spec.ts` — extend to cover `/chains` index loads and `/chains/[id]` renders without errors.

## Files Changed Summary (preview — plan will be exact)

- `catalog/_meta/schema/1.0/profile.schema.json` — bump version enum, add `pairings`.
- `catalog/_meta/schema/1.0/chain.schema.json` — NEW.
- `smadp/schemas/profile.py` — add `pairings`, broaden `schema_version`.
- `smadp/schemas/chain.py` — NEW.
- `smadp/schemas/__init__.py` — export `Chain`.
- `smadp/catalog/repo.py` — chain CRUD methods.
- `smadp/catalog/lint.py` — pairings cross-ref + chain validation.
- `smadp/config.py` — add `chains_dir` property.
- `scripts/v2_e/ontology.py`, `scripts/v2_e/generate_profiles.py`, `scripts/v2_e/pairings_table.py`, `scripts/v2_e/backfill_pairings.py` — NEW.
- `catalog/profiles/_unverified/*.json` — 69 new files.
- `catalog/profiles/*.json` — 31 existing files patched in place with `pairings`.
- `catalog/chains/*.json` — 6 new files.
- `site/src/lib/chains.ts` — NEW: typed fetch + chain types.
- `site/src/pages/chains.astro`, `site/src/pages/chains/[id].astro` — NEW.
- `site/src/pages/agents/[slug].astro` — render pairings.
- `site/src/components/Nav.astro` — add Chains to Catalog group.
- Tests above.

## Out of scope / explicitly deferred

- Pairwise verdicts for any of the 69 new profiles (separate batches).
- Evidence file authoring for new profiles (separate verification batches V1/V2/V3).
- Chain composite-score computation, severity rollup, framework-coverage analyzer integration.
- LLM-driven pairings suggestion. Pairings table is hand-authored in v2-E.
- Auto-generated topology diagram beyond a simple SVG renderer (advanced graph layout deferred).
