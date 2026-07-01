# Correction & status — 2026-07-01

A one-time explainer covering what drifted off track and what is now repaired.
Hand-written and dated; not the autopilot's auto-generated daily briefing
(`report/2026-07-01.md`), which continues to regenerate every tick.

## What went off track

The judge was healthy the whole time — but the **public** catalog silently froze.

- **Published verdicts frozen for 10 days.** Every autopilot tick routes new
  docs-only verdicts into `catalog/pending/` (the operator-review gate); nothing
  auto-publishes. From 2026-06-21 to 06-30 the `smadp pending approve` gate was
  never run, so the published catalog sat at **1,352 verdicts** while the pending
  queue climbed **355 → 1,691**. The judge itself was fine — it produced roughly
  **94 new pending verdicts/day** the entire time.
- **The daily report hid it.** The briefing showed a bland `Verdicts: 1,352 (—)`
  with no signal that a large backlog was stranded, so a 10-day freeze read as
  business as usual.
- **Profiles mis-counted.** `daily_report.py` globbed only
  `catalog/profiles/*.json` and skipped `catalog/profiles/_unverified/`, so the
  report said **6,187** while `smadp lint`, `scripts/update-stats.py` and the site
  said **6,250**.
- **A stale red herring.** `state/judge_errors.jsonl` carries 165 OpenAI `429`
  quota errors — all from a single blip on **2026-06-18**. The judge produced
  normally before and after; the 429s did not cause the freeze.

## What is now repaired

- **Catalog unfrozen.** Published **524 docs-only verdicts at confidence ≥ 0.65**
  (stricter than the historical human bar — 63% of already-published verdicts sit
  at 0.55–0.65) and signed every one. Published verdicts **1,352 → 1,876**;
  `smadp lint` passes.
- **A freeze can't hide again.** The daily report now prints a loud
  **PUBLISH STALLED** banner (0 published today while the operator queue is deep)
  with the exact drain command, plus an "operator queue is deep" nudge past 300.
- **It won't refreeze unattended.** New high-confidence auto-publish lane
  (`auto_publish.docs_only_min_confidence: 0.70` in `config/autopilot.yaml`):
  docs-only verdicts at/above **0.70** are promoted straight to the public catalog
  (schema re-validated and BYOK-signed via the normal `approve` path); everything
  below stays gated for human review. Set the value to `0` to disable the lane.
- **Counts reconciled.** `daily_report.py` now counts `_unverified/` too — report,
  lint and site agree at **6,250 profiles**.

## Where things stand

The autopilot loop is running; the judge is producing; the high-confidence lane
keeps the public catalog growing without manual gate-tending; the remaining
~1,300 lower-confidence verdicts sit in `catalog/pending/` for operator review at
your discretion. Nothing is blocked.

---
*hand-written 2026-07-01; the daily `report/2026-07-01.md` regenerates every tick.*
