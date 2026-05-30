#!/usr/bin/env bash
# scripts/autopilot-loop.sh
# Single iteration of the autopilot loop. launchd invokes this every 300s.
set -euo pipefail

# Resolve repo root from this script's location.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Ensure the venv is on PATH; the plist points launchd at this script.
if [ -d "$REPO_ROOT/.venv" ]; then
  export PATH="$REPO_ROOT/.venv/bin:$PATH"
fi

# tick: plan; sandbox work: drain queue + promote inline
smadp autopilot tick
smadp sandbox work --once --max-runs=3
