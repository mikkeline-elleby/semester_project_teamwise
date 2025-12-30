# Configs

This folder holds example configuration files consumed by the harness. Three categories:
- Persona configs (`configs/persona/*.json`) define replica behavior and reference objectives & guardrails by name.
- Conversation configs (`configs/conversation/*.json`) define conversation creation parameters.
- Template examples (`*.example.json` / `*.example.jsonc`) you can copy and adapt.

The flow is configuration-only: put what you need in the JSON files, then run the helper scripts. No CLI flags are required.

## Persona config essentials

Minimum useful fields:
- persona_name
- system_prompt
- objectives_name (preferred over objectives_id)
- guardrails_name (preferred over guardrails_id)
- layers: either inline structure or references to layer fragments (llm / tts / stt / perception) under `presets/layers/`.

Example (abbreviated):
```json
{
  "persona_name": "Facilitator",
  "system_prompt": "You help teams run efficient kickoff meetings.",
  "objectives_name": "facilitator_core",
  "guardrails_name": "facilitator_safety",
  "layers": {
    "llm": { "llm": "tavus-gpt-oss" },
    "tts": { "tts_engine": "cartesia", "tts_model_name": "sonic" },
    "stt": { "stt_engine": "tavus-advanced" },
    "perception": { "perception_model": "raven-0" }
  }
}
```

Optional fields you can add as needed:
- context: Extra background.
- document_ids / document_tags
- default_replica_id (rarely needed if using persona flows)

## Conversation config essentials

Minimum useful fields:
- persona_id (preferred) OR replica_id
- conversation_name
- conversational_context (or rely on persona system_prompt alone)
- test_mode (false when you actually want the agent to join)

Example:
```json
{
  "persona_id": "<filled after persona creation>",
  "conversation_name": "Kickoff Meeting",
  "conversational_context": "Facilitate a brief kickoff: clarify goals, roles, and next steps.",
  "test_mode": false
}
```

Optional fields:
- document_ids / document_tags
- callback_url (only include if you have a real webhook URL)
- memory_stores

Avoid including unsupported or empty fields (e.g., null `callback_url`).

## Objectives & Guardrails

Names resolve automatically (via an API list + case-insensitive match). Ensure you run:
```bash
python bin/sync_policies.py
```
after editing any preset under `presets/objectives/` or `presets/guardrails/`.

## Layer fragments

Instead of verbose inline structures you can reference minimal fragments by name. For example:
```json
{ "layers": { "llm": { "llm": "tavus-gpt-oss" } } }
```
The harness expands `llm` into a full model definition using the fragment in `presets/layers/llm/`.

## Tools

Function tools live in `presets/tools/`. Copy or compose them inside the LLM layer fragment; they are plain JSON definitions. No command-line merging flags remain.

## Webhook URL

If you use a live webhook, set `WEBHOOK_URL` in `.env` via the helper script (see root README). Omit `callback_url` in configs unless it’s valid.

## Editing flow recap
1. Edit presets (objectives, guardrails, layers, tools) as needed.
2. Run `python bin/sync_policies.py` to upsert policies.
3. Create/update persona using `bin/tune.sh persona --config <file>`.
4. Fill `persona_id` into your conversation config (if not auto-populated) and run `bin/tune.sh conversation --config <file>`.

Keep configs lean; remove anything not actively used.
