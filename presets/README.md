# Presets (Layers & Tools)

<<<<<<< HEAD
Minimal reference for what you can plug into personas via config or CLI flags.

## Structure
- `layers/llm/*.json` – LLM model fragments (e.g., `tavus_llama_4.json`).
- `layers/tts/*.json` – Text-to-speech engine configs (Cartesia Sonic variants).
- `layers/stt/*.json` – Speech-to-text and turn detection behavior.
- `layers/perception/*.json` – Perception model selection (`basic`, `raven_0`, `off`).
- `layers/llm/tools/*.json` – Function tools the LLM can call.

## Referencing Layers
In a persona config:
```jsonc
{
	"llm": "tavus_llama_4",
	"tts": "cartesia_sonic.teamwise",
	"stt": "teamwise.demo",
	"perception": "basic"
}
```
The harness resolves each name to `presets/layers/<kind>/<name>.json`.

## Common Fields
LLM fragment:
```json
{ "model": "tavus-llama-4" }
```
TTS fragment (Cartesia Sonic):
```json
{
	"tts_engine": "cartesia",
	"external_voice_id": "UUID-here",
	"voice_settings": { "speed": "normal", "emotion": ["positivity:high", "curiosity"] },
	"tts_model_name": "sonic"
}
```
STT fragment:
```json
{
	"stt_engine": "tavus-advanced",
	"participant_pause_sensitivity": "high",
	"participant_interrupt_sensitivity": "high",
	"smart_turn_detection": true,
	"hotwords": "Mikkeline, Akila, TeamWise"
}
```
Perception fragment:
```json
{ "perception_model": "basic" }
```

## Tools Examples
Attach tools by listing their names in the persona `tools` array:
```json
{
	"tools": [
		"summarize_discussion",
		"take_meeting_notes",
		"cluster_ideas",
		"get_speaker_name",
		"get_current_speaker",
		"get_roster"
	]
}
```
Each tool JSON defines:
```json
{
	"type": "function",
	"function": {
		"name": "take_meeting_notes",
		"description": "Captures and organizes key discussion points into structured notes.",
		"parameters": { "type": "object", "properties": { "content": { "type": "string" } }, "required": ["content"] }
	}
}
```

## Adding New Presets
1. Drop a new JSON file under the appropriate `layers/<kind>/` directory.
2. Reference its file stem (without `.json`) in the persona config.
3. (Optional) Combine multiple fragments via CLI flags `--llm/--tts/--stt/--perception`.

## Validation
Use dry-run to inspect final payload:
```bash
bin/tune.sh persona --config configs/persona/facilitator.example.json --print-payload --dry-run
```

## Tips
- Keep hotwords a single comma-separated string (schema expects a string).
- Merge tool lists by naming them; the harness appends them.
- If a layer needs credentials (e.g., TTS external voice id), include only the non-secret reference here; put secrets in `.env` when possible.

---
This is the single presets reference; all other per-layer READMEs were removed for simplicity.
=======
Reusable building blocks you can include by name in persona configs or via CLI flags.

- layers/ — Modular fragments for `llm`, `tts`, `stt`, and `perception` (used with `--layers-dir` and `--llm/--tts/--stt/--perception`).
- tools/ — Function tool definitions (used with `--tools-dir` and `--tools`).
- objectives/ — Named Objectives presets you create in Tavus and then reference by name (resolved to IDs).
- guardrails/ — Named Guardrails presets you create in Tavus and then reference by name (resolved to IDs).

Usage tips:
- Start from the `template.example.jsonc` in each folder.
- Create the Objective/Guardrail in Tavus with the same `name`.
- Attach to a persona using either names (auto-resolved):
	- `--objectives-name "Facilitator Core Objective"`
	- `--guardrails-name "Facilitator Safety Policy"`
	or explicit IDs:
	- `--objectives-id ob_...`
	- `--guardrails-id gr_...`

See subfolder READMEs for details and examples.
>>>>>>> origin/feat/objectives-guardrails
