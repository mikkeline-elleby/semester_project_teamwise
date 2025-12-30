# TeamWise — Tavus Evaluation

Config-first toolkit for running and evaluating a Tavus-powered meeting facilitator (“TeamWise”).

It supports:
- Creating/updating Tavus personas and conversations from JSON + templates
- Syncing objectives/guardrails (“policies”) from reusable presets
- A FastAPI webhook server for logging and debugging live events
- Two small web demos: (1) Daily multi-speaker diarization/name mapping, (2) “blackout” mode that subscribes to replica audio without video

---

## Quick overview (what you run)

- `bin/sync_policies.py`: sync presets (objectives/guardrails/tools/layers) to Tavus
- `tune.py` / `bin/tune.sh`: create persona + conversation from configs/templates
- `uvicorn app.main:app`: webhook receiver + logging (optional but recommended)
- `web-demo/*`: optional helper UIs (diarization + blackout)

---

## 1) Setup (bash)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
````

Populate `TAVUS_API_KEY` in `.env`.

---

## 2) Sync policies & run a sample

Upsert objectives and guardrails defined under `presets/` then create the sample persona and a conversation:

```bash
source .venv/bin/activate
python bin/sync_policies.py
bin/tune.sh persona --config configs/persona/facilitator.example.json
bin/tune.sh conversation --config configs/conversation/facilitator_kickoff.json
```

Persona config uses `objectives_name` and `guardrails_name`; IDs are resolved automatically.

---

## 3) Webhook 

To receive live events:

Terminal A:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Terminal B (tunnel + persist):

```bash
ngrok http 8000
```

Terminal C (create conversation):

```bash
bin/tune.sh conversation --config configs/conversation/facilitator_kickoff.json
```

`bin/set_webhook_url.sh` writes `WEBHOOK_URL` into `.env`. Run it after the tunnel is up.

* Daily diarization helper (for multi-speaker): start your webhook (`uvicorn app.main:app`), create a conversation with `enable_closed_captions: true` (example: `configs/conversation/demo_v2_conv_cc.json`), then open `http://localhost:8001/web-demo/daily_diarization.html` in a browser (serve it with `python -m http.server 8001`). Paste the `conversation_url`, set webhook base (default `http://localhost:8000`), join, and watch `/roster/register` updates + per-speaker CC logs.

### Multi-speaker name recognition (Daily app-message path)

* Terminal A: run webhook server `uvicorn app.main:app --host 0.0.0.0 --port 8000`.
* Terminal B: serve the helper UI `python -m http.server 8001` and open `http://localhost:8001/web-demo/daily_diarization.html` (share LAN/ngrok URL if on different machines).
* Terminal C: create a CC-enabled conversation `python tune.py conversation --config configs/conversation/demo_v2_conv_cc.json` and copy `conversation_url`.
* In the helper (each participant):

  * Paste the same `conversation_url`.
  * Set webhook base (e.g., `http://localhost:8000`).
  * Enter your display name and Join. This posts `/roster/register` so the webhook knows who is speaking.
  * Leave one helper tab open to handle tool calls: it listens for Tavus `conversation.tool_call` events over Daily app-message and sends `conversation.echo` back (no REST echo required). When asked “what’s my name?”, it returns “You are <name>” for the active speaker.
* Notes: keep `ENABLE_TAVUS_ECHO` off; echoes go over Daily data channel. Multiple participants can join; pick one “controller” tab to avoid duplicate echoes. Use `/debug/roster/<conversation_id>` to inspect server-side roster if needed.

Webhook payloads and API request/response logs are stored under `logs/` (`logs/personas`, `logs/conversations`, `logs/webhook`).

---

## 4) Web demos 

This repo includes a folder `web-demo/` folder with two UIs that help during development and evaluation.

### A) Daily diarization helper (multi-speaker name recognition)

Purpose: map each human participant’s display name to the Daily roster via a simple UI, so the backend can associate closed captions / speaker turns with stable names.

Requirements:

* Webhook server running (`uvicorn app.main:app ...`)
* A CC-enabled conversation config (example: `configs/conversation/demo_v2_conv_cc.json`)
* Serving the demo UI locally (example: `python -m http.server 8001`)

Suggested flow:

* Terminal A: run webhook server

  * `uvicorn app.main:app --host 0.0.0.0 --port 8000`
* Terminal B: serve the helper UI and open it

  * `python -m http.server 8001`
  * open `http://localhost:8001/web-demo/daily_diarization.html`
* Terminal C: create a CC-enabled conversation and copy `conversation_url`

  * `python tune.py conversation --config configs/conversation/demo_v2_conv_cc.json`
* In the helper UI (for each participant):

  * paste the same `conversation_url`
  * set webhook base (default `http://localhost:8000`)
  * enter display name and Join (posts `/roster/register` so webhook knows who is speaking)

Notes:

* Keep `ENABLE_TAVUS_ECHO` off; echoes go over the Daily data channel.
* Multiple participants can join; pick one “controller” tab to avoid duplicate echoes.
* Use `/debug/roster/<conversation_id>` to inspect server-side roster if needed.

### B) “Blackout” replica UI (audio-only subscription)

Purpose: join the meeting and subscribe only to the replica’s audio stream (not video), producing a black screen while still allowing users to hear the replica.

This is useful for user studies where you want voice facilitation without visual presence.


---

## 5) Utilities

```bash
bin/demo_v2.sh         # quick end-to-end demo
bin/clean_logs.sh      # prune old logs (keeps 7 days by default)
```


---

## 6) Editing flow recap

1. Adjust presets (objectives, guardrails, layers, tools).
2. `python bin/sync_policies.py` to upsert changes.
3. Update persona config, then run persona & conversation commands.

See `presets/README.md` and `configs/README.md` for detailed schema guidance.

---

## 7) Repo map (what lives where)

This is a quick guide to the important folders/files and what they do. Focus on what you’ll edit and what calls Tavus.

```
.
├─ README.md                         # This guide
├─ requirements.txt                  # Python deps
├─ .env(.example)                    # TAVUS_API_KEY (+ optional WEBHOOK_URL)
├─ tune.py                           # Core CLI (persona / conversation create)
├─ util.py                           # Shared helpers: auth, HTTP, name→ID resolution, logging
├─ app/                              # FastAPI webhook server (persists events under logs/webhook)
│
├─ bin/                              # Helper scripts
│  ├─ tune.sh                        # Wrapper for tune.py
│  ├─ demo_v2.sh                     # Quick end-to-end sample flow
│  ├─ clean_logs.sh                  # Prune old logs
│  ├─ set_webhook_url.sh             # Writes WEBHOOK_URL into .env
│  ├─ sync_policies.py               # Upsert objectives & guardrails from presets/
│  └─ scenarios/                     # Scenario helpers
│
├─ configs/                          # Config-first inputs you run
│  ├─ persona/
│  └─ conversation/
│
├─ presets/                          # Reusable building blocks synced to Tavus
│  ├─ objectives/                    # Persona objectives (sync_policies)
│  ├─ guardrails/                    # Persona guardrails (sync_policies)
│  ├─ tools/                         # LLM tool specs (referenced by LLM presets)
│  └─ layers/                        # Model/audio/perception presets
│     ├─ llm/                        # LLM configs referencing tools
│     ├─ tts/                        # Text-to-speech presets
│     ├─ stt/                        # Speech-to-text presets
│     └─ perception/                 # Perception presets
│
├─ web-demo/                         # Browser helper UIs (diarization + blackout)
├─ logs/                             # All runtime logs (gitignored)
│  ├─ personas/                      # Persona create/update (payload/response/meta)
│  ├─ conversations/                 # Conversation create calls
│  └─ webhook/                       # Incoming webhook event payloads
│
└─ __pycache__/ / .venv / etc.       # Local environment / Python caches
```

### Key entrypoints hitting Tavus API

* `tune.py` (or `bin/tune.sh`): persona + conversation creation
* `bin/sync_policies.py`: upsert objectives & guardrails

### Typical flows

* Edit a persona config → `bin/tune.sh persona --config configs/persona/your.json`
* Edit a conversation config → `bin/tune.sh conversation --config configs/conversation/your.json`
* Add/update objectives or guardrails → edit under `presets/` then `python bin/sync_policies.py`
* Webhooks → run `uvicorn app.main:app`, expose via ngrok, then `bin/set_webhook_url.sh <public-url>`

---

## Final evaluation commands

The evaluation flow uses prompt templating for exactly 4 participants.

1. Update the participant list in `configs/participants.json`.

The file must contain exactly 4 participants. Supported shape:

```json
{ "participants": ["P1", "P2", "P3", "P4"] }
```

Then:

2. Preview-only (no API calls) to verify placeholders are filled:

```bash
bin/tune.sh persona \
  --persona-template configs/persona/template.example.json \
  --prompt-template configs/prompt_template.txt \
  --participants configs/participants.json \
  --persona-name "Facilitator" \
  --print-payload \
  --dry-run
```

3. Create the Tavus Persona (requires `TAVUS_API_KEY`):

```bash
bin/tune.sh persona \
  --persona-template configs/persona/template.example.json \
  --prompt-template configs/prompt_template.txt \
  --participants configs/participants.json \
  --persona-name "Facilitator" \
  --write-persona-id
```

Then take the `persona_id` (printed and saved in `personas/generated_replica_id.txt`) and input it in the conversation files.

We have two modes — one with camera, one without — choose the conversation according to the meeting type.

Reminder: when you join the Daily call as a human, keep your own camera/mic off. Start the meeting verbally when everyone has joined.

```bash
bin/tune.sh conversation --config configs/conversation/icebreaker_with_video.json
bin/tune.sh conversation --config configs/conversation/icebreaker_without_video.json
```

For task 2:

* Send the link of the Daily meeting configured under TeamWise and record it also.
* Join with camera and audio off — just share the slides and advance them after 2–6–6 minutes.
* Then send the link to the Google Form.

Communication can be done over a channel or email.

