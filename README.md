# Tavus Test Harness

Kickstart personas and conversations against the Tavus API with the smallest setup possible.

## 1) Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Open `.env` and set your API key:

```
TAVUS_API_KEY=your_api_key_here
```

Optional convenience (skip if unsure):

```
# Webhook URL (used as default callback_url if set)
WEBHOOK_URL=https://<your-tunnel>/tavus/callback

# Defaults to reduce flags
TUNE_AUTO_RECORDING=false  # set true to auto-enable S3 recording defaults
```

## 2) Run a quick test

Create or update policies (objectives + guardrails) from presets, then create the example persona and a conversation:

```bash
source .venv/bin/activate
python bin/sync_policies.py      # one-time: creates/updates preset objectives & guardrails
bin/tune.sh persona --config configs/persona/facilitator.example.json
bin/tune.sh conversation --config configs/conversation/facilitator_kickoff.json
```

Tip: conversation name is derived from the file name if omitted; `callback_url` falls back to `WEBHOOK_URL`.

## 3) Optional: live webhook + tunnel

If you run a webhook receiver locally on port 8000, expose it and set `WEBHOOK_URL`:

```bash
ngrok http 8000
export WEBHOOK_URL="https://<your-ngrok>.ngrok-free.app/tavus/callback"
```

Then create a conversation:

```bash
source .venv/bin/activate
bin/tune.sh conversation --config configs/conversation/facilitator_kickoff.json
```

## 4) Optional: recording made easy

Add this to a conversation config to enable recording with project defaults:

```json
{
  "enable_recording": true
}
```

Or set `TUNE_AUTO_RECORDING=true` in `.env` to enable it automatically.

---
That’s it. For presets and tools, see `presets/README.md`. For examples, check `configs/persona/` and `configs/conversation/`.
