#!/usr/bin/env python3
"""Persona builder

Builds a Tavus persona JSON by:
- loading a plain-text prompt template
- loading exactly 4 participant display names
- injecting names into the template
- copying a canonical persona JSON template and replacing only:
  - persona_name (optional)
  - system_prompt (rendered)

Optionally can create a Tavus Persona via API using util.py (requires TAVUS_API_KEY).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


_PLACEHOLDER_RE = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")


@dataclass(frozen=True)
class BuildResult:
    persona: Dict[str, Any]
    rendered_prompt: str
    participants: List[str]
    placeholders_found: List[str]


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception as e:
        raise RuntimeError(f"Failed to read template file: {path} ({e})")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise RuntimeError(f"Failed to read JSON file: {path} ({e})")


def _extract_participants(data: Any) -> List[str]:
    if not isinstance(data, dict):
        raise ValueError("participants file must be a JSON object")

    participants = data.get("participants")
    if not isinstance(participants, list):
        raise ValueError("participants file must contain a 'participants' array")

    names: List[str] = []
    for idx, item in enumerate(participants):
        if isinstance(item, str):
            name = item.strip()
        elif isinstance(item, dict):
            v = item.get("name")
            name = str(v).strip() if v is not None else ""
        else:
            name = ""

        if not name:
            raise ValueError(f"participants[{idx}] must be a non-empty string or {{\"name\": ...}}")
        names.append(name)

    if len(names) != 4:
        raise ValueError(f"Expected exactly 4 participants, got {len(names)}")

    return names


def _render_prompt(template: str, participants: List[str]) -> tuple[str, List[str], List[str]]:
    p1, p2, p3, p4 = participants

    replacements = {
        "P1": p1,
        "P2": p2,
        "P3": p3,
        "P4": p4,
        "participants[0]": p1,
        "participants[1]": p2,
        "participants[2]": p3,
        "participants[3]": p4,
    }

    placeholders_found = [m.group(1) for m in _PLACEHOLDER_RE.finditer(template)]

    def repl(match: re.Match[str]) -> str:
        key = match.group(1).strip()
        if key in replacements:
            return replacements[key]
        # leave unknown placeholders intact
        return match.group(0)

    rendered = _PLACEHOLDER_RE.sub(repl, template)

    # Which of our supported placeholders were present?
    supported_present = sorted(set([k for k in placeholders_found if k in replacements]))

    # Remaining {{...}} placeholders after rendering
    leftovers = sorted(set([m.group(0) for m in _PLACEHOLDER_RE.finditer(rendered)]))

    return rendered, supported_present, leftovers


def _validate_persona_json(persona: Dict[str, Any]) -> None:
    if not isinstance(persona, dict):
        raise ValueError("persona JSON must be an object")

    required = ["persona_name", "pipeline_mode"]
    for k in required:
        if k not in persona:
            raise ValueError(f"persona JSON missing required key: {k}")

    if not isinstance(persona.get("persona_name"), str) or not persona["persona_name"].strip():
        raise ValueError("persona_name must be a non-empty string")

    pipeline_mode = persona.get("pipeline_mode")
    if not isinstance(pipeline_mode, str):
        raise ValueError("pipeline_mode must be a string")

    # If pipeline is full, system_prompt must be present and string
    if pipeline_mode.lower() == "full":
        sp = persona.get("system_prompt")
        if not isinstance(sp, str) or not sp.strip():
            raise ValueError("system_prompt must be a non-empty string when pipeline_mode is 'full'")

    # Guard against common accidental shape issues
    for k, v in persona.items():
        if isinstance(v, tuple):
            raise ValueError(f"Invalid tuple value for key '{k}'. JSON requires lists/objects, not tuples.")


def build_persona(
    *,
    prompt_template_path: Path,
    participants_path: Path,
    persona_template_path: Path,
    persona_name: Optional[str] = None,
) -> BuildResult:
    prompt_template = _read_text(prompt_template_path)
    participants_data = _read_json(participants_path)
    participants = _extract_participants(participants_data)

    persona_template = _read_json(persona_template_path)
    if not isinstance(persona_template, dict):
        raise ValueError("persona-template JSON must be an object")

    rendered_prompt, supported_present, leftovers = _render_prompt(prompt_template, participants)

    # Warn if none of the supported placeholders were used
    if not supported_present:
        print(
            "Warning: no supported placeholders found in prompt template. "
            "Expected one of {{P1}}..{{P4}} or {{participants[0]}}..{{participants[3]}}.",
            file=sys.stderr,
        )

    # Warn if placeholders remain
    if leftovers:
        print(
            "Warning: unrendered placeholders remain in prompt after injection: " + ", ".join(leftovers),
            file=sys.stderr,
        )

    out_persona = dict(persona_template)  # shallow copy
    if persona_name:
        out_persona["persona_name"] = persona_name
    out_persona["system_prompt"] = rendered_prompt

    _validate_persona_json(out_persona)

    # Unit check: ensure all injected names appear at least once
    for n in participants:
        if n not in rendered_prompt:
            raise ValueError(f"Rendered prompt does not include participant name: {n}")

    return BuildResult(
        persona=out_persona,
        rendered_prompt=rendered_prompt,
        participants=participants,
        placeholders_found=supported_present,
    )


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _create_persona_via_tavus(persona_payload: Dict[str, Any]) -> str:
    # Lazy import: util.py exits if TAVUS_API_KEY missing.
    try:
        from util import H, PERSONA_ENDPOINT, save_log  # type: ignore
    except SystemExit as e:
        raise RuntimeError(
            "TAVUS_API_KEY missing (util.py refused to load). Set it in .env or env var before using --create."
        ) from e

    import requests  # local import to keep base path clean

    r = requests.post(PERSONA_ENDPOINT, headers=H, json=persona_payload, timeout=90)
    try:
        data = r.json()
    except Exception:
        data = None

    if r.status_code >= 400:
        raise RuntimeError(f"Tavus create persona failed: {r.status_code} {r.text}")

    save_log("persona_create", persona_payload, r, PERSONA_ENDPOINT)

    persona_id = None
    if isinstance(data, dict):
        persona_id = data.get("persona_id") or data.get("id")

    if not isinstance(persona_id, str) or not persona_id.strip():
        raise RuntimeError("Tavus response did not include persona_id")

    return persona_id


def main() -> int:
    ap = argparse.ArgumentParser(description="Build a persona JSON from a prompt template + participants.")
    ap.add_argument("--template", required=True, help="Path to prompt template text file")
    ap.add_argument("--participants", required=True, help="Path to participants JSON")
    ap.add_argument("--persona-template", required=True, help="Path to canonical persona JSON template")
    ap.add_argument("--out", required=True, help="Output path for generated persona JSON")
    ap.add_argument("--persona-name", required=False, help="Override persona_name in output")
    ap.add_argument(
        "--create",
        action="store_true",
        help="After writing JSON, call Tavus Create Persona API (requires TAVUS_API_KEY) and write persona_id next to output.",
    )

    args = ap.parse_args()

    result = build_persona(
        prompt_template_path=Path(args.template),
        participants_path=Path(args.participants),
        persona_template_path=Path(args.persona_template),
        persona_name=args.persona_name,
    )

    out_path = Path(args.out)
    _write_json(out_path, result.persona)
    print(f"Wrote persona JSON: {out_path}")

    # Post-write validation: reload output and check key types
    reloaded = _read_json(out_path)
    if not isinstance(reloaded, dict):
        raise RuntimeError("Output JSON is not an object")
    sp = reloaded.get("system_prompt")
    if not isinstance(sp, str):
        raise RuntimeError("Output system_prompt is not a string")
    for n in result.participants:
        if n not in sp:
            raise RuntimeError(f"Output system_prompt does not include participant name: {n}")

    if args.create:
        persona_id = _create_persona_via_tavus(reloaded)
        id_path = out_path.with_suffix(out_path.suffix + ".persona_id.txt")
        id_path.write_text(persona_id + "\n", encoding="utf-8")
        print(f"Created Tavus persona_id: {persona_id}")
        print(f"Saved persona_id to: {id_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
