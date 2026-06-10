# ONEXUS-Agents -> SMADP nightly integration

How fresh runnable agents from the ONEXUS-Agents catalog become researched
SMADP safety profiles, unattended, with caps and a kill switch.

## Flow

```
ONEXUS-Agents catalog refresh (upstream, nightly ~13:00 UTC)
        |
        v  (once a day, 09:00 local, com.smadp.agents-sync.plist)
scripts/agents-nightly-sync.sh
   step 1: onexus-agents-smadp-sync  ->  catalog/profiles/_unverified/*.json
           (additive staging; skips slugs already under catalog/profiles/;
            at most AGENTS_SYNC_MAX_NEW new seeds per run)
   step 2: smadp autopilot sync-onexus
           promote <= AGENTS_SYNC_MAX_PROMOTE highest-scored staged seeds
           into catalog/profiles/ AND append work items to
           state/docs_only_queue.jsonl
        |
        v  (existing 300s loop, com.smadp.autopilot.loop.plist)
smadp autopilot docs-only-tick  ->  enrichment judge upgrades each promoted
   profile to docs-only tier; pair judges write verdicts to catalog/pending/
        |
        v  (operator gate, unchanged)
smadp pending approve  ->  catalog/verdicts/  ->  Pages site
```

`catalog/profiles/_unverified/` is a staging buffer: the autopilot planners
glob `catalog/profiles/*.json` non-recursively, so a seed only enters
research once `sync-onexus` promotes it (a move, not a copy — each slug
lives in exactly one place, keeping `smadp lint`'s duplicate check green).

## Caps (volume safety)

| Knob | Default | Effect |
|---|---|---|
| `AGENTS_SYNC_MAX_NEW` | 100 | new seeds staged per run |
| `AGENTS_SYNC_MAX_PROMOTE` | 25 | seeds promoted into research per run |

Deferred candidates are counted in the log, not dropped; they remain
eligible the next run. One bad upstream night therefore cannot flood SMADP
research — intake is bounded on both sides.

## Kill switch

```bash
touch ~/code/SMADP/state/AGENTS_SYNC_DISABLED   # pause (both steps skip)
rm    ~/code/SMADP/state/AGENTS_SYNC_DISABLED    # resume
```

This switch is independent of the NEXUS pipeline's `AGENTS_SYNC_ENABLED`
GitHub Actions variable. The two integrations share no trigger, no state,
and no credentials: a failure or pause in one cannot affect the other.

## Install

```bash
cp scripts/launchd/com.smadp.agents-sync.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.smadp.agents-sync.plist
```

Run it by hand any time:

```bash
ONEXUS_AGENTS_REPO=~/Downloads/Integration/ONEXUS-Agents \
  bash scripts/agents-nightly-sync.sh
tail state/agents-sync.log
```

## Self-halt conditions

- Kill switch file present -> both steps no-op.
- ONEXUS-Agents catalog directory missing -> log and exit 0 (no partial work).
- `onexus-agents-smadp-sync` not installed -> step 1 logs and is skipped;
  step 2 still drains anything already staged.
- A promote/enqueue error -> logged, exit 0 (the 300s loop and the next
  nightly run are unaffected).
