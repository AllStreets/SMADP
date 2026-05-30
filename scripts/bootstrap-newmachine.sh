#!/usr/bin/env bash
# One-shot environment setup for SMADP on a fresh macOS install.
#
# Run from the repo root:  ./scripts/bootstrap-newmachine.sh
#
# This script is idempotent — safe to re-run if a step fails.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

say()  { printf "${GREEN}==>${NC} %s\n" "$*"; }
warn() { printf "${YELLOW}!! ${NC} %s\n" "$*"; }
die()  { printf "${RED}✗ ${NC} %s\n" "$*" >&2; exit 1; }

# --- Step 1: Homebrew -------------------------------------------------------
say "Checking Homebrew"
if ! command -v brew >/dev/null 2>&1; then
  warn "Homebrew not found. Install it from https://brew.sh and re-run this script."
  die "Aborting: Homebrew required"
fi

# --- Step 2: System deps ----------------------------------------------------
say "Installing system dependencies via brew (idempotent)"
brew install python@3.12 node pnpm 2>&1 | grep -v "already installed" || true

if ! command -v docker >/dev/null 2>&1; then
  warn "Docker CLI not detected. Install Docker Desktop from"
  warn "  https://www.docker.com/products/docker-desktop"
  warn "(Required for sandbox runs. The rest of this script will still work.)"
fi

# --- Step 3: Python venv ----------------------------------------------------
PY312="$(brew --prefix python@3.12)/bin/python3.12"
if [ ! -x "$PY312" ]; then
  die "python3.12 not found at $PY312 — check 'brew install python@3.12'"
fi

if [ ! -d ".venv" ]; then
  say "Creating .venv with Python 3.12"
  "$PY312" -m venv .venv
else
  say ".venv already exists — skipping creation"
fi

say "Installing Python deps (editable + dev extras)"
# shellcheck source=/dev/null
source .venv/bin/activate
pip install --upgrade pip wheel
pip install -e ".[dev]"

# --- Step 4: Frontend deps --------------------------------------------------
say "Installing report-site deps (pnpm + Playwright browsers)"
cd report
pnpm install
pnpm exec playwright install --with-deps chromium
cd "$REPO_ROOT"

# --- Step 5: Required directories ------------------------------------------
say "Ensuring runtime directories exist"
mkdir -p state report
mkdir -p "$HOME/.smadp" "$HOME/Library/Caches/smadp"
chmod 700 "$HOME/.smadp"

# --- Step 6: API keys -------------------------------------------------------
KEYS_FILE="$HOME/.smadp/keys.env"
if [ ! -f "$KEYS_FILE" ]; then
  say "Creating $KEYS_FILE template"
  cat > "$KEYS_FILE" <<'EOF'
# SMADP sandbox runs read this file.
# Fill in real values, do NOT commit this file.
OPENAI_API_KEY=
EOF
  chmod 600 "$KEYS_FILE"
  warn "Edit $KEYS_FILE and set OPENAI_API_KEY before running 'smadp sandbox work'."
else
  say "$KEYS_FILE already present"
fi

# --- Step 7: Smoke tests ----------------------------------------------------
say "Sanity-checking the install"
smadp --help >/dev/null && echo "    smadp CLI: ok"
pytest -q --no-header 2>&1 | tail -5

say "Bootstrap complete."
echo
echo "Next steps:"
echo "  1. Edit $KEYS_FILE if you haven't already."
echo "  2. Start Docker Desktop."
echo "  3. Read HANDOFF.md for current state and immediate next tasks."
echo "  4. Run a smoke test:  smadp autopilot tick  &&  smadp sandbox work --once"
