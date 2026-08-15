#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -e .
fi
if [ ! -f frontend/dist/index.html ]; then
  command -v npm >/dev/null 2>&1 || { echo "Node.js wird einmalig zum Bauen der Oberfläche benötigt."; exit 1; }
  (cd frontend && npm install && npm run build)
fi
exec .venv/bin/python -m savox_giveaway
