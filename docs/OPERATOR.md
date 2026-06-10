# Operator command reference

Everything you need to run SMADP day-to-day. Optimised for copy-paste.

Repo lives at `~/code/SMADP`. The venv binary is at
`~/code/SMADP/.venv/bin/smadp`. Most commands assume you've either `cd`'d
into the repo or set the alias below.

## One-time setup: shell alias

Add to `~/.zshrc` (or `~/.bashrc`):

```bash
alias smadp='~/code/SMADP/.venv/bin/smadp'
```

Then `source ~/.zshrc` (or open a new Terminal). After that, `smadp …`
works from any directory and every example below stays short.

---

## Pending review (the daily flow)

### See what's queued

```bash
# Everything
smadp pending list

# Just docs-only, high confidence (the easy approvals)
smadp pending list --tier docs-only --min-confidence 0.85

# Just sandbox-validated (the ones worth real attention)
smadp pending list --tier sandbox-validated

# Anything involving a specific agent
smadp pending list --pair-contains aider

# Only low-risk (composite < 0.4)
smadp pending list --max-composite 0.4

# Cap rows shown
smadp pending list --limit 20
```

### Inspect one before deciding

```bash
smadp pending show v_2026-06-10_aider__autogen_39a4f6
```

Prints the full sub-verdicts, citations, conditions, and mitigations.
Read it like a code review.

### Approve

```bash
# (a) One at a time, explicit key
smadp pending approve v_2026-06-10_aider__autogen_39a4f6

# (b) Bulk by filter with a cap
smadp pending approve --tier docs-only --min-confidence 0.85 \
  --max-composite 0.4 --limit 25 --yes

# (c) The full long tail of high-confidence, low-risk docs-only
smadp pending approve --tier docs-only --min-confidence 0.9 \
  --max-composite 0.3 --all --yes
```

`--yes` skips the confirmation prompt on batches. Single approvals don't
prompt.

### Reject (audit-logged, never silently deleted)

```bash
smadp pending reject v_2026-06-10_some_bad_pair_abc123 \
  --reason "Hallucinated capability claim; cursor doesn't expose MCP yet"
```

Rejected verdicts move to `catalog/_rejected/` with a `.reason.json`
sidecar.

### After approving or rejecting

Nothing else to do. Within five minutes the autopilot's next tick
auto-commits and pushes the moves to GitHub, which triggers a Pages
redeploy. Within roughly eight minutes the live site at
[allstreets.github.io/SMADP/pending/](https://allstreets.github.io/SMADP/pending/)
reflects the change.

If you want to skip the wait:

```bash
cd ~/code/SMADP && git add catalog/pending catalog/verdicts catalog/_rejected \
  && git commit -m "operator: manual sync" && git push
```

---

## Autopilot daemon

The launchd daemons run on their own schedules. You usually never touch
them, but here's how to inspect or restart.

### Status

```bash
launchctl list | grep smadp
# Columns: PID  LAST_EXIT  LABEL
# PID '-' means "not currently running" (normal between ticks).
# LAST_EXIT 0 means "last run was clean".
```

### Tail the live log

```bash
# autopilot loop output
tail -f ~/code/SMADP/state/autopilot.loop.stdout.log

# API server output
tail -f ~/code/SMADP/state/api.stdout.log
```

`Ctrl+C` exits. `tail -50` (without `-f`) shows the last 50 lines and exits.

### Force a tick to run right now

```bash
launchctl kickstart -k gui/$(id -u)/com.smadp.autopilot.loop
```

`-k` kills the running instance first if any. Useful when you just
approved something and want to push immediately without waiting for the
300-second timer.

### Restart the API daemon

```bash
launchctl kickstart -k gui/$(id -u)/com.smadp.api
```

### Stop / start the autopilot (when on vacation, debugging, etc.)

```bash
# Stop  (autopilot won't fire until reloaded)
launchctl unload ~/Library/LaunchAgents/com.smadp.autopilot.loop.plist

# Start again
launchctl load -w ~/Library/LaunchAgents/com.smadp.autopilot.loop.plist
```

### Hard cost limits

In `config/autopilot.yaml`:

- `runs_per_day: 200` (LLM-call cap)
- `dollar_cap_per_day: 20` (soft cap; the estimator increments per call)

Edit, save, and the next tick picks them up. No restart needed.

---

## Site (Astro)

```bash
cd ~/code/SMADP/site

# Run a static build locally (writes dist/)
pnpm run build

# Type-check + Astro lint
pnpm check

# Run the local dev server (live reload at http://localhost:4321/)
pnpm run dev

# Preview the production build locally (after pnpm run build)
pnpm run preview
```

The actual public site is built and deployed by the
`.github/workflows/deploy-pages.yml` workflow on every push to `main`.
You don't need to deploy by hand.

---

## Python / tests / linters

All from inside `~/code/SMADP`.

```bash
# Full pytest suite
.venv/bin/python -m pytest -q

# A specific test file
.venv/bin/python -m pytest tests/unit/test_chain_fixtures.py -q

# A specific test by name
.venv/bin/python -m pytest tests/unit/test_chain_fixtures.py::test_chain_validates -q

# Ruff lint + format (both are CI gates; run BOTH before pushing)
ruff check smadp tests
ruff format --check smadp tests

# Type-check
mypy smadp

# Catalog lint (schema + cross-reference checks)
smadp lint
```

If pytest complains about a missing package like `tenacity`, you're on
Anaconda's Python by accident. Use `.venv/bin/python` explicitly.

---

## Git + GitHub

```bash
cd ~/code/SMADP

# Working state
git status
git log --oneline -10

# CI / deploy status (last 5 runs)
gh run list --limit 5

# Watch a specific run
gh run watch <id>

# Watch the most recent Pages deploy
gh run watch $(gh run list --workflow="Deploy site to GitHub Pages" --limit 1 --json databaseId -q '.[0].databaseId')

# See if there's anything pending push
git status --porcelain | head
```

The autopilot pushes as `smadp-autopilot <autopilot@smadp.local>`. Your
commits stay attributed to you.

---

## Submit + scaffold + sandbox

```bash
# Submit an external agent for profiling
smadp submit <github-or-website-url>

# Scaffold a single MCP adapter (Dockerfile + mcp.json) for a slug
smadp scaffold <slug>

# One sandbox tick (planner + drain queue + promote completed runs)
smadp autopilot tick

# Drain N sandbox runs from the queue right now
smadp sandbox work --once --max 5

# Drain the docs-only enrichment + judge queue once
smadp autopilot docs-only-tick --batch-size 3

# Scaffold-tick: turn enriched profiles into adapter packages
smadp autopilot scaffold-tick --batch-size 10

# Regenerate today's daily briefing
smadp autopilot daily-report
```

---

## Keyboard shortcuts on the live site

Visible at `allstreets.github.io/SMADP/`.

| Shortcut | What it does |
|---|---|
| `/` | Focus the global search bar |
| `Cmd+K` / `Ctrl+K` | Same as `/` |
| Trackpad two-finger scroll on a chain topology | Zoom in/out smoothly |
| Trackpad pinch on a chain topology | Same (slightly more sensitive) |
| Click `revert` (bottom-right of the topology) | Reset zoom to 1:1 |
| Double-click anywhere on the topology | Same reset shortcut |
| `Esc` (when a nav dropdown is open) | Close it |
| `Cmd+Shift+R` / `Ctrl+Shift+R` | Hard refresh (bypass cache; useful right after a deploy) |

The Layout also auto-detects stale bfcache and a deploy-orphaned CSS
bundle and reloads once if either is detected, so most of the time you
won't need the hard refresh.

---

## Where things live

| Thing | Path |
|---|---|
| Source code | `~/code/SMADP/` |
| Python venv | `~/code/SMADP/.venv/bin/` |
| Catalog (the product) | `~/code/SMADP/catalog/` |
| Pending review queue | `~/code/SMADP/catalog/pending/` |
| Public verdicts | `~/code/SMADP/catalog/verdicts/` |
| Rejected (preserved) | `~/code/SMADP/catalog/_rejected/` |
| Autopilot logs | `~/code/SMADP/state/autopilot.loop.stdout.log` |
| API logs | `~/code/SMADP/state/api.stdout.log` |
| Daily briefings | `~/code/SMADP/report/YYYY-MM-DD.md` |
| Hard cost caps | `~/code/SMADP/config/autopilot.yaml` |
| launchd plists | `~/Library/LaunchAgents/com.smadp.*.plist` |
| ONEXUS source catalog | `~/Downloads/ONEXUS-Agents/` |
| Security gap doc | `~/code/SMADP/docs/SECURITY-NOTES.md` |
| Node 24 migration plan | `~/code/SMADP/docs/TODO-NODE24-MIGRATION.md` |
| This file | `~/code/SMADP/docs/OPERATOR.md` |

---

## Common gotchas

- **`smadp pending approve` doesn't push automatically.** It moves the
  file locally. The next autopilot tick (within five minutes) commits +
  pushes. If you want it on the live site immediately, run
  `git add catalog/pending catalog/verdicts && git commit -m … && git push`
  from the repo root, or `launchctl kickstart -k gui/$(id -u)/com.smadp.autopilot.loop`.
- **The `/pending` page on the live site can lag behind your local repo
  by up to eight minutes** (five for the tick, three for the Pages deploy).
- **`pnpm run build` succeeds even when `pnpm check` has TypeScript
  warnings.** CI runs both, so always run `pnpm check` before push.
- **CI gate hierarchy: `ruff check` *and* `ruff format --check`.** Running
  only the former misses formatting issues and CI fails.
- **Anaconda's `python` doesn't have `tenacity`** and other deps. Always
  use `.venv/bin/python` for tests.
- **The autopilot uses macOS keychain for git push, not the .env
  GITHUB_TOKEN** (the .env value is malformed). Both contexts (interactive
  shell and launchd) use the keychain. If push starts failing again,
  check the keychain entry for `github.com`.
- **The `Guard catalog/verdicts/` GitHub Actions workflow only fires on
  pull requests.** Direct pushes from your machine (operator or
  autopilot) pass through.
