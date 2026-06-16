# Correction & status — 2026-06-16

A one-time explainer covering what drifted off track over the past week and what
is now repaired. This file is hand-written and dated; it is not the autopilot's
auto-generated daily briefing (`report/2026-06-16.md`), which continues to
regenerate every tick.

## What went off track

A development session that elevated SMADP (the "Proving Ground" work) was
interrupted mid-flight and left several things in a half-finished state:

- **CI was red on `main`.** A Starlette router test asserted on an attribute
  (`.path`) that the upgraded framework no longer exposes, and a batch of
  subagent-built code passed its per-file lint/type checks but not the
  repo-wide gate (`ruff check smadp tests`, `ruff format --check`, `mypy smadp`).
- **The autopilot was churning empty commits.** The per-tick daily report
  carries a fresh timestamp, so the tree always looked "dirty" and the loop
  pushed ~288 no-op commits a day.
- **Pending review silently stalled.** The docs-only work queue
  (`state/docs_only_queue.jsonl`) drained to empty on 2026-06-12 and was never
  refilled. The loop ran `tick → docs-only-tick → scaffold-tick → daily-report`
  but **never ran `pair-gate-plan`** — the step that enqueues new agent pairs to
  judge. Every tick since reported `reason=no_work`; no new verdicts were
  produced and the chronicle of new activity went quiet for four days.
- **The verdict-page citations regressed.** Each A–E sub-verdict rendered its
  citations as absolutely-positioned, translucent popovers anchored to a
  zero-height inline element, so opening more than one stacked them on top of
  each other and they bled through the prose.
- **A backlog of stale dependabot PRs** had accumulated against the
  previously-broken `main`, including the Astro 4→5 site framework bump.

## What is now on track

- **CI is green.** 966 tests pass; `ruff check`, `ruff format --check`, and
  `mypy` are clean across 181 source files on both the 3.11 and 3.12 matrix.
- **The autopilot produces work again.** `pair-gate-plan` now runs every tick
  and refills the queue. It excludes any pair that already has a verdict
  (published in `catalog/verdicts/` or awaiting the gate in `catalog/pending/`),
  and the queue writer dedups against what is already queued — so re-running it
  every five minutes only ever adds genuinely-new pairs. A live run enqueued
  **4,450 fresh pairs** (excluding 566 already-judged) and the next ticks
  published new pending verdicts with `reason=ok`. Pending review, frozen at 34
  since 06-12, is climbing again.
- **Empty-commit churn is fixed.** The git-sync step only treats real catalog
  paths as substantive and discards cosmetic regen on quiet ticks.
- **The citation UI is rebuilt.** Citations now render as opaque, in-flow
  expandable footnotes grouped under a labeled "Evidence" block — several can be
  open at once without overlapping or bleeding through, and the purpose is
  clear. Verified in a browser with multiple footnotes open.
- **The site is on Astro 5 and deployed.** The framework bump (plus
  `@astrojs/tailwind` 6, `@types/node` 25, `happy-dom` 20) was verified against
  the live components — `astro check` 0 errors, full 13,149-page build, vitest
  26/26 — and GitHub Pages deployed green. All dependabot PRs are resolved
  (0 open).

## What to watch

- Pending review grows ~3 verdicts per 5-minute tick (capped at
  `runs_per_day: 200`) until the new pair backlog is worked down. Publishing
  still requires the operator gate: `smadp pending approve`.
- Kill switch unchanged: `touch state/PAUSE` halts the autopilot;
  `touch state/AGENTS_SYNC_DISABLED` halts the ONEXUS-Agents seed sync.
