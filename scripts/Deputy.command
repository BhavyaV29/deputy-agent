#!/bin/bash
# Deputy — double-click me (Finder) to launch the local web UI.
#
# Starts the loopback server once, opens your browser, and keeps running. If
# Deputy is already running it just opens that instance. Close this Terminal
# window or press Ctrl+C to stop.
#
# One-time setup so double-clicking works: `chmod +x scripts/Deputy.command`
# (already set in the repo). On first run macOS Gatekeeper may ask you to
# confirm — right-click → Open once to allow it.
set -euo pipefail

# Prefer an installed `deputy-app` (uv tool install / pipx). Otherwise fall back
# to running it straight from this repo checkout with uv.
if command -v deputy-app >/dev/null 2>&1; then
  exec deputy-app "$@"
fi

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"
if command -v uv >/dev/null 2>&1; then
  exec uv run deputy-app "$@"
fi

echo "Couldn't find 'deputy-app' or 'uv' on your PATH."
echo
echo "Install Deputy as a command:  uv tool install .    (run once, from the repo)"
echo "…or install uv first:         https://docs.astral.sh/uv/"
echo
read -r -p "Press Return to close this window…" _
exit 1
