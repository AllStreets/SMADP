#!/usr/bin/env bash
# scripts/autopilot-loop.sh
# Single iteration of the autopilot loop. launchd invokes this every 300s.
set -euo pipefail

# Resolve repo root from this script's location.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

mkdir -p "$REPO_ROOT/state"

# Ensure the venv is on PATH; the plist points launchd at this script.
if [ -d "$REPO_ROOT/.venv" ]; then
  export PATH="$REPO_ROOT/.venv/bin:$PATH"
fi

# Load secrets from .env (OPENAI_API_KEY, GITHUB_TOKEN). The docs-only path
# needs these; if .env isn't present, the autopilot will record errors but
# the sandbox path keeps working.
if [ -f "$REPO_ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$REPO_ROOT/.env"
  set +a
fi

# Sandbox tick: plan + drain queue, promote completed runs.
smadp autopilot tick
smadp sandbox work --once --max 3

# Docs-only tick: drain the enrichment + pair-judge queue at a small batch
# size so each launchd invocation is bounded (~10-30s of LLM work) and the
# daily run cap (runs_per_day in config/autopilot.yaml) is respected.
smadp autopilot docs-only-tick --batch-size 3

# Scaffold tick: turn enriched docs-only profiles into Dockerfile + mcp.json
# adapters. Batch-size 10 drains the ~200-deep queue in ~7h instead of ~17h
# at the previous 3-per-fire rate. The skip-attempted list in
# state/scaffold_tick.jsonl ensures already-tried slugs aren't retried, and
# runs_per_day in config/autopilot.yaml still caps total daily spend.
smadp autopilot scaffold-tick --batch-size 10

# Daily briefing: regenerate report/YYYY-MM-DD.md so it reflects the catalog
# state after this tick's writes. Single-file rewrite, ~50ms, no LLM cost.
smadp autopilot daily-report

# Stats sync: keep the hardcoded counts in README.md and the banner SVG in
# sync with actual catalog/ contents (profile / verdict / sandbox-validated /
# adapter counts). Idempotent — only rewrites a file when its number changed,
# so the git_sync step below has nothing to commit on quiet ticks.
python3 "$REPO_ROOT/scripts/update-stats.py" \
  >>"$REPO_ROOT/state/autopilot.loop.stdout.log" 2>&1 || true

# ----------------------------------------------------------------------------
# GitHub sync. Push any new pending verdicts, operator approvals (pending →
# verdicts moves), rejections, and the regenerated daily report so the live
# site at allstreets.github.io/SMADP/ reflects today's state. We sync only
# the catalog dirs the operator-gate cares about (plus report/) so we don't
# accidentally commit unrelated working-tree changes. Failures are tolerated:
# the next tick retries; never crash the loop just because git is unhappy.
# ----------------------------------------------------------------------------
git_sync() {
  local log="$REPO_ROOT/state/autopilot.loop.stdout.log"
  # Sync every path the autopilot writes to so the live site mirrors the
  # operator's machine: pending/verdicts/rejected (operator gate), profiles
  # and _evidence (enrichment writes), adapters (scaffold writes), and
  # report (daily briefing). Notably absent: site/ and smadp/ — those are
  # operator-authored code edits and never get bot-committed.
  local sync_paths=(
    catalog/pending
    catalog/verdicts
    catalog/_rejected
    catalog/profiles
    catalog/_evidence
    adapters
    report
    README.md
    .github/assets/smadp-banner.svg
  )

  # The .env load earlier in this script sets GITHUB_TOKEN, which today is
  # malformed (a double-prefixed ghp_github_pat_… value) and causes git to
  # present a bad credential and get 403'd on push. Unset it within this
  # function so git falls through to the macOS keychain credentials the
  # operator's interactive shell uses. The enrich + scaffold steps above
  # still see whatever .env provided (they tolerate failure and fall back to
  # the 60 req/hr anonymous rate limit), so this scoping is intentional.
  unset GITHUB_TOKEN

  # Anything to push?
  local dirty
  dirty=$(git status --porcelain -- "${sync_paths[@]}" 2>/dev/null | head -1 || true)
  if [ -z "$dirty" ]; then
    echo "[git-sync] no catalog changes to push" >>"$log"
    return 0
  fi

  # Stage just the gated catalog dirs and report/.
  if ! git add -- "${sync_paths[@]}" >>"$log" 2>&1; then
    echo "[git-sync] git add failed; skipping push this tick" >>"$log"
    return 0
  fi

  # Count what we're actually committing for the message body.
  local stats
  stats=$(git diff --cached --shortstat -- "${sync_paths[@]}" 2>/dev/null | tr -d '\n')

  local subject="autopilot: catalog sync $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  local body
  body=$(printf 'Automated catalog sync from %s.\n\n%s' "$(hostname -s)" "$stats")

  GIT_AUTHOR_NAME="smadp-autopilot" \
  GIT_AUTHOR_EMAIL="autopilot@smadp.local" \
  GIT_COMMITTER_NAME="smadp-autopilot" \
  GIT_COMMITTER_EMAIL="autopilot@smadp.local" \
    git commit -m "$subject" -m "$body" >>"$log" 2>&1 \
      || { echo "[git-sync] commit failed" >>"$log"; return 0; }

  # Rebase any operator pushes that happened during this tick, then push.
  # --autostash protects against an in-progress edit by the operator on
  # unrelated files. On any failure we just leave the local commit in place
  # for the next tick to re-attempt.
  if ! git pull --rebase --autostash origin main >>"$log" 2>&1; then
    echo "[git-sync] rebase failed; will retry next tick" >>"$log"
    return 0
  fi
  if ! git push origin main >>"$log" 2>&1; then
    echo "[git-sync] push failed; will retry next tick" >>"$log"
    return 0
  fi
  echo "[git-sync] pushed catalog changes to GitHub" >>"$log"
}
git_sync
