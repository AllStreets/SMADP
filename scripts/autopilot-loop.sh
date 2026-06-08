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
