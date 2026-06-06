# Design: Profile Enrichment Pivot

**Date:** 2026-06-06
**Status:** Draft — supersedes parts of `2026-06-06-onexus-autonomous-loop-design.md`
**Spec ID:** `2026-06-06-profile-enrichment-pivot-design`

## Summary

The 5-pair smoke validation surfaced a real design gap: docs-only LLM verdicts emitted against sparse ONEXUS-derived profiles collapse to `composite_score: 0.0` and severity `"none"` across every dimension. Tag-based capability heuristics simply do not carry enough signal to drive useful pair-level judgments.

This spec replaces the prior plan's "judge all 4,950 pairs from the top-100 immediately" with a **profile-first** pipeline. We enrich every ONEXUS profile with a one-time GitHub-README-grounded LLM pass before any pair work runs, then gate pair-judging on profile quality. The sandbox path stays the project's true differentiator and gets first-class adapter scaffolding.

## What changes vs the prior spec

| Component | Prior spec | This spec |
| --- | --- | --- |
| Source / Profiler / Planner / Publisher / WorkItem queue | New (built) | **Kept** — code in `smadp/autopilot/` survives intact |
| `DocsOnlyJudge` | Run against raw profiles | **Gated** — only runs when both profiles `evidence_level >= "docs-only"` (i.e. enriched) |
| Bootstrap behavior | Writes raw ONEXUS profiles + queues 4,950 pairs | Writes raw ONEXUS profiles tagged `evidence_level: "unverified-profile"` + queues **enrichment work**, not pair work |
| New: `ProfileEnrichmentJudge` | — | Wraps existing `LLMClient.extract_profile`, fetches GitHub README, produces a `docs-only` enriched profile |
| New: `AdapterScaffolder` | — | For runnable agents (GitHub source + signal), scaffolds `adapters/<slug>/{Dockerfile, mcp.json}` so sandbox tick can drive them |
| `evidence_level` ladder | docs-only → profile-verified → sandbox-validated | **unverified-profile** → docs-only → profile-verified → sandbox-validated |
| What ships overnight | 5,000+ docs-only pair verdicts | 0–500 enriched profile pages + the queue framework for pair work |

## Goals

1. **No more zero-information verdicts** on the site. Every published verdict represents real signal — either enriched profile capabilities reasoned over, or actual sandbox transcript evidence.
2. **5,554 profile pages live on `site/` within 24h.** Day-1 catalog size matches the spec's "catalog completeness by morning" goal — but as profile pages, not noise verdicts.
3. **Profile enrichment as a first-class evidence tier.** Existing schema already supports `unverified-profile` and `docs-only`; we use both deliberately.
4. **Adapter scaffolder reaches the long tail.** Every ONEXUS record with `source.github` set becomes a candidate for a scaffolded MCP adapter; the existing sandbox runner drives them.
5. **Reversible at every step.** Profiles, pair pages, and adapter scaffolds all live on disk; nothing is irreversibly published until human review on the sandbox tier.

## Non-goals

- Restyling site/. New tiers render through existing `agents/[slug].astro` and `verdicts/[id].astro`.
- Replacing the `pairwise_judge` prompt (works as-is).
- Sandbox runner refactor — `SandboxJudge` registry wrapper is still deferred.
- Auto-publishing sandbox-tier verdicts (existing manual approve flow stays).
- Chain (3+ agent) verdicts. Pairs first, even now.

## Architecture

Five-stage pipeline, now expanded with an `Enricher`:

```
┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐  ┌───────────┐
│ Source   │→ │ Profiler │→ │ Enricher │→ │ Planner  │→ │ Judge  │→ │ Publisher │
└──────────┘  └──────────┘  └──────────┘  └──────────┘  └────────┘  └───────────┘
  ONEXUS,       Raw→stub     Fetch README,  Only pairs   Docs-only,  Auto-pub by
  HF (later)    profile      LLM enrich    where BOTH    profile,    evidence
                (unverified) → docs-only   profiles      sandbox     tier policy
                              profile      enriched
```

Two new types of WorkItem now live in the queue: `enrichment` and `pair-judge`. Same JSONL file, same `WorkItem` dataclass, distinguished by `requested_judge`.

### File layout (new pieces)

```
smadp/autopilot/
  enrichers/
    __init__.py
    base.py
    github_readme.py        # NEW — GitHub README fetcher + LLM enrich
  judges/
    profile_enrich.py       # NEW — ProfileEnrichmentJudge (calls LLMClient.extract_profile)
  planners/
    enrichment.py           # NEW — enqueues enrichment work for unverified profiles
    pair_gate.py            # NEW — enqueues pair work only when both profiles enriched
  scaffolders/              # NEW
    __init__.py
    base.py
    mcp_adapter.py          # NEW — Dockerfile + mcp.json from ONEXUS GitHub source
```

### Modified pieces

- `smadp/autopilot/profilers/onexus.py` — sets `evidence_level: "unverified-profile"`, drops the (broken) tag-based capability inference. Leaves capabilities as `null` / empty so the enricher can fill them. Stub profile still has slug, name, category, docs URLs, evidence refs.
- `smadp/autopilot/bootstrap.py` — bootstrap now queues *enrichment* WorkItems for the union of (top-N + existing), not pair-judge WorkItems. Pair gate runs separately, downstream.
- `smadp/autopilot/docs_only_tick.py` — dispatch by `requested_judge`: route to `ProfileEnrichmentJudge` or `DocsOnlyJudge` based on the queued item's judge name. The orchestrator is generic; specific judges are injected.

### Interfaces (additions)

```python
# Enricher — augments a stub profile with capability data
class Enricher(ABC):
    name: str
    cost_per_call_usd: float
    @abstractmethod
    def enrich(self, profile: dict) -> dict: ...    # returns enriched profile dict

# Scaffolder — turns an ONEXUS record into a runnable adapter dir
class Scaffolder(ABC):
    name: str
    @abstractmethod
    def scaffold(self, profile: dict, *, target_dir: Path) -> Path: ...    # returns adapter dir
```

`ProfileEnrichmentJudge` implements `Judge` (so it slots into the existing tick dispatch) while delegating to `Enricher.enrich`. Its `evaluate()` returns a `JudgeResult` whose `verdict` is actually the **updated profile JSON**, not a pair verdict. Publisher routes profile-updates to `catalog/profiles/<slug>.json` (overwrite the stub) instead of `catalog/verdicts/`.

We add a second method on `PolicyPublisher`:

```python
def commit_profile(self, profile: dict) -> Path: ...    # writes catalog/profiles/<slug>.json
```

…and the tick orchestrator picks between `commit` and `commit_profile` based on the judge name.

## Data flow

### Bootstrap (new behavior)

```
$ smadp autopilot bootstrap-onexus --top-n 100

  ① OnexusSource → 5,554 RawOnexusAgent records
  ② OnexusProfiler → stub profile dicts:
     {slug, name, category, docs_urls, evidence_refs, evidence_level: "unverified-profile",
      capabilities: null, concurrency_model: null, data_classes_touched: []}
  ③ Write catalog/profiles/<slug>.json for each (idempotent + respects manual: true)
  ④ EnrichmentPlanner emits one WorkItem per stub profile:
     {pair: [slug, slug], requested_judge: "profile_enrich", judge_version: "v1",
      priority: composite_score, enqueued_at}
     Note: pair is (slug, slug) — single-agent work item; cleanest reuse of the schema.
  ⑤ Append to state/docs_only_queue.jsonl
```

### Steady-state enrichment (launchd 300s)

```
autopilot docs-only-tick:
  ① Read next N from queue (priority desc, budget gated)
  ② For each item:
       requested_judge == "profile_enrich":
         a. GithubReadmeFetcher: fetch raw README from source.github (cached on disk)
         b. ProfileEnrichmentJudge: LLMClient.extract_profile against {README, stub} → enriched dict
         c. PolicyPublisher.commit_profile → catalog/profiles/<slug>.json (overwrite stub)
         d. evidence_level = "docs-only" on enriched profile
         e. Budget += $0.04
  ③ When enrichment queue empties, PairGatePlanner runs:
     For every (a, b) in top-N union where BOTH evidence_level >= "docs-only":
       enqueue pair-judge WorkItem
  ④ Tick now drains pair-judge items via DocsOnlyJudge (existing path, already built)
```

### Adapter scaffolder (parallel track)

Triggered manually for now (not autopilot-driven):

```
$ smadp adapters scaffold --from-onexus <slug>

  ① Read catalog/profiles/<slug>.json — must be enriched (evidence_level >= "docs-only")
  ② Require source.github set in the onexus block
  ③ Generate adapters/<slug>/Dockerfile from a template (base image picked per category)
  ④ Generate adapters/<slug>/mcp.json from enriched capabilities + tags
  ⑤ Add slug to scripts/sandbox-runnable.yaml so sandbox autopilot tick picks it up
```

This is the path to the *real* product differentiator. Once a slug has both an adapter and a sandbox transcript, the existing `SandboxJudge` (via the unchanged `tick.py`) produces `sandbox-validated` verdicts.

### Where files land

| Path | Written by | When |
| --- | --- | --- |
| `catalog/profiles/<slug>.json` (stub) | OnexusProfiler via bootstrap | Bootstrap |
| `catalog/profiles/<slug>.json` (enriched, overwrites stub) | PolicyPublisher.commit_profile | Each enrichment tick |
| `state/docs_only_queue.jsonl` | EnrichmentPlanner / PairGatePlanner / bootstrap | Bootstrap + after enrichment queue drains |
| `state/budget.json` | tick (atomic) | Per LLM call |
| `state/enrichment_cache/<slug>.txt` | GithubReadmeFetcher | First fetch per agent (idempotent) |
| `catalog/verdicts/<verdict_id>.json` | PolicyPublisher.commit | DocsOnlyJudge after pair-gate passes |
| `catalog/pending/...` | existing sandbox flow | unchanged |
| `adapters/<slug>/{Dockerfile,mcp.json}` | mcp_adapter Scaffolder | Manual CLI invocation |

## Error handling

- **GitHub fetch failure (404, rate limit, network)**: cache miss → log to `state/enrichment_errors.jsonl`, skip enrichment, profile stays `unverified-profile`. Tomorrow's tick retries.
- **LLM enrichment returns invalid schema**: existing `extract_profile` validates via tool schema; retry once, then fail-soft and log.
- **Pair-gate skipped pair**: silent — pair simply doesn't enter the queue until both sides are enriched.
- **Scaffolder bad input** (no GitHub source, no enriched capabilities): refuse with explicit error, do not produce a half-formed adapter dir.
- **Budget exhausted mid-enrichment**: same as existing tick — exit gracefully, resume on next 300s fire.

## Testing

- `test_profile_enrich_judge.py` — mock LLMClient.extract_profile, assert enriched profile dict round-trips through PolicyPublisher.commit_profile.
- `test_github_readme.py` — mock `urlopen` (or `httpx`) to return a fixture README; assert caching + 404 handling.
- `test_enrichment_planner.py` — fixture catalog with 3 unverified profiles → 3 enrichment WorkItems.
- `test_pair_gate_planner.py` — fixture: 4 profiles where 2 are docs-only and 2 are unverified. Only the (docs-only × docs-only) pair gets queued.
- `test_bootstrap_v2.py` — bootstrap writes stubs (not enriched) and queues enrichment items, not pair items.
- `test_scaffold_mcp_adapter.py` — given an enriched profile with source.github + execute_shell capability, scaffolder produces a syntactically valid Dockerfile + mcp.json.

## Cost model

| Phase | Call type | Volume | Unit cost | Total |
| --- | --- | --- | --- | --- |
| Profile enrichment | LLM `extract_profile` (gpt-5.4-mini) + GitHub fetch | 5,554 × 1 | ~$0.04 | ~$220 |
| Pair judging (post-gate, top-100 union) | LLM `judge_pair` | up to 4,950 | ~$0.04 | up to ~$200 |
| Combined first 30 days | | | | ~$420 cap at $20/day soft = ~21 days |

GitHub anonymous API limit is 60 req/h; the README fetcher honors this with a backoff. With auth token: 5,000 req/h → no real limit.

## Configuration additions

```yaml
# config/autopilot.yaml additions

enrichers:
  github_readme:
    enabled: true
    github_token_env: GITHUB_TOKEN   # optional; raises rate limit
    cache_dir: state/enrichment_cache
    max_readme_chars: 60_000

judges:
  profile_enrich:
    enabled: true
    model: gpt-5.4-mini
    cost_per_call_usd: 0.04
  docs_only:
    enabled: true                    # but pair gate must pass
    require_evidence_level: docs-only
    model: gpt-5.4-mini

scaffolders:
  mcp_adapter:
    base_image_by_category:
      coding: python:3.11-slim
      data-science-ml: python:3.11-slim
      web-dev: node:20-alpine
      default: python:3.11-slim
    require_github_source: true
    require_capability_signal: true
```

## Open questions

- **README size limit**: 60k char cap is generous; tune after first 50 enrichments by tokens-in. Trim README before LLM call to keep cost predictable.
- **Pair gate threshold**: minimum is "both enriched" (`evidence_level >= "docs-only"`). Stronger gate ("at least one True capability flag") is cheap to add; deferred until first batch of enriched profiles lands.
- **Re-enrichment cadence**: when ONEXUS upstream refreshes (catalog daily updates), do we re-enrich? Initial answer: only if the GitHub source SHA has changed. Tracked in profile's `onexus.last_commit_at` field.
- **GITHUB_TOKEN env**: user has one set (the `.env` mentions one); confirm before bulk enrichment.

## Sequencing (replaces the prior plan's T1–T9)

Tonight's smoke proved T1–T8 (work_queue, source, profiler stub, judge wiring, publisher, planner, tick orchestrator, CLI). Profiler will be lightly amended to set `evidence_level: "unverified-profile"`. The remaining work:

1. `Enricher` ABC + `GithubReadmeFetcher` (with caching).
2. `ProfileEnrichmentJudge`.
3. `PolicyPublisher.commit_profile`.
4. `EnrichmentPlanner` — emits one WorkItem per unverified-profile slug.
5. `PairGatePlanner` — emits pair-judge WorkItems only when both sides enriched.
6. `docs_only_tick` dispatch: judge name → which judge → which publisher method.
7. Update `bootstrap-onexus` to use `EnrichmentPlanner` instead of `TopNPlanner`.
8. New CLI command: `autopilot pair-gate-plan` (re-runs the gate after enrichment).
9. 5-agent enrichment smoke: bootstrap → enrich 5 high-priority agents → eyeball enriched capabilities → if real, run 5 pair-judges → eyeball verdicts. **No launchd activation until both gates pass.**
10. `mcp_adapter` Scaffolder + `adapters scaffold` CLI.
11. Adapter scaffolder smoke: pick 3 enriched-and-runnable agents → scaffold → manually run their adapter through the existing sandbox runner.
12. Only then: launchd loop activation with both enrichment and pair-judge paths live.

## Out of scope

- HuggingFace as a Source (deferred).
- ProfileVerifiedJudge as a distinct LLM pass (profile enrichment already covers most of this — promotion happens only when sandbox produces evidence).
- Chain (3+ agent) work.
- Auto-scaffolding via launchd. Scaffolder stays manual until proven.

## Acceptance criteria

- After enrichment smoke (5 agents): each enriched profile has at least 3 non-default capability flags + a non-empty `data_classes_touched` list + a populated `concurrency_model`. Manual eyeball is the test.
- After pair-judge smoke (5 pairs over enriched profiles): no two verdicts share an identical composite_score; severity distribution shows at least three distinct severities across the 5 × 5 = 25 sub-verdicts.
- After scaffolder smoke (3 adapters): each `adapters/<slug>/Dockerfile` builds (`docker build .` returns 0); each `mcp.json` validates against the existing adapter schema.

If any criterion fails, the loop does not activate.
