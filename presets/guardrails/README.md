# Guardrails Presets

Define reusable Guardrails here. These JSON files act as named presets; create them in Tavus and then reference by name in the CLI to resolve to IDs, or set `guardrails_id` directly.

Recommended flow:
- Create the Guardrail in the Tavus dashboard using the content of your preset file.
- Name it exactly as in the preset ("name").
- Use the CLI with `--guardrails-name <name>` to attach it, or pass the ID with `--guardrails-id`.

Files:
- `template.example.jsonc`: Commented template for creating your own policy.
- `facilitator_safety.guardrail.json`: Example guardrail suited for a meeting facilitator.
