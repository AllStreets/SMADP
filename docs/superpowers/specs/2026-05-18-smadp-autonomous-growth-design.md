# SMADP Autonomous Growth: pair + chain verdicts on autopilot

**Date:** 2026-05-18
**Status:** Draft spec, awaiting user review
**Supersedes:** task #212 (original autonomous-runner brainstorm)
**Absorbs:** tasks #187 (more pair verdicts), #188 (scale sandbox-smoke)

## Goal

Make the SMADP catalog grow without per-step human direction. The autopilot runs pair verdicts (length-2 chains) and chain verdicts (length 3–4) against the sandbox, applies a safety gate, and publishes to the catalog. The user steers via a priority file and budget caps; everything else is automatic.

## Locked design decisions

| # | Lever | Choice |
|---|---|---|
| Q1 | Autonomy trigger | Hybrid — continuous within daily budget + event-triggered on catalog change |
| Q2 | Chain topology | Linear with role tags (planner / executor / reviewer style) |
| Q3 | Chain length | Scenario-declared, capped at 4 |
| Q4 | Verdict storage | Unified — `roles[]` of length 2 (pair) or 3–4 (chain), single `catalog/verdicts/` directory |
| Q5 | Selection policy | `priority.yaml` drained first, then coverage gap |
| Q6 | Promotion gate | First-time `(scenario, agents)` tuple → `catalog/pending/` for human review; re-runs → auto-publish |
| Q7 | Budget governor | Run cap AND dollar cap, whichever hits first |
| Q8 | Chain scenario authoring | Hand-authored only; revisit after first 50 chain verdicts |

## Architecture: cron-tick planner + existing worker

Two new CLIs plus one shell wrapper for launchd. The existing worker already does inline promotion — we extend its routing rather than introducing a separate promote step:

```
smadp autopilot tick           # plan: pick next tuples, enqueue (idempotent)
smadp sandbox work             # already exists — drains queue, runs, promotes inline
smadp autopilot approve <key>  # move catalog/pending/<key>.json → catalog/verdicts/<key>.json
smadp autopilot loop           # launchd target: tick → work → sleep 5m
```

### Data flow

```
catalog/priority.yaml + smadp/sandbox/scenarios/ + adapters/<slug>/mcp.json
   │
   ▼
[ tick ] ──► for each candidate scenario: binder.find_match(scenario, slugs)
   │
   ▼
queue (existing queue module)
   │
   ▼
[ work ] ──► runner.execute_run(run_id)   (existing runner module)
   │           │
   │           ▼
   │        promote.promote_from_run(run_id)
   │           │
   │           ▼
   │   verdict exists at catalog/verdicts/<key>.json?
   │           ├── no  → write at catalog/pending/<key>.json (initial verdict)
   │           └── yes → mutate in place (existing accumulation logic)
   ▼
[ approve ] ──► catalog/pending/<key>.json → catalog/verdicts/<key>.json
```

`<key>` is the participating-agents key: `<slug_a>__<slug_b>` for pairs, `<slug_a>__<slug_b>__<slug_c>` for length-3 chains, sorted lexicographically so role assignment ordering doesn't change the filename.

### Why a cron-tick planner instead of a daemon

- No long-running process to babysit; launchd restart = state on disk picks up where it left off.
- Each tick is idempotent. Calling it twice is a no-op if budget is exhausted or queue is full.
- State lives in plain files (`state/budget.json`, `state/coverage.json`, `catalog/priority.yaml`, `catalog/pending/`), so debugging is `cat`-and-edit.
- Five-minute granularity on event triggers is fine — catalog edits are not latency-sensitive.

### Event triggers

A launchd `WatchPaths` rule on `catalog/scenarios/` and `catalog/agents/` fires an extra `tick` invocation on file change. No additional code.

## Data model: pair → N-ary

The existing scenario schema already uses a named-key mapping for agents. We relax the "exactly 2" constraint to "2–4" rather than rewriting the schema as an array. Existing scenarios and verdicts continue to validate without changes.

### Scenario shape (unchanged keys, relaxed count)

The existing schema (`smadp/sandbox/scenarios/*.yaml`) supports 2 named role keys. The new chain shape adds 1–2 more named keys:

```yaml
name: code_review_chain                # length-3 example
description: >
  Planner drafts a fix; executor applies it; reviewer audits the diff.
timeout_s: 600

agents:
  planner:
    adapter: null
    required_capabilities: [read_filesystem]
    role: "Read the bug report and propose a patch plan."
    initial_prompt: "..."
  executor:
    adapter: null
    required_capabilities: [read_filesystem, write_filesystem, execute_shell]
    role: "Apply the patch the planner drafted."
    initial_prompt: "..."
  reviewer:
    adapter: null
    required_capabilities: [read_filesystem]
    role: "Audit the diff before commit."
    initial_prompt: "..."

shared_workspace:
  type: tmpfs
  files: [/work/plan.md, /work/diff.patch]

# allow_egress / synthetic_secrets / assertions unchanged
```

`loader.py` is updated so `_validate` accepts 2–4 `agents:` entries instead of requiring exactly 2; `Scenario.agents` becomes `tuple[AgentRole, ...]` instead of `tuple[AgentRole, AgentRole]`.

### Verdict shape (generalized key, unchanged inner schema)

Existing pair verdicts at `catalog/verdicts/<slug_a>__<slug_b>.json` keep their schema. The only changes are at the boundary:

- Filename pattern: `<slug_a>__<slug_b>[__<slug_c>][__<slug_d>].json`, slugs sorted lexicographically.
- Top-level `pair: [a, b]` field generalizes to `participants: [a, b, ...]` (with `pair` retained as a deprecated alias on existing files for one release cycle, then deleted).
- `sandbox_runs[]`, `evidence_level`, `sub_verdicts`, etc. all stay as they are.

Inside, the accumulation semantics from `promote.py` remain authoritative — every run mutates the participating-agents verdict in place; nothing changes about ladders, severity bumps, or chronicle events.

### Binder

`bind_scenario_to_pair(scenario, slug_a, caps_a, slug_b, caps_b)` is replaced by:

```python
def bind_scenario(
    scenario: Scenario,
    *,
    agents: Mapping[str, Mapping[str, Any]],   # {slug → capabilities}
) -> BindingResult                              # {role_key → slug}
```

It tries every permutation of `len(scenario.agents)` slugs across the role keys and returns the first assignment whose required_capabilities are all satisfied. With ~10 adapters available and N roles:

- N=2: 90 ordered pairs (today)
- N=3: 720 ordered triads
- N=4: 5,040 ordered 4-tuples

Coverage policy (§5) prunes this dramatically — the autopilot only enqueues *uncovered* assignments per scenario.

## Autopilot internals

### `smadp autopilot tick` (planner)

```
1. If state/PAUSED exists: exit 0
2. Load state/budget.json
   - If date != today: reset runs_today=0, dollars_today=0
   - If runs_today >= runs_per_day OR dollars_today >= dollars_per_day: exit 0
3. Load catalog/priority.yaml
   - For each unrun priority entry: enqueue, mark "enqueued_at" in coverage.json
4. If priority drained AND budget remains:
   - Compute coverage gap from state/coverage.json
   - Rank uncovered (scenario × role-assignment) tuples
   - Tie-break: fewest verdicts on scenario, then fewest on each agent
   - Enqueue up to (runs_per_day - runs_today) tuples
   - Refuse to enqueue any tuple whose estimated cost would exceed remaining $ budget
5. Update state/coverage.json (enqueued_at markers prevent double-enqueue on re-tick)
6. Exit 0
```

Tick never executes a run. Safe to invoke every minute if you want; the work happens in `work`.

### Promotion gate (extended worker behavior)

`smadp sandbox work` continues to call `promote.promote_from_run(run_id)` inline after each run completes. We extend `promote.py` so the *initial* verdict for an agent-combination lands at `catalog/pending/<key>.json` instead of `catalog/verdicts/<key>.json`. Subsequent runs against an already-promoted verdict use the existing accumulation path unchanged.

Concretely, inside `promote_from_run`:

```
1. participants = sorted([role_to_slug[r] for r in scenario.agents])
2. key = "__".join(participants)
3. pending_path  = catalog_root / "pending"  / f"{key}.json"
4. verdicts_path = catalog_root / "verdicts" / f"{key}.json"
5. If verdicts_path.exists():     # repeat run: existing accumulation
       load(verdicts_path); apply_run_to_verdict(); save(verdicts_path)
6. Elif pending_path.exists():    # repeat run while still in review
       load(pending_path); apply_run_to_verdict(); save(pending_path)
7. Else:                          # very first run for this combination
       new_verdict = seed_verdict(participants, scenario, run)
       save(pending_path)
8. promote_from_run still:
       - appends SandboxRun, updates evidence_level, bumps sub-verdict severity
       - records chronicle event
       - updates state/coverage.json:last_verdict_ts for this key
       - updates state/budget.json: increment runs_today, add actual_dollars
9. If saved to verdicts_path: touch report/.rebuild-requested
```

The "first-time" check is "does `catalog/verdicts/<key>.json` exist?" — that file IS the human-approved record. Initial seeding (step 7) produces a verdict that looks identical structurally; the only difference is which directory holds it.

### `smadp autopilot approve <key>` (publish)

```
1. Move catalog/pending/<key>.json → catalog/verdicts/<key>.json
2. touch report/.rebuild-requested
3. Record a chronicle event: sandbox.verdict.approved with key + approver
4. Exit 0; non-zero if pending file doesn't exist
```

Inverse `smadp autopilot reject <key>` deletes the pending file with a chronicle event so we have a record. Out of scope for v1 if needed.

### `smadp autopilot loop` (launchd target)

A trivial shell script:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
smadp autopilot tick
smadp sandbox work --once --max-runs=3
```

launchd interval-driven: every 300 seconds. If launchd kills it mid-run, the queue and state files on disk mean the next invocation resumes cleanly. The worker handles promotion inline (extended per above) so the loop has only two CLI calls, not three.

### `catalog/priority.yaml` (user steering wheel)

```yaml
priority:
  - { scenario: code-review-tampering, agents: [aider, autogen] }
  - { scenario: secrets-exfiltration, kind: chain, agents: [aider, continue-dev, autogen] }
```

Tick drains top-down. Empty file = pure coverage mode. The autopilot never edits this file — it's user-only.

## Budget governor + cost estimation

### `state/budget.json` (mutable state)

```json
{
  "date": "2026-05-18",
  "runs_today": 7,
  "dollars_today": 2.34
}
```

Daily reset is lazy: tick checks `date` field and zeros counters when it doesn't match today.

### `config/autopilot.yaml` (user-edited caps)

```yaml
runs_per_day: 10
dollars_per_day: 5.00
```

Conservative defaults. Raise by editing the file; no code change required. The launchd plist is the schedule authority — tick interval lives there, not in this config. Concurrency is bounded structurally by a single worker process draining the queue sequentially; no lock needed.

### Two-stage cost accounting

1. **Pre-flight estimate** (`tick`): each adapter manifest declares `expected_cost_per_run` (token budget × current model price). Tick refuses to enqueue a tuple whose estimate would push `dollars_today + estimate` past the cap.
2. **Post-flight actual** (`promote`): `runner.py` already records token counts. Promote multiplies by `config/model_prices.yaml` and accumulates the real cost.

Without post-flight, an underestimated adapter would silently blow the cap. Without pre-flight, the planner couldn't reject expensive runs at the right point.

### Manual pause

`touch state/PAUSED` — tick checks for this file and exits 0 if present. `rm state/PAUSED` resumes. No daemon signalling.

## Report site adaptation

- **Data layer** (`report/src/lib/catalog.ts`): generalize types from `role_a/role_b` to `roles[]`. Migration already aligned every verdict file; this is a typing change plus accessor renames, not a dual path.
- **`/search`**: new `kind` filter chip (All / Pair / Chain). Verdict row renders agents as `aider → continue-dev → autogen` for chains, `aider × autogen` for pairs.
- **Verdict detail pages**: pair view (role A | role B side-by-side) generalizes to a vertical stack of role panels for chains. Same transcript viewer, same judge block.
- **Prospectus agents table**: add `Chains` column next to `Verdicts`. Reuses centered-numeric styling.
- **Dossier "11 · Open questions"**: seeded subsection on chain-specific failure modes (handoff drift, blame diffusion). Updated by hand until first 50 chain verdicts land.
- **References (live-growth page)**: third "Chains" row in catalog-status block alongside Pairs and Sandbox. Pulsing-dot framing extends cleanly.
- **`/pending`** (new route, not linked from nav): browser view of `catalog/pending/*.json` for first-time tuples. Each entry has an "Approve → publish" affordance that documents the local CLI step (`smadp autopilot approve <run_id>`); no server-side writes.
- **Rebuild trigger**: `promote` writes `report/.rebuild-requested` when a verdict is published; a launchd watchpath job runs `pnpm build` when it appears. Falls back to daily rebuild if launchd isn't set up.

## Testing strategy

### Unit tests (pytest)

- `tests/sandbox/test_binding.py` (existing file, extended) — N-ary `bind_scenario`: length-3 and length-4 cases; capability matching; raises `ScenarioBindingError` when no permutation satisfies the scenario.
- `tests/autopilot/test_tick.py` — priority drained first, then coverage; idempotent on re-invocation; refuses when budget exhausted; refuses when `state/PAUSED` exists; refuses to enqueue tuples whose pre-flight estimate exceeds remaining $ budget.
- `tests/sandbox/test_promote.py` (existing file, extended) — first-time → `pending/`; re-run on existing pending → mutate pending; re-run on existing verdict → mutate verdict; `report/.rebuild-requested` written when verdicts mutate.
- `tests/autopilot/test_budget.py` — daily reset on date change; pre-flight gate; post-flight accumulation via promote.
- `tests/autopilot/test_approve.py` — pending → verdicts move; chronicle event recorded; non-zero exit on missing pending.
- `tests/sandbox/test_scenarios_nary.py` — loader accepts 2, 3, 4 agents; rejects 1 or 5; existing fixtures still parse.

### Integration test

- `test_autopilot_loop.py` — one full tick → work → promote cycle against a fake catalog with one pair scenario and one length-3 chain scenario, using the synthetic adapter. Assert both produce verdicts and land in the expected directories.
- `smadp autopilot tick --dry-run` — prints what it *would* enqueue without writing. Used in CI to assert the planner doesn't crash on the real catalog.

### Site tests (Playwright, extends `routes.spec.ts`)

- Chain verdict renders with `roles[]` of length 3 visible.
- `/search` kind filter toggles pair-vs-chain results.
- `/pending` route renders when fixture pending files exist.

### Smoke test (proof of life before enabling launchd)

After all CLIs land but before flipping launchd on:

```bash
# Seed priority with the new chain scenario, one tuple
echo "priority:" > catalog/priority.yaml
echo "  - { scenario: code_review_chain, agents: [aider, continue-dev, autogen] }" >> catalog/priority.yaml

smadp autopilot tick                  # enqueues one job
smadp sandbox work --once --max-runs=1   # runs + promotes inline → pending/

# Inspect catalog/pending/aider__autogen__continue-dev.json (slugs are sorted)
# If it looks right:
smadp autopilot approve aider__autogen__continue-dev
# Then enable launchd.
```

### What we don't test

- Actual model behavior — that's what the catalog *is*.
- Cost estimation accuracy — it'll always drift, hence post-flight correction.

## Rollout sequence

Eight commits, each leaves the repo in a working state.

1. **Scenario loader: relax 2 → 2–4 agents.** Update `_validate` in `smadp/sandbox/scenarios/loader.py`; change `Scenario.agents` from `tuple[AgentRole, AgentRole]` to `tuple[AgentRole, ...]`. Existing 2-agent fixtures unchanged. New unit tests for 3 and 4 agents.
2. **Binder generalization.** Replace `bind_scenario_to_pair` with `bind_scenario(scenario, agents={slug→caps})` returning `{role_key → slug}`. Existing pair tests pass via the new API; new length-3/4 tests added.
3. **Queue + verdict key generalization.** Generalize queue rows from `slug_a/slug_b/role_a/role_b` to `participants: list[{role, slug}]`. Generalize verdict filename/key from `<a>__<b>.json` to sorted `<a>__<b>__...json`. Update `CatalogRepo.load_verdict`/`save_verdict` accordingly; `pair: [a,b]` → `participants: [a,b,...]` with `pair` kept as read-time alias.
4. **Promote.py routing: first-time → pending/.** Extend `promote_from_run` to check `verdicts_path.exists()`; route initial seed to `catalog/pending/<key>.json`; touch `report/.rebuild-requested` on verdict-directory writes. Coverage + budget state updates added (read by tick, written by promote).
5. **First hand-authored chain scenario.** One length-3 scenario `code_review_chain.yaml` at `smadp/sandbox/scenarios/`. Binder + loader unit test confirms it parses and binds against the existing 4 adapters.
6. **`smadp autopilot tick` + budget + priority + pause.** New module `smadp/autopilot/`. CLI: `smadp autopilot tick [--dry-run]`. Reads `config/autopilot.yaml` caps, `state/budget.json`, `state/coverage.json`, `catalog/priority.yaml`, `state/PAUSED` sentinel. Computes next enqueue set, calls existing queue API. Full unit + integration tests.
7. **`smadp autopilot approve` CLI + report site adaptation.** `smadp autopilot approve <key>` moves `pending/<key>.json` → `verdicts/<key>.json` with chronicle event. Report site: generalize `report/src/lib/catalog.ts` to `participants[]`; add `kind` filter on `/search`; render chains as `a → b → c`; add `Chains` column on prospectus; add `/pending` review route; extend Playwright suite.
8. **`loop` wrapper + launchd plists.** `scripts/autopilot-loop.sh` runs `tick + sandbox work`. `scripts/launchd/com.smadp.autopilot.loop.plist` (interval 300s); `scripts/launchd/com.smadp.autopilot.watch.plist` (`WatchPaths` on `smadp/sandbox/scenarios/` and `adapters/`). README install section. Smoke test in §6 run manually first; launchd flipped on only after the first chain verdict lands cleanly.

## Out of scope

- Auto-derived chain scenarios from pair scenarios — revisit after 50 chain verdicts (Q8).
- LLM-proposed scenarios queued for review — same reason.
- Arbitrary DAG chain topology — `handoff: linear` is the only supported value; field is reserved.
- Risk-weighted selection — Q5 chose coverage + priority as the right separation; weighting bakes judgment into the runner.
- Confidence-based promotion gate — Q6 chose first-time-vs-rerun; gating on judge confidence is circular because confidence is one of the things we're measuring.
- Web-based approval UI — `/pending` route is read-only; approval happens via CLI to keep the trust boundary clear.
