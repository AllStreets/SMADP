# SMADP daily catalog briefings

Auto-generated end-of-tick reports from the autopilot loop. Modeled on the
[ONEXUS-Agents nightly reports](https://github.com/AllStreets/ONEXUS-Agents/tree/main/reports)
— a quick, scannable summary of what changed in the catalog without having
to walk the git log.

Each file at `report/YYYY-MM-DD.md` carries:

- **Totals** — current profile / verdict / adapter / pending counts, with
  day-over-day deltas.
- **Tier breakdown** — how many profiles and verdicts sit at each
  evidence_level (`sandbox-validated` ≻ `profile-verified` ≻ `docs-only`
  ≻ `unverified-profile`).
- **Activity today (UTC)** — new verdicts created today, sandbox runs
  (pass / fail), autopilot budget consumed.
- **Severity distribution** — sub-verdict severities across the verdicts
  created today, so trend shifts (e.g. more critical findings on a new
  adapter batch) are visible without opening files.
- **Pipeline health** — queue depths, operator review backlog, judge
  errors logged lifetime.

## Schedule

The autopilot loop (`scripts/autopilot-loop.sh`) runs every 300s; the last
step of every tick is `smadp autopilot daily-report`, which **regenerates
that day's report file**. So `report/<today>.md` always reflects the
state of disk within ~5 minutes.

## Manual run

```bash
smadp autopilot daily-report
# writes report/$(date -u +%F).md
```

That's all there is. The catalog is the source of truth; this folder is
the lobby version.
