# Tavus Test Harness (Python)

Single-CLI workflow to create Personas and Conversations against Tavus APIs. Keep it simple: a few commands to get started locally, plus an optional local webhook backend for tool callbacks.

## Getting started

```bash
# 1) Create a virtualenv and install deps
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2) Configure your API key
cp .env.example .env && ${EDITOR:-nano} .env   # set TAVUS_API_KEY
```

That’s it for setup. All commands are run from the repo root.

## Main commands (persona and conversation)

- Create or update a persona from the example config:
```bash
# Create
bin/tune.sh persona --config configs/persona/facilitator.example.json

# Update (PATCH) using fields from the same config
bin/tune.sh persona --config configs/persona/facilitator.example.json --update

# (Optional) Print the payload without sending
bin/tune.sh persona --config configs/persona/facilitator.example.json --print-payload --dry-run
```

- Create a conversation (choose one):
```bash
# From the example conversation config (safe test mode)
bin/tune.sh conversation --config configs/conversation/facilitator_kickoff.json --test-mode

# Or provide a persona by ID directly
bin/tune.sh conversation \
  --persona-id pe_XXXXXXXX \
  --name "Facilitator Demo" \
  --context "Let's kick off the session." \
  --document-retrieval-strategy balanced \
  --test-mode
```

- One‑shot flow (create/update persona → create conversation):
```bash
bin/scenarios/run_pair.sh \
  configs/persona/facilitator.example.json \
  configs/conversation/facilitator_kickoff.json \
  --update-persona --disable-test-mode
```

Logs for all requests and responses are saved in `logs/`.

## Backend for callbacks (3 terminals)

If you want tool callbacks (e.g., printing when the model calls a tool), run the included FastAPI webhook locally and expose it via a tunnel.

- Terminal A — Webhook backend
```bash
uvicorn app.main:app --reload --port 8000
```

- Terminal B — Public tunnel (and export callback URL)
```bash
ngrok http 8000
export WEBHOOK_URL="https://<your-ngrok-id>.ngrok.io/tavus/callback"
```

- Terminal C — Create persona and conversation
```bash
# One‑shot: persona update + conversation
bin/scenarios/run_pair.sh \
  configs/persona/facilitator.example.json \
  configs/conversation/facilitator_kickoff.json \
  --update-persona --disable-test-mode

# Or just create a conversation (uses WEBHOOK_URL by default)
bin/tune.sh conversation --config configs/conversation/facilitator_kickoff.json --test-mode
```

What to expect:
- The webhook terminal will print lines like `[Webhook] print_message: ...` when tools fire.
- Webhook logs are saved under `logs/webhook/<conversation_id>/` (events.jsonl and transcript.txt).

That’s all you need to run locally. When ready, you can deploy the webhook service and set the `callback_url` to your hosted endpoint.
