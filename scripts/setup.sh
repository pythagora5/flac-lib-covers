#!/usr/bin/env bash
# Create .venv with Homebrew Python and install everything needed.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=""
for cand in /opt/homebrew/opt/python@3.13/bin/python3.13 /opt/homebrew/bin/python3 python3; do
  if command -v "$cand" >/dev/null 2>&1; then PY="$cand"; break; fi
done
if [ -z "$PY" ]; then
  echo "Python not found. Install it with:  brew install python@3.13" >&2
  exit 1
fi
echo "Using $($PY --version) at $PY"

if [ ! -d .venv ]; then
  "$PY" -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip >/dev/null
.venv/bin/python -m pip install -r requirements-dev.txt
echo "Setup complete."
