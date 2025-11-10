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
# Webhook URL (quickstart will set this automatically when tunneling)
WEBHOOK_URL=https://<your-tunnel>/tavus/callback

# Defaults to reduce flags
TUNE_AUTO_RECORDING=false  # set true to auto-enable S3 recording defaults
```

## 2) Run a quick test

Create or update the example persona, then create a conversation:

```bash
source .venv/bin/activate
bin/tune.sh persona --config configs/persona/facilitator.example.json
bin/tune.sh conversation --config configs/conversation/facilitator_kickoff.json
```

Tip: conversation name is derived from the file name if omitted; callback_url falls back to `WEBHOOK_URL`.

## 3) Optional: live webhook + tunnel

Terminal A – start the local webhook:
```bash
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Terminal B – start a tunnel and persist the callback URL:
```bash
ngrok http 8000
bin/set_webhook_url.sh "https://<your-ngrok>.ngrok-free.app/tavus/callback"
```

Terminal C – create a conversation:
```bash
source .venv/bin/activate
bin/tune.sh conversation --config configs/conversation/facilitator_kickoff.json
```

## 4) Optional: recording made easy

Add this to a conversation config to enable recording with project defaults:

```json
{
<<<<<<< HEAD
  "enable_recording": true
=======
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

### Objectives and Guardrails for a Meeting Facilitator

Use a practical Objective and Guardrail aligned with facilitator tasks:

- Objective: "Facilitator Core Objective" — by end of meeting, ensure:
  - Agenda coverage and timeboxed discussion
  - Inclusive participation (no one dominates)
  - 1–3 decisions captured with owners
  - Action items: owner, due date, and success metric

- Guardrail: "Facilitator Safety Policy" — always:
  - Avoid medical, legal, or financial advice
  - Do not collect sensitive data (SSN, passport, payment)
  - De-escalate unsafe or toxic content and offer to loop in a human
  - Maintain professional, inclusive tone

Attach them to your persona by ID:

```bash
bin/tune.sh persona \
  --config configs/persona/facilitator.example.json \
  --update \
  --objectives-id ob_XXXXXXXX \
  --guardrails-id gr_YYYYYYYY
```

Or by NAME (auto-resolve):

```bash
bin/tune.sh persona \
  --config configs/persona/facilitator.example.json \
  --update \
  --objectives-name "Facilitator Core Objective" \
  --guardrails-name "Facilitator Safety Policy"
```

Tip: a ready-to-run example is in `configs/persona/facilitator.with_policies.json` (uses the names above). Run:

```bash
bin/tune.sh persona --config configs/persona/facilitator.with_policies.json --update
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
- Run the included minimal webhook receiver:
  - `python bin/webhook_server.py --port 8080 --path /tavus/callback`
  - Export a URL for Tavus to call: `export WEBHOOK_URL="http://<your-host-or-tunnel>:8080/tavus/callback"`
  - For internet reachability from Tavus, use a tunnel (e.g., `ngrok http 8080`) and set `WEBHOOK_URL` to the HTTPS ngrok URL.
- The CLI will automatically use `WEBHOOK_URL` as the default `callback_url` if you don’t pass `--callback-url` or set it in config.

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
>>>>>>> origin/feat/objectives-guardrails
}
```

Or set `TUNE_AUTO_RECORDING=true` in `.env` to enable it automatically.

---
That’s it. For presets and tools, see `presets/README.md`. For examples, check `configs/persona/` and `configs/conversation/`.
