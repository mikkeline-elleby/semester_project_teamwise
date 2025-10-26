# Objectives Presets

Define reusable Objectives here. These JSON files are not sent directly to the API; they serve as named presets you can reference by name and resolve to IDs once created in Tavus.

Recommended flow:
- Create the Objective in the Tavus dashboard using the content of your preset file.
- Name it exactly as in the preset ("name").
- Use the CLI with `--objectives-name <name>` to attach it, or set `objectives_id` directly if you already have it.

Files:
- `template.example.jsonc`: Commented template for creating your own objective.
- `facilitator_core.objective.json`: Example objective suited for a meeting facilitator.
