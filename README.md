# Tavus Test Harness

## Daily-Owned Rooms with Tavus Replica (Pipecat)

This project now supports creating Daily rooms owned by you (not Tavus) and injecting a Tavus replica as a bot participant using Pipecat.

### Setup
1.  Install dependencies: `pip install -r requirements.txt`
2.  Set environment variables in `.env`:
    *   `DAILY_API_KEY`: Your Daily.co API key.
    *   `DAILY_DOMAIN`: Your Daily.co domain (e.g., `my-domain`).
  *   `CARTESIA_API_KEY`: Cartesia API key for TTS (required).
  *   `CARTESIA_VOICE_ID`: Cartesia voice identifier (required).
  *   `CARTESIA_MODEL`: Optional Cartesia model override.
  *   `CARTESIA_SAMPLE_RATE`: Optional output sample rate (defaults to `24000`).
    *   `TAVUS_API_KEY`: Your Tavus API key.
    *   `TAVUS_REPLICA_ID`: The ID of the Tavus replica to use.

Cartesia replaces the previous OpenAI TTS dependency; no OpenAI credentials are required.

### Usage
1.  **Start Backend**: `uvicorn app.main:app --reload`
2.  **Open Frontend**: Open `web-demo/daily_diarization.html`.
3.  **Create Public Room**: Click "Create Public Room". This generates a public Daily room and tokens for the Host and Bot.
4.  **Share Link**: Copy the "Share Link" and send it to participants. They can join without a token.
5.  **Join as Host**: Click "Join as Host (Owner)". You will have admin privileges (recording, ejection).
6.  **Start Replica (Task 1)**: Click "Start Replica". The bot joins.
7.  **Eject Replica (Task 2)**: Click "Eject Replica". The bot is removed from the call, but the room remains active for humans.
8.  **Recording**: Use the "Record" button to toggle cloud recording.

#### Verifying replica media output
1. Export `DEBUG_MEDIA=1` before starting the bot to enable Tavus → Daily frame counters in `bot/worker.py` logs.
2. Start the bot and wait for the "Daily transport joined" log. Within a few seconds you should see `[MEDIA] tavus->daily` heartbeats with non-zero audio/video counts.
3. In the Daily UI (or the helper page), confirm a participant named "Replica" appears with an active tile.
4. Unmute the call audio and verify you can hear the welcome message or any prompted speech from the replica.
5. If the tile is blank or silent, inspect the debug counters: zero video frames implies Tavus is not producing video, zero audio frames indicates Cartesia output stalled, and non-zero counters with a blank tile points to a Daily/JS rendering issue.

### Architecture
*   **Backend (`app/main.py`)**: Manages public Daily room creation, token generation (Host/Bot), and bot process lifecycle.
*   **Bot (`bot/worker.py`)**: A Pipecat-based worker that connects to Daily, uses Cartesia for streaming TTS, and feeds the audio into `TavusVideoService` to render the avatar.
*   **Frontend**: Custom Daily.js UI for managing the session.

---

Minimal harness for creating personas and conversations against the Tavus API using config files plus a small helper script set.

## 1) Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Populate `TAVUS_API_KEY` in `.env`.

## 2) Sync policies & run a sample

Upsert objectives and guardrails defined under `presets/` then create the sample persona and a conversation:

```bash
source .venv/bin/activate
python bin/sync_policies.py
bin/tune.sh persona --config configs/persona/facilitator.example.json
bin/tune.sh conversation --config configs/conversation/facilitator_kickoff.json
```

Persona config uses `objectives_name` and `guardrails_name`; IDs are resolved automatically.

## 3) Webhook (optional)

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

- Daily diarization helper (for multi-speaker): start your webhook (`uvicorn app.main:app`), create a conversation with `enable_closed_captions: true` (example: `configs/conversation/demo_v2_conv_cc.json`), then open `http://localhost:8001/web-demo/daily_diarization.html` in a browser (serve it with `python -m http.server 8001`). Paste the `conversation_url`, set webhook base (default `http://localhost:8000`), join, and watch `/roster/register` updates + per-speaker CC logs.

### Multi-speaker name recognition (Daily app-message path)
- Terminal A: run webhook server `uvicorn app.main:app --host 0.0.0.0 --port 8000`.
- Terminal B: serve the helper UI `python -m http.server 8001` and open `http://localhost:8001/web-demo/daily_diarization.html` (share LAN/ngrok URL if on different machines).
- Terminal C: create a CC-enabled conversation `python tune.py conversation --config configs/conversation/demo_v2_conv_cc.json` and copy `conversation_url`.
- In the helper (each participant):
  - Paste the same `conversation_url`.
  - Set webhook base (e.g., `http://localhost:8000`).
  - Enter your display name and Join. This posts `/roster/register` so the webhook knows who is speaking.
  - Leave one helper tab open to handle tool calls: it listens for Tavus `conversation.tool_call` events over Daily app-message and sends `conversation.echo` back (no REST echo required). When asked “what’s my name?”, it returns “You are <name>” for the active speaker.
- Notes: keep `ENABLE_TAVUS_ECHO` off; echoes go over Daily data channel. Multiple participants can join; pick one “controller” tab to avoid duplicate echoes. Use `/debug/roster/<conversation_id>` to inspect server-side roster if needed.

## 4) Utilities

```bash
bin/demo.sh            # quick end‑to‑end demo
bin/clean_logs.sh      # prune old logs (keeps 7 days by default)
python bin/documents.py create --url https://example.com/document.pdf --name "Important" --tag meeting --prop department sales
python bin/documents.py list
```

Webhook payloads and API request/response logs are stored under `logs/` (`logs/personas`, `logs/conversations`, `logs/webhook`).

## 5) Editing flow recap
1. Adjust presets (objectives, guardrails, layers, tools).
2. `python bin/sync_policies.py` to upsert changes.
3. Update persona config, then run persona & conversation commands.

See `presets/README.md` and `configs/README.md` for detailed schema guidance.

## 6) Repo map (what lives where)

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
│  ├─ demo.sh                        # Quick end‑to‑end sample flow
│  ├─ clean_logs.sh                  # Prune old logs
│  ├─ set_webhook_url.sh             # Writes WEBHOOK_URL into .env
│  ├─ sync_policies.py               # Upsert objectives & guardrails from presets/
│  ├─ documents.py                   # Ad‑hoc create/list documents
│  └─ sync_documents.py              # Upsert documents from presets/documents/
│
├─ configs/                          # Config‑first inputs you run
│  ├─ persona/
│  └─ conversation/
│
├─ presets/                          # Reusable building blocks synced to Tavus
│  ├─ objectives/                    # Persona objectives (sync_policies)
│  ├─ guardrails/                    # Persona guardrails (sync_policies)
│  ├─ tools/                         # LLM tool specs (referenced by LLM presets)
│  ├─ documents/                     # Document presets (sync_documents)
│  │  └─ attention_is_all_you_need.json
│  └─ layers/                        # Model/audio/perception presets
│     ├─ llm/                        # LLM configs referencing tools
│     ├─ tts/                        # Text‑to‑speech presets
│     ├─ stt/                        # Speech‑to‑text presets
│     └─ perception/                 # Perception presets
│
├─ logs/                             # All runtime logs (gitignored)
│  ├─ personas/                      # Persona create/update (payload/response/meta)
│  ├─ conversations/                 # Conversation create calls
│  └─ webhook/                       # Incoming webhook event payloads
│
└─ __pycache__/ / .venv / etc.       # Local environment / Python caches
```


### Key entrypoints hitting Tavus API
- `tune.py` (or `bin/tune.sh`): persona + conversation creation
- `bin/sync_policies.py`: upsert objectives & guardrails
- `bin/sync_documents.py`: upsert documents (name→ID resolution, property sanitization)
- `bin/documents.py`: ad‑hoc document create/list

### Typical flows
- Edit a persona config → `bin/tune.sh persona --config configs/persona/your.json`
- Edit a conversation config → `bin/tune.sh conversation --config configs/conversation/your.json`
- Add/update objectives or guardrails → edit under `presets/` then `python bin/sync_policies.py`
- Add/update documents → place JSON in `presets/documents/` then `python bin/sync_documents.py`
- Webhooks → run `uvicorn app.main:app`, expose via ngrok, then `bin/set_webhook_url.sh <public-url>`

If you’d like more examples (e.g., composing multiple documents or layering tools), open an issue or drop a comment.
