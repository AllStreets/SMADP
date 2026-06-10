#!/usr/bin/env bash
# scripts/smadp-api-serve.sh
#
# Wrapper that launchd uses to start the SMADP API with an operator token.
# launchd's EnvironmentVariables can only hold literal values, so we load the
# secret from ~/.smadp/api-token (mode 600, never in the repo or .env) here and
# export it before exec'ing the server.
#
# If the token file is absent, the server still starts but every write endpoint
# returns 503 (fail-safe) until a token is configured. See docs/SECURITY-NOTES.md.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

TOKEN_FILE="${SMADP_API_TOKEN_FILE:-$HOME/.smadp/api-token}"
if [ -f "$TOKEN_FILE" ]; then
  SMADP_API_TOKEN="$(tr -d '\n' < "$TOKEN_FILE")"
  export SMADP_API_TOKEN
fi

exec "$REPO_ROOT/.venv/bin/smadp" serve --host 127.0.0.1 --port 8000
