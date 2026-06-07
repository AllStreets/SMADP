# Design: V3+ Every-Agent Page Quality Parity (DEFERRED)

**Date:** 2026-06-07
**Status:** Vision spec — explicitly v3 or later, written now to preserve context
**Spec ID:** `2026-06-07-v3-every-agent-page-quality-design`

## North Star

Every one of the 6,030+ catalog agent pages reaches the visual + factual density of the hand-curated claude-code page, without manual curation per agent. The catalog stays useful at scale, evidence remains cited, no field is fabricated.

## Why v3 (and not now)

The user's explicit decision on 2026-06-07: **keep the current claude-code page quality for v1, ship the lesser-quality LLM-enriched pages as v2-tier "showing catalog depth", and only invest in v3-quality once the autopilot loop is autonomous and the long-tail catalog is fully enriched.** The site already renders all tiers defensively (`f807bb6`); the gap is data depth, not display.

## Five concrete workstreams

### 1. Multi-source enrichment harness (~1 week)

Today's enricher feeds the LLM only the GitHub README. The README is marketing-flavored; technical claims are incomplete. Expand the evidence bundle:

- **Docs site fetch.** If the README links to a docs URL (gptr.dev, aider.chat, etc.), pull the top-level page + 2–3 deep links, chunk, hash, include as evidence.
- **Manifest files.** Pull `pyproject.toml`, `package.json`, `go.mod`, `Cargo.toml` (whichever matches the detected language). These declare dependencies and entry points — capabilities the README may have missed.
- **LICENSE file.** Authoritative for the `license` field, vs README-claimed which is often outdated.
- **ToS / privacy policy.** If the homepage has one, fetch it. Matters for the data-leakage risk dimension.

Each source is a separate `Source` (per the existing pipeline ABCs). The bundle merges them, dedupes by SHA, caps at ~40K total characters before sending to the LLM.

**Cost:** ~$0.10/agent (more evidence = larger prompt). 6,030 × $0.10 = ~$603, one-time. With existing $20/day cap, that's ~30 days of grinding for the long tail.

### 2. Static-analysis judge per language (~2-3 weeks per language)

Capabilities should be grounded in code, not docs. For each supported language, build a judge that reads the cloned repo and infers capabilities deterministically:

**Python:**
- `subprocess.Popen` / `subprocess.run` / `os.system` → `execute_shell: true`
- `open(..., 'w')` / `pathlib.Path.write_*` → `write_filesystem: true`
- `httpx.*` / `requests.*` / `aiohttp.*` → `network_egress: broad` if no allowlist visible
- `git` imports / `gitpython` → `modify_git_state: true`
- `pip` / `subprocess install` → `install_packages: true`
- `playwright` / `selenium` → `run_browsers: true`
- MCP server registration → `use_mcp: true`

**Node:**
- `child_process.exec` → execute_shell
- `fs.write*` → write_filesystem
- `fetch` / `axios` / `node-fetch` → network_egress
- `puppeteer` / `playwright` → run_browsers

**Go / Rust:** equivalent pattern matching against stdlib + popular libraries.

**Why this matters:** today the docs-only judge says `execute_shell: true` because the README says "Aider runs commands." A static-analysis judge sees the actual `subprocess.run` call and stakes a verifiable claim. Verdict tier promotes from `docs-only` to `profile-verified`.

### 3. Adapter scaffolder + sandbox runs

Already specced separately at `docs/superpowers/specs/2026-06-07-adapter-scaffolder-design.md`. The output is `sandbox-validated` evidence — the project's actual differentiator. Without this, every claim remains LLM-inferred; with this, every claim has a transcript to prove it.

### 4. Completion-judge audit pass (~1 day)

A small LLM judge that examines an enriched profile, identifies missing fields (`vendor.handle == None`, `io_surfaces == {}`, `data_classes_touched == []`), and re-prompts gpt-5.4-mini specifically for those gaps using the cached README evidence:

```python
class CompletionJudge:
    def evaluate(self, profile: dict) -> dict:
        gaps = self._identify_gaps(profile)
        if not gaps:
            return profile
        evidence = self._fetch_cached_readme(profile)
        patch = self._llm_fill(gaps, evidence, model="gpt-5.4-mini")
        return {**profile, **patch}
```

Cost: ~$0.02/agent × ~150 partials = $3. Closes ~80% of "this page looks thin" complaints from existing enriched profiles.

### 5. Schema-driven rendering with "awaiting enrichment" affordances (~half-day)

Today `agents/[slug].astro` silently shows "—" for missing fields. Better: visible "this section awaiting enrichment" badge so users understand the catalog's state. Aligns with the "honest evidence tier" goal.

Two small UI components:
- `<AwaitingEnrichmentBadge field="vendor.handle" />` — small inline label
- `<AwaitingEnrichmentSection label="IO surfaces" />` — full section placeholder

Render only when the field/section is null/empty AND the profile's tier suggests it should be filled.

## Long-term operational goals (the user stated 2026-06-07)

These constraints apply to the whole pipeline, not just v3:

- **Fully autonomous research.** Once the loop is wired, the user shouldn't have to drive day-to-day. Bootstrap → enrich → pair-judge → adapter scaffold → sandbox-run all happen on cron.
- **Cost-effective throughout.** Daily soft cap stays $20; soft autopilot pauses gracefully when reached; resumes next day. No surprise bills.
- **Conversational ONEXUS sync.** Periodically poll the ONEXUS-Agents repo for catalog updates and incorporate new agents automatically. Possibly via webhook or a daily git fetch.
- **Never delete research.** Every verdict, every enrichment, every sandbox transcript stays on disk forever. Pagination is the answer to scale, not deletion.
- **Pagination across the site.** As the catalog grows past 50,000 verdicts, `/verdicts/` and `/agents/` list pages need to paginate or lazy-load. Astro static generation can handle pagination via `getStaticPaths` — each page renders 100 items.

## Sequencing under v3

Real-world order (assuming current state is the v2 baseline):

1. **Tier-aware catalog lint** (the deferred spec at `2026-06-07-tier-aware-catalog-lint-design.md`) — must come first so the schema supports the tier flow.
2. Completion-judge audit pass (cheap, fast, high visual impact).
3. Schema-driven "awaiting enrichment" affordances.
4. Multi-source enrichment harness.
5. Static-analysis judge for Python (highest agent count).
6. Adapter scaffolder + sandbox smoke (the deferred spec at `2026-06-07-adapter-scaffolder-design.md`).
7. Static-analysis judges for Node, Go, Rust.
8. Pagination across the site (when verdict count crosses ~5K).

Each item is its own brainstorm → spec → plan → implement cycle.

## Acceptance for v3

- Median agent page has: vendor.handle populated, at least 3 capabilities set, at least 3 data classes touched, sandboxing block populated, evidence_refs ≥ 5, at least one sandbox-validated verdict involving the agent.
- 95% of catalog profiles reach `docs-only` tier or higher.
- At least 100 agents reach `sandbox-validated` tier.
- Site builds in <60s with 50,000+ pages via incremental + paginated generation.
- launchd loop runs continuously without operator intervention for 30+ days.

## Out of scope (truly later)

- Closed-source agent shims (Cursor, GH Copilot, Claude Code APIs)
- GUI / browser agent sandboxing (ComfyUI, browser-use, screen-capture-needing agents)
- Cross-machine catalog replication / shared registry
- Auto-PR back to ONEXUS-Agents with safety findings
- Public hosting (deploy to Cloudflare Pages / Vercel — separate decision)
