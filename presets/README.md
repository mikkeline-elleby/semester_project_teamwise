# Presets overview

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
