#!/usr/bin/env bash
# Unpack a bundle created by export-machine-state.sh into the right places.
#
# Usage:  ./scripts/import-machine-state.sh <bundle.tar.gz>

set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: $0 <path-to-smadp-machine-state.tar.gz>" >&2
  exit 1
fi

BUNDLE="$1"
if [ ! -f "$BUNDLE" ]; then
  echo "Bundle not found: $BUNDLE" >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "==> Unpacking bundle"
tar -xzf "$BUNDLE" -C "$TMP"

if [ -f "$TMP/MANIFEST.txt" ]; then
  echo
  cat "$TMP/MANIFEST.txt"
  echo
fi

echo "==> Restoring files"

# 1. state/
if [ -d "$TMP/state" ]; then
  mkdir -p "$REPO_ROOT/state"
  cp -R "$TMP/state/." "$REPO_ROOT/state/"
  echo "    -> $REPO_ROOT/state/"
fi

# 2. ~/.smadp/
if [ -d "$TMP/dotsmadp" ]; then
  mkdir -p "$HOME/.smadp"
  cp -R "$TMP/dotsmadp/." "$HOME/.smadp/"
  chmod 700 "$HOME/.smadp"
  [ -f "$HOME/.smadp/keys.env" ] && chmod 600 "$HOME/.smadp/keys.env"
  echo "    -> $HOME/.smadp/  (perms locked down)"
fi

# 3. ~/Library/Caches/smadp/
if [ -d "$TMP/cache" ]; then
  mkdir -p "$HOME/Library/Caches/smadp"
  cp -R "$TMP/cache/." "$HOME/Library/Caches/smadp/"
  echo "    -> $HOME/Library/Caches/smadp/"
fi

echo
echo "Import complete."
echo "Next: ./scripts/bootstrap-newmachine.sh"
