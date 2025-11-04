#!/usr/bin/env bash
set -euo pipefail

# Quickstart: start webhook (uvicorn), launch ngrok, set WEBHOOK_URL in .env, create a test conversation, print URL.
# Optional args after -- are passed to the conversation command, e.g.:
#   bin/quickstart.sh -- --test-mode
#   bin/quickstart.sh -- --properties-file configs/conversation/recording.s3.julie.json

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"

PY=""
if [[ -x ".venv/bin/python" ]]; then
  PY=".venv/bin/python"
else
  if command -v python3 >/dev/null 2>&1; then PY=$(command -v python3); else PY=$(command -v python); fi
fi

# Ensure venv + deps
if [[ ! -x ".venv/bin/uvicorn" ]]; then
  echo "[quickstart] Creating virtualenv and installing requirements..."
  "$PY" -m venv .venv
  source .venv/bin/activate
  pip install -r requirements.txt >/dev/null
else
  source .venv/bin/activate
fi

# Check required tools
if ! command -v ngrok >/dev/null 2>&1; then
  echo "[quickstart] ngrok is required. Install from https://ngrok.com/download and ensure 'ngrok' is on PATH." >&2
  exit 1
fi

# Ensure API key present
if ! grep -q '^TAVUS_API_KEY=' .env 2>/dev/null; then
  echo "[quickstart] TAVUS_API_KEY missing in .env. Run: cp .env.example .env && edit .env" >&2
  exit 1
fi

# Start uvicorn if not already running on port 8000
UVICORN_PID=""
if ! nc -z 127.0.0.1 8000 >/dev/null 2>&1; then
  echo "[quickstart] Starting uvicorn on :8000..."
  .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload >/dev/null 2>&1 &
  UVICORN_PID=$!
  # give it a moment
  sleep 1
fi

# Start ngrok if local API not responding
NGROK_PID=""
if ! nc -z 127.0.0.1 4040 >/dev/null 2>&1; then
  echo "[quickstart] Starting ngrok http 8000..."
  ngrok http 8000 >/dev/null 2>&1 &
  NGROK_PID=$!
  # wait for API to come up
  for i in {1..20}; do
    sleep 0.5
    if nc -z 127.0.0.1 4040 >/dev/null 2>&1; then break; fi
  done
fi

cleanup() {
  code=$?
  if [[ -n "${NGROK_PID}" ]]; then kill ${NGROK_PID} >/dev/null 2>&1 || true; fi
  if [[ -n "${UVICORN_PID}" ]]; then kill ${UVICORN_PID} >/dev/null 2>&1 || true; fi
  exit $code
}
trap cleanup EXIT INT TERM

# Obtain public URL from ngrok API
PUBLIC_URL=""
get_public_url_jq() {
  curl -s http://127.0.0.1:4040/api/tunnels | jq -r '.tunnels[] | select(.proto=="https") | .public_url' | head -n1
}
get_public_url_py() {
  python - "$@" <<'PY'
import json, sys, urllib.request
try:
  data = json.loads(urllib.request.urlopen('http://127.0.0.1:4040/api/tunnels', timeout=2).read())
  urls = [t.get('public_url') for t in data.get('tunnels', []) if t.get('proto')=='https']
  print(urls[0] if urls else '')
except Exception:
  print('')
PY
}

for i in {1..40}; do
  if command -v jq >/dev/null 2>&1; then
    PUBLIC_URL=$(get_public_url_jq || true)
  else
    PUBLIC_URL=$(get_public_url_py || true)
  fi
  [[ -n "$PUBLIC_URL" ]] && break
  sleep 0.5
done

if [[ -z "$PUBLIC_URL" ]]; then
  echo "[quickstart] Failed to retrieve ngrok public URL from http://127.0.0.1:4040/api/tunnels" >&2
  exit 1
fi

CALLBACK_URL="${PUBLIC_URL%/}/tavus/callback"
echo "[quickstart] Using callback URL: ${CALLBACK_URL}"

# Persist in .env
bin/set_webhook_url.sh "$CALLBACK_URL"

# Create a conversation and print the URL
echo "[quickstart] Creating a test conversation..."
OUT=$(bin/tune.sh conversation "$@" 2>/dev/null || true)

if command -v jq >/dev/null 2>&1; then
  URL=$(printf '%s' "$OUT" | awk 'f{print} /^\{/ {f=1}' | jq -r '.conversation_url // empty')
else
  URL=$(printf '%s' "$OUT" | python -c "import sys,json,re;s=sys.stdin.read();m=re.search(r'\{[\\s\\S]*\}\s*$',s);print(json.loads(m.group(0)).get('conversation_url','')) if m else print('')")
fi

if [[ -z "$URL" ]]; then
  echo "[quickstart] Could not extract conversation_url. Raw output follows:" >&2
  printf '%s\n' "$OUT"
  exit 1
fi

echo "[quickstart] Conversation URL: $URL"
echo "[quickstart] Join the URL above. Press Ctrl+C here to stop ngrok/uvicorn."

# Keep processes alive until user exits
wait
