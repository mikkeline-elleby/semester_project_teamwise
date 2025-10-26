# Tavus Test Harness (Python)

Single-CLI workflow to create Personas and Conversations against Tavus APIs using small JSON templates or handy flags. No long bash invocations, everything goes through `bin/tune.sh`.

## Try it now
- One-time setup (Python venv, deps, and API key):
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && ${EDITOR:-nano} .env   # set TAVUS_API_KEY
```
- Run the full flow (create/update persona → inject persona_id → create conversation):
```bash
bin/scenarios/run_pair.sh configs/persona/life_coach.json configs/conversation/coach_intro.json --disable-test-mode
```
  - To update an existing persona by name (resolved from your persona config), add:
```bash
bin/scenarios/run_pair.sh configs/persona/life_coach.json configs/conversation/coach_intro.json --update-persona --disable-test-mode
```
Expected: you’ll see Status 200 responses and a Conversation URL printed. All payloads and responses are saved under `logs/`.

Optional (no API calls, just preview the JSON you’d send):
```bash
bin/tune.sh persona --config configs/persona/life_coach.json --print-payload --dry-run
bin/tune.sh conversation --config configs/conversation/coach_intro.json --print-payload --dry-run
```

### Facilitator quick start
- Create/update a persona that uses modular tools (summarize, notes, cluster), then run a kickoff conversation:
```bash
bin/scenarios/run_pair.sh \
  configs/persona/facilitator.example.json \
  configs/conversation/facilitator_kickoff.json \
  --update-persona --disable-test-mode
```
Tip: use `--print-payload --dry-run` on the persona command to see that tools are merged under `layers.llm.tools`.

## Setup
1) Python env and deps
   - Create/activate a venv and install requirements
2) API key
   - `cp .env.example .env` and set `TAVUS_API_KEY`

All commands below assume you run them from the repo root.

## Quick start
- One-shot: create or update persona and then create a conversation:
  - Run: `bin/scenarios/run_pair.sh configs/persona/life_coach.json configs/conversation/coach_intro.json --disable-test-mode`
  - To update the existing persona (resolved by name from your persona config):
    `bin/scenarios/run_pair.sh configs/persona/life_coach.json configs/conversation/coach_intro.json --update-persona --disable-test-mode`

- Or, run individual steps directly:
  - Persona: `bin/tune.sh persona --config configs/persona/life_coach.json`
  - Conversation: `bin/tune.sh conversation --config configs/conversation/coach_intro.json`

All runs are logged under `logs/` (payload, response, and meta).

## Commands reference

### One-shot workflow (create/update persona → inject persona_id → create conversation)
- Create fresh persona and run conversation:
```bash
bin/scenarios/run_pair.sh configs/persona/life_coach.json configs/conversation/coach_intro.json --disable-test-mode
```
- Update existing persona by ID and run conversation:
```bash
bin/scenarios/run_pair.sh configs/persona/life_coach.json configs/conversation/coach_intro.json \
  --update-persona --disable-test-mode --persona-id pe_XXXXXXXX
```
- Update existing persona by name (no ID needed; resolves by persona_name in persona config):
```bash
bin/scenarios/run_pair.sh configs/persona/life_coach.json configs/conversation/coach_intro.json --update-persona --disable-test-mode
```
Notes:
- This script does not require jq; it uses Python to parse configs/logs and will also resolve `persona_id` by `persona_name` via the Tavus API when needed.

### Persona (individual commands)
- Create from config:
```bash
bin/tune.sh persona --config configs/persona/life_coach.json
```
- Create with flags (no JSON):
```bash
bin/tune.sh persona \
  --persona-name "Life Coach" \
  --system-prompt "As a Life Coach..." \
  --pipeline-mode full \
  --default-replica-id r4317e64d25a \
  --layers-preset life_coach
```
- Add modular tools from files (by name in presets/layers/llm/tools or by file path):
```bash
bin/tune.sh persona \
  --persona-name "Assistant modular" \
  --system-prompt "Use tools." \
  --default-replica-id r4317e64d25a \
  --tools schedule_meeting,lookup_order_status

# or from a custom directory
bin/tune.sh persona \
  --persona-name "Assistant modular" \
  --system-prompt "Use tools." \
  --default-replica-id r4317e64d25a \
  --tools-dir my_tools \
  --tools book_flight.json,weather_lookup.json
```
- Update by ID (PATCH):
```bash
bin/tune.sh persona --config configs/persona/life_coach.json --update --persona-id pe_XXXXXXXX
```
- Update by name (no ID):
```bash
bin/tune.sh persona --config configs/persona/life_coach.json --update --target-persona-name "Life Coach"
```
- Print the request body without sending (dry run):
```bash
bin/tune.sh persona --config configs/persona/life_coach.json --print-payload --dry-run
```

### Conversation (individual commands)
- Create from config:
```bash
bin/tune.sh conversation --config configs/conversation/coach_intro.json
```
- Create with flags (no JSON):
```bash
bin/tune.sh conversation \
  --persona-id pe_XXXXXXXX \
  --name "Coaching Demo" \
  --context "Let's start with your main goal for this session." \
  --document-retrieval-strategy balanced \
  --test-mode
```
- Print the request body without sending (dry run):
```bash
bin/tune.sh conversation --config configs/conversation/coach_intro.json --print-payload --dry-run
```

## Templates you can copy
- Persona
  - `configs/persona/template.example.json` (minimal, runnable)
  - `configs/persona/template.example.jsonc` (commented guide; JSONC supported by the CLI)
  - Ready-made: `configs/persona/life_coach.json`

- Conversation
  - `configs/conversation/template.example.json` (minimal, runnable)
  - `configs/conversation/template.example.jsonc` (commented guide; JSONC supported by the CLI)
  - Ready-made: `configs/conversation/coach_intro.json`

## Unified CLI (bin/tune.sh)
Use a config file (recommended):
- Persona: `bin/tune.sh persona --config configs/persona/life_coach.json`
- Conversation: `bin/tune.sh conversation --config configs/conversation/coach_intro.json`

Or use flags (no JSON edits):
- Persona:
  - `bin/tune.sh persona --persona-name "Life Coach" --system-prompt "..." --pipeline-mode full --default-replica-id r4317e64d25a --layers-preset life_coach`
- Conversation:
  - `bin/tune.sh conversation --persona-id <persona_id> --name "Coaching Demo" --test-mode --context "Let's start with your main goal for this session."`

Tool files live under `presets/layers/llm/tools/`:
- `schedule_meeting.json` – function to schedule a meeting
- `lookup_order_status.json` – function to check an e-commerce order

You can include tools by name with `--tools schedule_meeting,lookup_order_status` (resolved under `presets/layers/llm/tools`),
or by passing file paths. Directory defaults:
- tools_dir defaults to `presets/layers/llm/tools`
- layers_dir defaults to `presets/layers`
You can override with `--tools-dir` and `--layers-dir` when needed.

### Modular layers (llm, tts, stt, perception)
- Define layer fragments once under `presets/layers/<kind>/` and reuse by name.
- Kinds: `llm`, `tts`, `stt`, `perception`.
- Default LLM: templates use `llm: "tavus_llama"`, which sets `model: "tavus-llama"`.
- Also available out of the box: `tavus_llama_4` (tavus-llama-4), `tavus_gpt_4o` (tavus-gpt-4o), `tavus_gpt_4o_mini` (tavus-gpt-4o-mini).
- Use with flags:
```bash
bin/tune.sh persona \
  --persona-name "Facilitator" \
  --system-prompt "You are TeamWise..." \
  --default-replica-id r4317e64d25a \
  --layers-dir presets/layers \
  --llm tavus_llama \
  --tts cartesia_sonic \
  --stt tavus_advanced \
  --perception basic
```
- Or via config (see `configs/persona/facilitator.example.json`):
```json
{
  "persona_name": "Meeting Facilitator",
  "system_prompt": "...",
  "default_replica_id": "r4317e64d25a",
  "layers_dir": "presets/layers",
  "llm": "tavus_llama",
  "tts": "cartesia_sonic",
  "stt": "tavus_advanced",
  "perception": "basic"
}
```
Notes:
- If you also provide a full `layers` object, modular layers will merge into it (LLM tools are appended).
- If `--layers-preset` is used, you can still override individual modular layers by flags or config.

## Payload shapes (aligned with Tavus API)

Persona (POST /v2/personas):
- Required: `persona_name`, `system_prompt` (required when `pipeline_mode` = `full`)
- Optional: `pipeline_mode` (default `full`), `context`, `default_replica_id`, `document_ids`, `document_tags`, `layers`, `objectives_id`, `guardrails_id`

Conversation (POST /v2/conversations):
- Provide either `persona_id` (preferred) or `replica_id`
- Optional: `callback_url`, `conversation_name`, `conversational_context`, `audio_only`, `custom_greeting`, `document_ids`, `document_tags`, `document_retrieval_strategy`, `memory_stores`, `test_mode`, `properties`

The CLI can auto-build `conversational_context` from meeting helper flags when using `tune.sh conversation`.

## Common pitfalls
- Don’t send `callback_url` when empty (null causes 400)
- Don’t include `language` in conversation (API rejects unknown field)
- If neither `persona_id` nor `replica_id` is provided, the CLI auto-picks a completed stock replica

## Notes
- Set `test_mode: true` on conversations to validate payloads without joining/billing
- Prefer `persona_id` with the persona’s `default_replica_id` (e.g., `r4317e64d25a`) instead of hard-coding a `replica_id` per conversation
- Responses and payloads are printed to the console and saved in `logs/`

## Do I need a backend for tools/objectives callbacks?
Short answer: only if you want Tavus to call your code asynchronously.

- Tools (aka function calling): In presets under `presets/layers/llm/tools/` you define the function schema the LLM can call. Executing those functions is your responsibility. There are two common patterns:
  - In-band execution (no backend): If your tool is purely virtual (e.g., “cluster ideas”, “summarize”) and the model can produce the result itself, you don’t need any server. The schema simply guides the model’s behavior, and nothing hits your infra.
  - Out-of-band execution (needs an endpoint): If tools are meant to trigger real actions in your systems (schedule a meeting, create a ticket, hit an internal API), you must provide code that receives the tool call and performs the action. Tavus supports this via `callback_url` on conversations and product-specific webhooks. You’ll need a reachable HTTPS endpoint.

- Objectives and guardrails: These are configured in Tavus and referenced by ID. You don’t need a backend just to attach them. However, if your objectives emit events or you want to observe progress/results asynchronously, set a `callback_url` and run a receiver.

How to test callbacks locally:
- Run the included FastAPI webhook with Uvicorn:
  - Start the server: `uvicorn app.main:app --reload --port 8000`
  - Export a URL for Tavus to call: `export WEBHOOK_URL="http://localhost:8000/tavus/callback"`
  - For internet reachability from Tavus, use a tunnel (e.g., `ngrok http 8000`) and set `WEBHOOK_URL` to the HTTPS ngrok URL (must end with `/tavus/callback`).
- The CLI will automatically use `WEBHOOK_URL` as the default `callback_url` if you don’t pass `--callback-url` or set it in config.

### Three-terminal local test (webhook + tunnel + conversation)
Use this to see tool calls and transcripts live while you talk to your replica.

- Terminal A — Webhook backend
  - `uvicorn app.main:app --reload --port 8000`
  - Watch for lines like `[Webhook] print_message: ...` when tools fire.

- Terminal B — Public tunnel
  - `ngrok http 8000` (or your tunneling tool of choice)
  - Copy the HTTPS URL and export it: `export WEBHOOK_URL="https://<your-ngrok-id>.ngrok.io/tavus/callback"`

- Terminal C — Create persona and conversation
  - Ensure your persona includes the sample tools (e.g., `print_message`). A ready-made persona is `configs/persona/facilitator.example.json` and a kickoff conversation is `configs/conversation/facilitator_kickoff.json`.
  - Create/update persona then create conversation:
    - One-shot: `bin/scenarios/run_pair.sh configs/persona/facilitator.example.json configs/conversation/facilitator_kickoff.json --update-persona --disable-test-mode`
    - Or individually with `bin/tune.sh conversation --persona-id <pe_xxx>`; omit `--callback-url` to let it use `WEBHOOK_URL`.
  - Open the printed `conversation_url` in a browser and say “test”. You should see `[Webhook] print_message: heard test` in Terminal A.

Where to find logs:
- All API requests/responses: `logs/*_{persona,conversation}_*/`
- Webhook events: `logs/webhook/<conversation_id>/events.jsonl`
- Readable transcript: `logs/webhook/<conversation_id>/transcript.txt`

If you don’t set any callback, everything still works synchronously: you can create personas and conversations, open the conversation link, and interact. You just won’t receive async events or tool invocations on your server.

### Presets guidance (functions, objectives, guardrails)
- Start with a clear `system_prompt` that states the agent’s role and constraints.
- Add function tools in the preset under `llm.tools` with JSON Schema parameters; the model will call them when appropriate.
- Wire in organizational policies via `guardrails_id` and outcomes via `objectives_id` (create these in the Tavus dashboard, then pass IDs either via config or flags `--guardrails-id` / `--objectives-id`).
- Keep presets small and focused; prefer composing capabilities (tools/perception/tts) over monolithic prompts.

Try it with a preset and guardrails/objectives:
```bash
bin/tune.sh persona \
  --persona-name "Assistant with Tools" \
  --system-prompt "You are a helpful assistant that can schedule meetings and check orders using provided tools." \
  --layers-preset assistant_with_tools \
  --default-replica-id r4317e64d25a \
  --objectives-id <OBJECTIVES_ID> \
  --guardrails-id <GUARDRAILS_ID>
```

### Modular tools (define once, reuse anywhere)
- Define each tool as a small JSON file under `presets/layers/llm/tools/`.
- Supported formats:
  - a single tool object: `{ "type": "function", "function": { ... } }`
  - an array of tools: `[ { ... }, { ... } ]`
  - an object with `tools`: `{ "tools": [ { ... } ] }`
- Add to a persona by name: `--tools schedule_meeting,lookup_order_status`
- Or via config file:
```json
{
  "persona_name": "Assistant modular",
  "system_prompt": "Use tools.",
  "default_replica_id": "r4317e64d25a",
  "tools": ["schedule_meeting", "lookup_order_status"],
  "tools_dir": "presets/layers/llm/tools"
}
```

Troubleshooting:
- 401 Unauthorized: ensure `TAVUS_API_KEY` is set in `.env` and you’re using the right venv
- 400 Unknown field `language`: remove `language` from conversation payload
- 400 `callback_url` may not be null: omit it entirely if you don’t have a real endpoint
- Persona didn’t join: make sure `test_mode` is false and open `conversation_url` in a browser (someone must join)

### Utilities
- Auto-set persona_id on a conversation config from the latest persona run and optionally disable test mode:
```bash
python bin/set_persona_id.py --config configs/conversation/coach_intro.json --from-latest-log --disable-test-mode
```
- Extract latest persona_id (two options):
  - With jq (if installed):
```bash
jq -r '.persona_id // .id' $(ls -1t logs/*_persona_create/response.json logs/*_persona_update/response.json | head -n1)
```
  - Pure Python (no jq required):
```bash
python -c "import glob,os,json; p=sorted(glob.glob('logs/*_persona_*/response.json'), key=lambda x: os.path.getmtime(x), reverse=True);\
print((lambda d: d.get('persona_id') or d.get('id') or '')(json.load(open(p[0])))) if p else None"
```
- List personas (table or JSON):
```bash
# table view, optionally filter by name
python bin/list_personas.py
python bin/list_personas.py --grep Coach

# raw JSON
python bin/list_personas.py --json
```
- Clean old logs (dry-run first):
```bash
bin/clean_logs.sh --dry-run
bin/clean_logs.sh --days 14
```

## Backend (FastAPI) for callbacks
Run a minimal FastAPI service to receive Tavus callbacks and route tool calls.

Local run:
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && ${EDITOR:-nano} .env   # set TAVUS_API_KEY; optional WEBHOOK_SHARED_SECRET

# Start API on :8000
uvicorn app.main:app --reload --port 8000

# Set callback to your local API (use a tunnel for public reachability)
export WEBHOOK_URL="http://localhost:8000/tavus/callback"
```

Security:
- Set `WEBHOOK_SHARED_SECRET` and configure your proxy to inject it in `x-webhook-secret`, or leave empty for local dev.

Handlers:
- Built-in examples for `summarize_discussion`, `take_meeting_notes`, `cluster_ideas`. Add more via `@register_tool("name")` in `app/main.py`.

Deploy:
- Containerize with Uvicorn/Gunicorn and deploy (Cloud Run/Fly.io/Azure Container Apps). Route `/tavus/callback` and set as the conversation `callback_url`.
