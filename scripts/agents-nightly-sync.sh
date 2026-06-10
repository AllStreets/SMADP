#!/usr/bin/env bash
# scripts/agents-nightly-sync.sh
#
# Nightly ONEXUS-Agents -> SMADP research bridge. Runs in two bounded steps:
#
#   1. onexus-agents-smadp-sync: write fresh runnable agents as seed profiles
#      into catalog/profiles/_unverified/ (additive staging). Slugs SMADP
#      already has anywhere under catalog/profiles/ are skipped, and at most
#      AGENTS_SYNC_MAX_NEW new seeds are written per run.
#   2. smadp autopilot sync-onexus: promote up to AGENTS_SYNC_MAX_PROMOTE
#      staged seeds into catalog/profiles/ and enqueue them for the docs-only
#      enrichment judge — the same queue the 300s autopilot loop already drains.
#
# Independent of the NEXUS catalog pipeline. Own file-based kill switch
# (state/AGENTS_SYNC_DISABLED), checked by BOTH steps. Idempotent: re-running
# the same night writes nothing new once caps are hit.
#
# Scheduled once per day via launchd (com.smadp.agents-sync.plist) at 09:00
# local — comfortably after the upstream ONEXUS-Agents nightly refresh lands.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"
mkdir -p "$REPO_ROOT/state"
LOG="$REPO_ROOT/state/agents-sync.log"

ONEXUS_AGENTS_REPO="${ONEXUS_AGENTS_REPO:-$HOME/Downloads/Integration/ONEXUS-Agents}"
AGENTS_SYNC_MAX_NEW="${AGENTS_SYNC_MAX_NEW:-100}"
AGENTS_SYNC_MAX_PROMOTE="${AGENTS_SYNC_MAX_PROMOTE:-25}"

if [ -d "$REPO_ROOT/.venv" ]; then
  export PATH="$REPO_ROOT/.venv/bin:$PATH"
fi

stamp() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { echo "[$(stamp)] $*" >>"$LOG"; }

# Kill switch — checked here too so step 1 (the staging write) is also gated.
if [ -f "$REPO_ROOT/state/AGENTS_SYNC_DISABLED" ]; then
  log "disabled (state/AGENTS_SYNC_DISABLED present); skipping"
  exit 0
fi

if [ ! -d "$ONEXUS_AGENTS_REPO/catalog" ]; then
  log "ONEXUS-Agents catalog not found at $ONEXUS_AGENTS_REPO; skipping"
  exit 0
fi

# Step 1: stage new runnable agents (bounded; skip anything SMADP already has).
if command -v onexus-agents-smadp-sync >/dev/null 2>&1; then
  out=$(onexus-agents-smadp-sync \
    --catalog "$ONEXUS_AGENTS_REPO" \
    --out "$REPO_ROOT/catalog/profiles/_unverified" \
    --runnable-only \
    --skip-existing \
    --skip-existing-in "$REPO_ROOT/catalog/profiles" \
    --max-new "$AGENTS_SYNC_MAX_NEW" 2>&1) || { log "stage step failed: $out"; }
  log "stage: $out"
else
  log "onexus-agents-smadp-sync not installed; run docs/integrate/smadp.sh first"
fi

# Step 2: promote + enqueue (bounded; honours the same kill switch).
out=$(smadp autopilot sync-onexus --max-promote "$AGENTS_SYNC_MAX_PROMOTE" 2>&1) \
  || { log "promote step failed: $out"; exit 0; }
log "promote: $out"
