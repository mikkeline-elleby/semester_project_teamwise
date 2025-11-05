#!/usr/bin/env bash
set -euo pipefail

# Usage: bin/set_webhook_url.sh https://<your-tunnel>/tavus/callback
URL="${1:-}"
if [[ -z "${URL}" ]]; then
  echo "Usage: bin/set_webhook_url.sh https://<your-tunnel>/tavus/callback" >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  if [[ -f .env.example ]]; then
    cp .env.example .env
  else
    touch .env
  fi
fi

# Escape slashes and ampersands for sed
ESCAPED=$(printf '%s\n' "${URL}" | sed -e 's/[\\/&]/\\&/g')

if grep -q '^WEBHOOK_URL=' .env; then
  sed -i.bak -e "s/^WEBHOOK_URL=.*/WEBHOOK_URL=${ESCAPED}/" .env
else
  printf '\nWEBHOOK_URL=%s\n' "${URL}" >> .env
fi

echo "Set WEBHOOK_URL=${URL} in .env"
