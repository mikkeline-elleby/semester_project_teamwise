#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"

PY=${PY:-".venv/Scripts/python.exe"}
if [[ -z "${PY}" ]]; then
  if [[ -x ".venv/bin/python" ]]; then
    PY=".venv/bin/python"
  elif command -v python3 >/dev/null 2>&1; then
    PY="$(command -v python3)"
  else
    PY="$(command -v python)"
  fi
fi

# Ensure deps
if ! "$PY" -c "import requests, dotenv" >/dev/null 2>&1; then
  echo "Install deps: $PY -m pip install -r requirements.txt" >&2
  exit 1
fi

echo "[demo] Creating/Updating persona..."
bin/tune.sh persona --config configs/persona/demo_v2.json --update || bin/tune.sh persona --config configs/persona/demo_v2.json || true

echo "[demo] Creating conversation..."
ARGS=(conversation --config configs/conversation/demo_v2_conv.json --use-s3-recording-from-env --disable-test-mode)
if [[ -n "${REPLICA_ID:-}" ]]; then
  ARGS+=(--replica-id "${REPLICA_ID}")
else
  ARGS+=(--replica-id "r4317e64d25a")
fi
bin/tune.sh "${ARGS[@]}"
