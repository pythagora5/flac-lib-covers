#!/usr/bin/env bash
# Run the app straight from source (no build needed).
set -euo pipefail
cd "$(dirname "$0")/.."
[ -d .venv ] || scripts/setup.sh
exec .venv/bin/python -m flaccovers
