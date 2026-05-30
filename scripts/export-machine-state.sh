#!/usr/bin/env bash
# Bundle everything that lives outside the git repo into a single tar.gz
# you can AirDrop/USB/iCloud to the new MacBook.
#
# Usage:  ./scripts/export-machine-state.sh [output-path]
# Default output: ~/Desktop/smadp-machine-state.tar.gz

set -euo pipefail

OUT="${1:-$HOME/Desktop/smadp-machine-state.tar.gz}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Collecting machine-local state for SMADP migration"
mkdir -p "$TMP/state" "$TMP/dotsmadp" "$TMP/cache"

# 1. autopilot runtime state (coverage memory, today's budget)
if [ -d "$REPO_ROOT/state" ]; then
  cp -R "$REPO_ROOT/state/." "$TMP/state/" 2>/dev/null || true
  echo "    state/                       $(du -sh "$TMP/state" 2>/dev/null | cut -f1)"
fi

# 2. secrets
if [ -d "$HOME/.smadp" ]; then
  cp -R "$HOME/.smadp/." "$TMP/dotsmadp/" 2>/dev/null || true
  # Strip any junk macOS dup files like "keys.env "
  find "$TMP/dotsmadp" -name "*\ " -delete 2>/dev/null || true
  echo "    ~/.smadp/                    $(du -sh "$TMP/dotsmadp" 2>/dev/null | cut -f1)"
fi

# 3. past run transcripts (optional but cheap to include)
if [ -d "$HOME/Library/Caches/smadp" ]; then
  cp -R "$HOME/Library/Caches/smadp/." "$TMP/cache/" 2>/dev/null || true
  echo "    ~/Library/Caches/smadp/      $(du -sh "$TMP/cache" 2>/dev/null | cut -f1)"
fi

# 4. manifest so import script knows what's inside
cat > "$TMP/MANIFEST.txt" <<EOF
SMADP machine-state bundle
Exported: $(date -u +%Y-%m-%dT%H:%M:%SZ)
From host: $(hostname)
Source repo: $REPO_ROOT
Last git commit: $(cd "$REPO_ROOT" && git rev-parse HEAD 2>/dev/null || echo "unknown")

Layout:
  state/        -> SMADP/state/
  dotsmadp/     -> ~/.smadp/
  cache/        -> ~/Library/Caches/smadp/
EOF

echo "==> Compressing"
mkdir -p "$(dirname "$OUT")"
tar -czf "$OUT" -C "$TMP" .

echo
echo "Bundle ready: $OUT"
echo "Size: $(du -sh "$OUT" | cut -f1)"
echo
echo "Next steps:"
echo "  1. AirDrop / iCloud / USB this file to the new MacBook"
echo "  2. Clone the repo on the new machine"
echo "  3. Run: ./scripts/import-machine-state.sh <path-to-bundle>"
echo "  4. Run: ./scripts/bootstrap-newmachine.sh"
