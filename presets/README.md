# Presets

This folder collects reusable building blocks for personas and conversations. It includes:
- Objectives presets (`presets/objectives/*.json`)
- Guardrails presets (`presets/guardrails/*.json`)
- Layer fragments (`presets/layers/**` for llm/tts/stt/perception)
- Tool definitions (`presets/tools/*.json`)

The workflow is config-first: define presets once, sync policies to Tavus, and then reference them by name in your persona configs. No CLI flags are required.

## Objectives

- Create JSON files under `presets/objectives/` with a top-level "name" and optional helper fields. Example templates are provided.
- Upsert them to Tavus via:

```bash
python bin/sync_policies.py
```

- In persona configs, prefer referencing by name using `objectives_name`:

```json
{
  "objectives_name": "facilitator_core"
}
```

IDs are still supported for advanced cases, but names are the default path.

## Guardrails

- Create JSON files under `presets/guardrails/` with a top-level "name". Example templates are provided.
- Upsert them with the same sync step above.
- In persona configs, reference by name using `guardrails_name`:

```json
{
  "guardrails_name": "facilitator_safety"
}
```

## LLM layer fragments

Layer fragments describe how the language model behaves and what function tools it can call. Place them in `presets/layers/llm/`.

Common fields:
- model: LLM model id (e.g., "tavus-gpt-oss").
- tools: Array of function-calling tool definitions.

Tool object shape (summary):
- type: "function"
- function.name: Stable function identifier
- function.description: What the function does
- function.parameters: JSON Schema describing inputs

Example:
```json
{
  "model": "tavus-gpt-oss",
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "summarize_discussion",
        "description": "Summarizes the current discussion into bullet points.",
        "parameters": {
          "type": "object",
          "properties": { "transcript": { "type": "string" } },
          "required": ["transcript"]
        }
      }
    }
  ]
}
```

Model variants provided out-of-the-box (choose by setting the `llm` field in your persona config):
- `tavus-gpt-oss` → `model: "tavus-gpt-oss"`
- `tavus_gpt_4o` → `model: "tavus-gpt-4o"`
- `tavus_gpt_4o_mini` → `model: "tavus-gpt-4o-mini"`

Note: `tavus_llama` / `tavus_llama_4` fragments may be deprecated upstream. They remain in this repo for reference, but the default recommendation is `tavus-gpt-oss`.

## Perception layer fragments

Perception fragments live in `presets/layers/perception/` and enable optional visual/ambient capabilities.

Common fields:
- perception_model: one of `raven-0` (recommended), `basic`, or `off`.
- ambient_awareness_queries: array of short passive checks.
- perception_analysis_queries: array of deeper checks.
- perception_tools and perception_tool_prompt: function tools and guidance specific to perception.

Templates: see `template.example.json` and `template.example.jsonc` for ready-to-copy fragments.

Docs: https://docs.tavus.io/sections/conversational-video-interface/persona/perception

## STT layer fragments

Configure how speech is captured and turns are detected. Place files in `presets/layers/stt/`.

Common fields:
- stt_engine: e.g., `tavus-advanced`.
- participant_pause_sensitivity / participant_interrupt_sensitivity: `low` | `medium` | `high`.
- hotwords: optional hints to bias recognition.
- smart_turn_detection (+ optional params).

## TTS layer fragments

Configure how the agent speaks. Place files in `presets/layers/tts/`.

Common fields:
- tts_engine, tts_model_name
- voice_settings (e.g., speed, emotion)
- tts_emotion_control

## Tools

Function-calling tool definitions live in `presets/tools/`. Each file can contain a single tool, an array of tools, or an object with a top-level `tools` array. Reference them from your persona’s LLM layer by including them in the `tools` array (inline or by copying the definitions into your layer).