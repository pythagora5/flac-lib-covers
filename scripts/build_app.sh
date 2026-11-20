#!/usr/bin/env bash
# Build "dist/FLAC Cover Fixer.app" and optionally copy it to /Applications.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -d .venv ] || scripts/setup.sh

echo "Running tests…"
.venv/bin/python -m pytest -q

echo "Building app…"
python_bin=.venv/bin/python
"$python_bin" scripts/make_icon.py || echo "(icon step skipped)"
"$python_bin" -m PyInstaller --noconfirm --clean FLACCoverFixer.spec

APP="dist/FLAC Cover Fixer.app"
echo
echo "Built: $APP"
if [ "${1:-}" = "--install" ]; then
  rm -rf "/Applications/FLAC Cover Fixer.app"
  cp -R "$APP" /Applications/
  echo "Installed to /Applications/FLAC Cover Fixer.app"
fi
