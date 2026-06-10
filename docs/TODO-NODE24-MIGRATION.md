# TODO: Node.js 24 migration

**Status as of 2026-06-09: wait and watch.** This file is a deliberate
parking lot. Re-open it if CI starts complaining or when one of the
deadlines below trips.

## Why this file exists

GitHub Actions emitted a deprecation warning on CI run #120 (commit
`507e01e4`) and every run since:

> Node.js 20 actions are deprecated. The following actions are running
> on Node.js 20 and may not work as expected: `actions/checkout@v4`,
> `actions/setup-python@v5`, `actions/setup-node@v4`,
> `pnpm/action-setup@v4`.

Two real deadlines come out of that warning:

| Date | What happens |
|---|---|
| **2026-06-16** | Node.js 24 becomes the default runner for actions. Existing actions either survive or break, depending on whether the maintainer has shipped a Node-24 release. |
| **2026-09-16** | Node.js 20 removed from runners entirely. Anything still depending on it stops working. |

## Decision: wait and watch (cheapest)

Rationale: every action flagged is a top-tier action maintained by
GitHub or pnpm. They will all ship Node-24-compatible releases before
2026-06-16. The risk of doing nothing is bounded: if CI breaks, the fix
is almost always a one-line version bump (`actions/checkout@v4` →
`@v5`, etc.).

We are not pre-empting because:
- It would mean editing two workflow files for a problem that may never
  occur.
- The pre-empt itself uses an env var (`FORCE_JAVASCRIPT_ACTIONS_TO_NODE24`)
  that is itself transitional, so we'd just have to remove it later.

## Pre-empt option (use this if you change your mind)

If CI breaks on or before 2026-06-16, the cheapest fix is to opt-in to
Node 24 globally for our two workflows:

```yaml
# .github/workflows/ci.yml
# .github/workflows/deploy-pages.yml
env:
  FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true
```

Add it at the top level of each workflow, push, and watch CI. If the
opt-in itself causes failures, that's a signal one of our pinned
actions hasn't shipped a Node-24 release yet, and you should bump that
specific action's version.

## What to do when CI actually breaks

1. Read the actual failure. It will name one of the four actions above
   (or pnpm) and a specific Node call that no longer works.
2. Find the latest release of that action on its GitHub page. Bump our
   pin (`@v4` → `@v5`, etc.).
3. If multiple actions are failing at once, prefer the `FORCE_*` env
   var as a holding pattern while you bump them all.
4. Re-run CI. Delete this file once everything is green and the
   2026-09-16 deadline has passed.

## Memory cross-references

- This is the SMADP repo at `~/code/SMADP` (after the move back from
  `~/Downloads/Integration/SMADP` on 2026-06-09).
- The CI workflow lives at `.github/workflows/ci.yml`; the Pages deploy
  at `.github/workflows/deploy-pages.yml`. Touching one without the
  other is fine; they're independent jobs.
