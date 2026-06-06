# Design: ONEXUS Autonomous Loop

**Date:** 2026-06-06
**Status:** Draft — awaiting user review
**Spec ID:** `2026-06-06-onexus-autonomous-loop-design`

## Summary

A modular five-stage pipeline (Source → Profiler → Planner → Judge → Publisher) that ingests the 3,202 agents from the ONEXUS-Agents catalog, generates SMADP profile pages for all of them, and produces Docs-only pair verdicts for the top-100 by composite score (~4,950 pairs). The pipeline runs unattended via the existing launchd autopilot loop, draining a JSONL work queue at $20/day soft / $30/day hard LLM cost.

The architecture replaces autopilot's implicit single-judge assumption with an explicit judge registry, letting `DocsOnlyJudge` and `SandboxJudge` coexist now and unlocking `ProfileVerifiedJudge`, future model judges, and adapter-driven judges later.

## Goals

1. **Catalog completeness by morning:** ~100 new profile pages live on `site/` and ~500–1,000 Docs-only verdicts on disk in a week of unattended grinding.
2. **Autonomous:** user does not micromanage individual runs; budget + auto-publish policy handle the steady state.
3. **Reversible:** `DocsOnlyJudge` outputs are clearly marked evidence-tier 1 ("Docs-only" badge already supported by `site/`). Sandbox-tier verdicts continue to require manual approval via existing pending/ flow.
4. **Honest evidence tiers:** every verdict carries its `evidence_level`; the site already renders this badge today. No tier inflation.
5. **Foundation, not just feature:** the modular registry is the architecture for ProfileVerifiedJudge, adapter scaffolding, and chain judges later.

## Non-goals

- **MCP adapter scaffolder** — separate effort, deferred to a follow-up spec.
- **Sandbox judge refactor** — existing `smadp sandbox` CLI keeps its current shape; `SandboxJudge` is a thin wrapper for registry uniformity, no behavior change.
- **Chain verdicts** — pairs first; chains come after the pair loop is proven.
- **Restyling site/** — visuals untouched. New verdict pages render through existing `verdicts/[id].astro`.
- **Auto-publishing sandbox verdicts** — sandbox results continue to land in `catalog/pending/` for manual approval.
- **Building new judges beyond DocsOnly** — `ProfileVerifiedJudge`, `EvidenceLensJudge`, etc. are designed-for but not implemented here.

## Architecture

Five composable stages, each a Python ABC with auto-discovered concrete implementations registered at import time.

```
┌──────────┐  ┌──────────┐  ┌─────────┐  ┌────────┐  ┌───────────┐
│ Source   │→ │ Profiler │→ │ Planner │→ │ Judge  │→ │ Publisher │
└──────────┘  └──────────┘  └─────────┘  └────────┘  └───────────┘
  ONEXUS,       Raw→SMADP    Priority,    Docs-only,  Auto-pub by
  HF (later),   profile      coverage,    profile,    evidence
  GH trending   schema       top-N        sandbox     tier policy
```

### File layout

```
smadp/autopilot/
  registry.py        # NEW — Source/Profiler/Planner/Judge/Publisher ABCs + @register decorator
  tick.py            # REFACTORED — uses registry; existing sandbox path preserved
  bootstrap.py       # NEW — one-shot CLI: `smadp autopilot bootstrap-onexus`
  sources/
    __init__.py
    base.py          # Source ABC
    onexus.py        # OnexusSource
  profilers/
    __init__.py
    base.py          # Profiler ABC
    onexus.py        # OnexusProfiler
  planners/
    __init__.py
    base.py          # Planner ABC
    top_n.py         # TopNPlanner
    priority.py      # PriorityPlanner (extracted from existing tick.py)
  judges/
    __init__.py
    base.py          # Judge ABC
    docs_only.py     # DocsOnlyJudge
    sandbox.py       # SandboxJudge (wraps existing sandbox runner)
  publishers/
    __init__.py
    base.py          # Publisher ABC
    policy.py        # PolicyPublisher
```

### Interfaces

```python
# Source — discovers raw agent records
class Source(ABC):
    name: str
    @abstractmethod
    def fetch(self) -> Iterator[RawAgent]: ...

# Profiler — normalizes raw → SMADP Profile schema
class Profiler(ABC):
    name: str
    accepts_source: str          # e.g. "onexus"
    @abstractmethod
    def normalize(self, raw: RawAgent) -> Profile: ...

# Planner — emits WorkItems to evaluate
class Planner(ABC):
    name: str
    @abstractmethod
    def plan(self, profiles: list[Profile], coverage: Coverage) -> Iterator[WorkItem]: ...

# WorkItem — what gets queued and judged
@dataclass(frozen=True)
class WorkItem:
    pair: tuple[str, str]           # sorted slugs
    requested_judge: str            # "docs_only" | "sandbox" | ...
    priority: float                 # higher = drained first
    enqueued_at: str                # ISO-8601

# Judge — converts WorkItem → Verdict
class Judge(ABC):
    name: str
    version: str                    # bump on prompt or output-schema change
    evidence_level: EvidenceLevel   # docs | profile | sandbox
    cost_per_call_usd: float
    @abstractmethod
    def evaluate(self, work: WorkItem) -> Verdict: ...

# Publisher — commits Verdict to disk per policy
class Publisher(ABC):
    @abstractmethod
    def commit(self, verdict: Verdict) -> Path: ...
```

A registry module (`registry.py`) provides `@register("source", "onexus")` decorators and lookups (`registry.get_judge("docs_only")`).

## Data flow

### Bootstrap (one-shot, manual tonight)

```
$ smadp autopilot bootstrap-onexus --top-n 100

  ① OnexusSource yields 3,202 RawAgents from ~/Downloads/ONEXUS-Agents/catalog
  ② Filter to composite_score top-100 from ONEXUS. Note: high-traffic agents (aider, cursor, claude-code) likely appear in both ONEXUS and existing SMADP profiles — overlap is handled in step ④. The Planner then emits pairs over the union of (top-100 ONEXUS slugs ∪ existing SMADP slugs), which is ≤130 slugs in practice. 130C2 = 8,385 pairs; cap at 4,950 by score-product priority for parity with the cost model below.
  ③ OnexusProfiler normalizes each → Profile dataclass:
     - slug, name, vendor (from author.handle)
     - source.github (from source.github)
     - evidence.docs[] = [{source_url: github_url, sha256: hash(metadata)}]
     - capabilities inferred from `tags` (heuristic table)
     - evidence_level = "docs"
  ④ Write catalog/profiles/<slug>.json (idempotent; overwrites preserve hand-edits — see Open questions: "Manual profile preservation")
  ⑤ TopNPlanner emits 100C2 = 4,950 WorkItems → state/work_queue.jsonl
     Each item: {pair: [slug_a, slug_b], requested_judge: "docs_only", priority: f(score_a, score_b), enqueued_at}
```

### Steady-state (launchd every 300s)

```
autopilot tick:
  ① Budget pre-check: state/budget.json[today_usd] vs $20 soft / $30 hard
  ② Pop N items from state/work_queue.jsonl
     N = min(batch_size=10, floor(budget_remaining / max_judge_cost))
  ③ For each item:
       a. judge = Registry.get_judge(item.requested_judge)
       b. verdict = judge.evaluate(item)             # LLM call ~$0.04, ~3s
       c. PolicyPublisher.commit(verdict)            # → catalog/verdicts/<id>.json
       d. budget["today_usd"] += verdict.cost_usd; atomic-write state/budget.json
  ④ Site rebuild triggered by existing watchpath on catalog/verdicts/
```

### Where files land

| Path | Written by | Cadence |
| --- | --- | --- |
| `catalog/profiles/<slug>.json` | OnexusProfiler | Bootstrap; on ONEXUS upstream refresh |
| `catalog/verdicts/<verdict_id>.json` | PolicyPublisher (docs_only path) | Per tick judgment |
| `catalog/pending/<verdict_id>.json` | PolicyPublisher (sandbox path) | Per sandbox run (existing) |
| `state/work_queue.jsonl` | TopNPlanner (append); tick (pop) | Bootstrap + tick |
| `state/budget.json` | tick (atomic) | Per judgment |
| `state/coverage.json` | tick (existing) | Per judgment |
| `state/judge_errors.jsonl` | tick on judge exception | Failure path only |
| `state/profiler_skipped.jsonl` | OnexusProfiler on normalize failure | Failure path only |

### Verdict ID and idempotency

- `verdict_id = sha1(":".join(sorted([pair_a, pair_b])) + ":" + judge.name + ":" + judge.version).hexdigest()[:16]`
- Re-running bootstrap or re-judging the same pair updates the same file (overwrite-safe).
- Profile JSON keyed by slug; bootstrap re-runs overwrite cleanly. A `manual: true` flag (added by hand-curators) blocks overwrite — log a skipped row instead.

## Error handling

- **LLM transient failure (network, 5xx):** retry once with 2-second backoff, then write a row to `state/judge_errors.jsonl` (`{pair, judge, error, attempted_at}`) and skip the item. Item is dropped from queue, not requeued — operator decides whether to retry from the error log.
- **Rate limit (429):** exponential backoff up to 5 retries (1s, 2s, 4s, 8s, 16s). Count against the soft budget so a 429 storm doesn't masquerade as throughput.
- **Malformed JSON from LLM:** prevented by construction — use OpenAI's `response_format={"type":"json_schema", "schema": VERDICT_SCHEMA}` so the API enforces shape. If the validation still fails (model refuses, edge case), treat as transient and retry once.
- **Budget exhausted mid-tick:** exit gracefully, log next reset time. Launchd will fire again every 300s; budget resets at 00:00 PT.
- **Profiler normalize failure:** write `state/profiler_skipped.jsonl` row, continue with next record. Bootstrap reports skip count on exit.
- **Disk write failure:** writes are atomic — `write_to_temp; os.rename`. If rename fails, roll back the budget debit before propagating the exception. State stays consistent.
- **OpenAI auth failure (401):** fail fast and loud — write a single error to syslog, exit with non-zero. Launchd backs off automatically on repeated failures.

## Testing

- **Unit tests** for each component class against fixtures:
  - `OnexusSource` over a 5-record fixture catalog
  - `OnexusProfiler` normalizing a known RawAgent → Profile (schema-validated)
  - `TopNPlanner` emitting the expected pair set from 3 profiles
  - `DocsOnlyJudge` against a recorded OpenAI response (`pytest-recording` or hand-stubbed client)
  - `PolicyPublisher` routing by evidence tier
- **Integration test:** end-to-end tick against a 3-record fixture catalog. Asserts profiles + verdicts hit disk with correct schema, budget updated, errors empty.
- **Smoke validation batch** before launchd takes over: run 5 hand-picked pairs (e.g. `aider × cursor`, `langgraph × autogen`, `crewai × autogen`, `cursor × github-copilot`, `claude-code × cursor`) and eyeball the LLM output for sanity. Halt the loop if any verdict looks like garbage.
- **Existing sandbox tests unchanged** — SandboxJudge is a thin wrapper.

## Cost model

| Component | Per-call cost | Volume | Total |
| --- | --- | --- | --- |
| `DocsOnlyJudge` (gpt-5.4-mini) | ~$0.04 | 4,950 pairs (top-100) | ~$198 |
| Daily soft cap | $20 | — | — |
| Daily hard cap | $30 | — | — |
| Time to drain top-100 backlog | ~10 days at soft cap | — | — |

Cost per call estimate: ~3k input tokens (system prompt + 2 profile bodies) + ~800 output tokens (structured verdict). At gpt-5.4-mini pricing this rounds to ~$0.04. **Verify against real billing after first 5-pair smoke batch** — if actual cost differs by 25%+, recalibrate `cost_per_call_usd` in the judge class and adjust soft cap if needed.

## Configuration

New keys in existing `config/autopilot.yaml`:

```yaml
sources:
  - name: onexus
    path: ~/Downloads/ONEXUS-Agents/catalog
    enabled: true

planners:
  active: top_n
  top_n:
    top_n: 100
    score_field: composite_score

judges:
  docs_only:
    enabled: true
    model: gpt-5.4-mini
    max_retries: 5
    cost_per_call_usd: 0.04
  sandbox:
    enabled: true   # existing behavior preserved

publishers:
  policy:
    auto_publish:
      docs: true
      profile: true
      sandbox: false

budget:
  daily_soft_usd: 20
  daily_hard_usd: 30
  reset_tz: "America/Los_Angeles"
```

## Open questions

- **Manual profile preservation:** if a profile JSON contains `"manual": true` at top level, bootstrap should skip with a `state/profiler_skipped.jsonl` row. If the field is absent, bootstrap overwrites. Confirm policy.
- **Verdict prompt:** the exact prompt for `DocsOnlyJudge` is its own design question. Plan: start from `smadp/judging/prompts/pair_verdict.py` (existing sandbox prompt) and trim to docs-only context. Verify in the 5-pair smoke batch.
- **Chain pickups:** TopNPlanner emits pairs only. Chain support (3+) is a follow-up — likely a `ChainPlanner` that selects from successful pair results.
- **HuggingFace / GitHub-trending sources:** designed for, not built. Drop new `Source` classes when ready.

## Sequencing for tonight

1. Refactor `tick.py` to use registry shape (no behavior change for existing sandbox path).
2. Implement `registry.py`, base ABCs, OnexusSource, OnexusProfiler, TopNPlanner, PolicyPublisher.
3. Implement `DocsOnlyJudge` with OpenAI structured outputs against `VERDICT_SCHEMA`.
4. Implement `bootstrap.py` CLI command.
5. Add config keys to `config/autopilot.yaml`.
6. Unit tests for each new component.
7. Integration test end-to-end on 3-record fixture.
8. **Smoke validation:** `smadp autopilot bootstrap-onexus --top-n 5 --dry-run` then `--top-n 5` real run; eyeball 5 verdicts.
9. If smoke passes: scale to `--top-n 100`, populate queue (~4,950 items), let launchd grind.

## Out of scope (explicitly deferred)

- MCP adapter scaffolder for ONEXUS GitHub records
- Chain WorkItems and ChainPlanner
- ProfileVerifiedJudge implementation
- New `Source` implementations (HuggingFace, GitHub trending)
- Sandbox runner refactor onto registry interface
- Site UI changes — new pages render through existing templates
