#!/usr/bin/env python3
"""
Tuning CLI for Tavus
--------------------
This CLI exposes two subcommands:
    - persona: Create a Persona with flags (no JSON edits required)
    - conversation: Create a Conversation with flags

Highlights:
    - Modular layers: use --layers-dir with --llm/--tts/--stt/--perception instead of preset files
    - --context or meeting helper flags build conversational_context
    - --print-payload and --dry-run help inspect payloads without API calls
"""

import argparse, json, sys, pathlib, re
from typing import List, Optional, Union
import requests
from util import (
    H,
    PERSONA_ENDPOINT,
    CONVERSATION_ENDPOINT,
    save_log,
    pick_replica,
    WEBHOOK_URL,
    resolve_objectives_id_by_name,
    resolve_guardrails_id_by_name,
)
import pathlib as _pl
import glob, os


def _build_s3_recording_properties_from_env(
    exit_on_missing: bool = True,
) -> Optional[dict]:
    """Build native Tavus S3 recording properties from environment variables.
    Requires the following env vars to be set:
      - S3_RECORDING_ASSUME_ROLE_ARN
      - S3_RECORDING_BUCKET_REGION
      - S3_RECORDING_BUCKET_NAME
    Returns a dict suitable for Conversation.properties or None when missing and exit_on_missing=False.
    """
    arn = os.getenv("S3_RECORDING_ASSUME_ROLE_ARN") or os.getenv("AWS_ROLE_ARN") or ""
    region = os.getenv("S3_RECORDING_BUCKET_REGION") or os.getenv("S3_REGION") or ""
    bucket = (
        os.getenv("S3_RECORDING_BUCKET_NAME")
        or os.getenv("S3_BUCKET_NAME")
        or os.getenv("S3_BUCKET")
        or ""
    )
    missing = []
    if not arn:
        missing.append("S3_RECORDING_ASSUME_ROLE_ARN")
    if not region:
        missing.append("S3_RECORDING_BUCKET_REGION")
    if not bucket:
        missing.append("S3_RECORDING_BUCKET_NAME")
    if missing:
        msg = (
            "Native S3 recording requires env vars: "
            + ", ".join(missing)
            + ". Add them to .env or export before running."
        )
        if exit_on_missing:
            sys.exit(msg)
        else:
            print(msg)
            return None
    return {
        "enable_recording": True,
        "aws_assume_role_arn": arn,
        "recording_s3_bucket_region": region,
        "recording_s3_bucket_name": bucket,
    }


def _csv_list(val: Optional[str]) -> List[str]:
    """Turn a comma-separated string into a clean list of strings."""
    if not val:
        return []
    # Split on comma and strip whitespace; drop empties
    return [x.strip() for x in str(val).split(",") if x.strip()]


def _load_tool_file(path: pathlib.Path) -> List[dict]:
    """Load a tool definition from a JSON/JSONC file.
    The file can contain:
      - a single tool object { "type": "function", "function": { ... } }
      - an array of tool objects [ {..}, {..} ]
      - an object with a top-level "tools": [ ... ]
    Returns a list of tool objects. Supports // and /* */ comments (JSONC).
    """
    try:
        data = _load_json_config(path)
    except Exception as e:
        sys.exit(f"Failed to parse tool file {path}: {e}")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if "tools" in data and isinstance(data["tools"], list):
            return data["tools"]
        # assume it's a single tool object
        return [data]
    sys.exit(f"Unsupported tool file format in {path} (must be object or array)")


def _load_layer_fragment(path: pathlib.Path) -> dict:
    """Load a single layer fragment JSON (e.g., llm/tts/stt/perception).
    Expected to be a JSON object; returns the dict.
    """
    try:
        data = _load_json_config(path)
    except Exception as e:
        sys.exit(f"Failed to parse layer file {path}: {e}")
    if not isinstance(data, dict):
        sys.exit(f"Unsupported layer file format in {path} (must be a JSON object)")
    return data


def _merge_llm(existing: dict | None, fragment: dict | None) -> dict:
    """Shallow-merge llm layers, appending tools arrays when both present."""
    base = dict(existing or {})
    frag = dict(fragment or {})
    # Merge keys (fragment overrides base)
    merged = {**base, **frag}
    # Special-case tools: append if both present
    base_tools = (
        (base.get("tools") or []) if isinstance(base.get("tools"), list) else []
    )
    frag_tools = (
        (frag.get("tools") or []) if isinstance(frag.get("tools"), list) else []
    )
    if base_tools or frag_tools:
        merged["tools"] = base_tools + frag_tools
    return merged


def _load_json_config(path: pathlib.Path) -> dict:
    """Load JSON or JSONC (comments allowed). Strips // and /* */ comments before parsing.
    Raises ValueError if parsing fails."""
    txt = path.read_text()

    def strip_comments(s: str) -> str:
        # Remove /* ... */ block comments
        s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
        # Remove // line comments (not perfect if in strings, but fine for templates)
        s = re.sub(r"(^|\s)//.*?$", "", s, flags=re.M)
        return s

    # If extension hints comments, strip immediately
    if path.suffix.lower() == ".jsonc":
        cleaned = strip_comments(txt)
        return json.loads(cleaned)
    # Try raw JSON first
    try:
        return json.loads(txt)
    except Exception:
        # Retry after stripping comments
        cleaned = strip_comments(txt)
        return json.loads(cleaned)


def _resolve_persona_id_by_name(name: str) -> Optional[str]:
    """Look up a persona_id by persona_name via Tavus API. Returns None if not found."""
    try:
        r = requests.get(PERSONA_ENDPOINT, headers=H, timeout=60)
    except Exception as e:
        print(f"Failed to fetch personas to resolve name '{name}': {e}")
        return None
    if r.status_code != 200:
        print(
            f"Failed to fetch personas to resolve name '{name}': {r.status_code} {r.text}"
        )
        return None
    data = r.json()
    items = []
    if isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
        items = data["data"]
    elif isinstance(data, list):
        items = data
    else:
        return None
    target = name.strip().lower()
    for it in items:
        if not isinstance(it, dict):
            continue
        pname = str(it.get("persona_name") or it.get("name") or "").strip().lower()
        pid = it.get("persona_id") or it.get("id")
        if pname == target and isinstance(pid, str) and pid:
            return pid
    return None


def _resolve_persona_id_from_logs(name: Optional[str] = None) -> Optional[str]:
    """Scan logs for latest persona create/update response.json and return persona_id.
    If name is provided, prefer entries with matching persona_name (case-insensitive).
    """
    paths = []
    for pat in (
        "logs/*_persona_create/response.json",
        "logs/*_persona_update/response.json",
    ):
        paths.extend(glob.glob(pat))
    if not paths:
        return None
    # Sort by mtime desc
    paths.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    name_lower = (name or "").lower()
    for p in paths:
        try:
            data = json.loads(open(p).read())
        except Exception:
            continue
        pid = data.get("persona_id") or data.get("id")
        pname = str(data.get("persona_name", ""))
        if name_lower:
            if pname.lower() == name_lower:
                return pid
        elif pid:
            return pid
    return None


def cmd_persona(args: argparse.Namespace) -> int:
    """Create a Persona via Tavus API from CLI flags and/or a config file."""
    # Load optional config file for defaults
    cfg = {}
    if getattr(args, "config", None):
        cfg_path = pathlib.Path(args.config)
        if not cfg_path.exists():
            sys.exit(f"Persona config not found: {cfg_path}")
        try:
            cfg = _load_json_config(cfg_path)
        except Exception as e:
            sys.exit(f"Persona config is not valid JSON/JSONC: {e}")

    persona_name = args.persona_name or cfg.get("persona_name")
    system_prompt = args.system_prompt or cfg.get("system_prompt")
    pipeline_mode = (args.pipeline_mode or cfg.get("pipeline_mode") or "full").lower()
    context = args.context or cfg.get("context")
    # Accept either explicit IDs or names; names will be resolved below.
    objectives_id = getattr(args, "objectives_id", None) or cfg.get("objectives_id")
    guardrails_id = getattr(args, "guardrails_id", None) or cfg.get("guardrails_id")
    objectives_name = getattr(args, "objectives_name", None) or cfg.get(
        "objectives_name"
    )
    guardrails_name = getattr(args, "guardrails_name", None) or cfg.get(
        "guardrails_name"
    )
    default_replica_id = args.default_replica_id or cfg.get("default_replica_id")
    doc_ids = _csv_list(args.document_ids) or _csv_list(cfg.get("document_ids"))
    doc_tags = _csv_list(args.document_tags) or _csv_list(cfg.get("document_tags"))

    payload = {
        "persona_name": persona_name,
        "pipeline_mode": pipeline_mode,
    }
    if system_prompt:
        payload["system_prompt"] = system_prompt
    if context:
        payload["context"] = context
    if default_replica_id:
        payload["default_replica_id"] = default_replica_id
    if doc_ids:
        payload["document_ids"] = doc_ids
    if doc_tags:
        payload["document_tags"] = doc_tags
    # Resolve names to IDs if provided
    if not objectives_id and objectives_name:
        resolved = resolve_objectives_id_by_name(objectives_name)
        if resolved:
            objectives_id = resolved
            print(f"Resolved objectives_id '{resolved}' from name '{objectives_name}'.")
        else:
            print(f"Warning: could not resolve objectives by name '{objectives_name}'.")
    if not guardrails_id and guardrails_name:
        resolved = resolve_guardrails_id_by_name(guardrails_name)
        if resolved:
            guardrails_id = resolved
            print(f"Resolved guardrails_id '{resolved}' from name '{guardrails_name}'.")
        else:
            print(f"Warning: could not resolve guardrails by name '{guardrails_name}'.")
    if objectives_id:
        payload["objectives_id"] = objectives_id
    if guardrails_id:
        payload["guardrails_id"] = guardrails_id

    # Layers can be provided via a custom JSON file or inlined in config
    layers_file = getattr(args, "layers_file", None) or cfg.get("layers_file")
    if layers_file:
        p = pathlib.Path(layers_file)
        if not p.exists():
            sys.exit(f"layers file not found: {p}")
        try:
            payload["layers"] = json.loads(p.read_text())
        except Exception as e:
            sys.exit(f"layers file is not valid JSON: {e}")
    elif "layers" in cfg:
        payload["layers"] = cfg["layers"]

    # Modular layers: allow specifying llm/tts/stt/perception by name or file, resolved under layers_dir
    layers_dir = pathlib.Path(
        getattr(args, "layers_dir", None)
        or cfg.get("layers_dir")
        or (pathlib.Path(__file__).parent / "presets" / "layers")
    )

    # Resolve helper
    def resolve_layer_path(kind: str, value: Optional[str]) -> Optional[pathlib.Path]:
        if not value:
            return None
        cand = pathlib.Path(value)
        if cand.exists():
            return cand
        # try layers_dir/kind/<name or name.json>
        p = layers_dir / kind / (value if value.endswith(".json") else f"{value}.json")
        if p.exists():
            return p
        sys.exit(f"{kind} layer not found: {value} (looked under {layers_dir / kind})")

    # Accept from flags or config
    llm_name = getattr(args, "llm", None) or cfg.get("llm")
    tts_name = getattr(args, "tts", None) or cfg.get("tts")
    stt_name = getattr(args, "stt", None) or cfg.get("stt")
    perception_name = getattr(args, "perception", None) or cfg.get("perception")
    conversational_flow = getattr(args, "conversational_flow", None) or cfg.get(
        "conversational_flow"
    )

    # Load fragments
    llm_path = resolve_layer_path("llm", llm_name)
    tts_path = resolve_layer_path("tts", tts_name)
    stt_path = resolve_layer_path("stt", stt_name)
    perc_path = resolve_layer_path("perception", perception_name)
    conversational_flow_path = resolve_layer_path(
        "conversational_flow", conversational_flow
    )

    if llm_path or tts_path or stt_path or perc_path or conversational_flow_path:
        layers = dict(payload.get("layers") or {})
        if llm_path:
            frag = _load_layer_fragment(llm_path)
            layers["llm"] = _merge_llm(layers.get("llm"), frag)
        if tts_path:
            layers["tts"] = _load_layer_fragment(tts_path)
        if stt_path:
            stt_frag = _load_layer_fragment(stt_path)
            # Normalize hotwords: API expects a string; allow arrays in presets and join here
            hw = stt_frag.get("hotwords")
            if isinstance(hw, list):
                stt_frag["hotwords"] = ", ".join(
                    [str(x).strip() for x in hw if str(x).strip()]
                )
            layers["stt"] = stt_frag
        if perc_path:
            layers["perception"] = _load_layer_fragment(perc_path)
        if conversational_flow_path:
            layers["conversational_flow"] = _load_layer_fragment(
                conversational_flow_path
            )
        payload["layers"] = layers

    # Merge modular tools specified by name or file into layers.llm.tools
    # Accept comma-separated names via --tools or a list via config { "tools": ["name1", "name2"] }
    tools_arg = getattr(args, "tools", None)
    tools_from_flags = _csv_list(tools_arg) if isinstance(tools_arg, str) else []
    tools_from_cfg: List[str] = []
    cfg_tools = cfg.get("tools")
    if isinstance(cfg_tools, list):
        tools_from_cfg = [str(x).strip() for x in cfg_tools if str(x).strip()]
    tools_names = tools_from_flags or tools_from_cfg
    if tools_names:
        # Prefer colocated tools under LLM layer
        # Updated default tools directory after relocation from presets/layers/llm/tools to presets/tools
        default_tools_dir = pathlib.Path(__file__).parent / "presets" / "tools"
        configured_tools_dir = getattr(args, "tools_dir", None) or cfg.get("tools_dir")
        tools_dir = (
            pathlib.Path(configured_tools_dir)
            if configured_tools_dir
            else default_tools_dir
        )
        merged_tools: List[dict] = []
        for name in tools_names:
            # If explicit path is provided, use it; else treat as name under tools_dir with .json
            candidate = pathlib.Path(name)
            if candidate.exists():
                tool_path = candidate
            else:
                tool_path = tools_dir / (
                    name if name.endswith(".json") else f"{name}.json"
                )
            if not tool_path.exists():
                sys.exit(f"tool not found: {tool_path}")
            merged_tools.extend(_load_tool_file(tool_path))
        # Ensure layers/llm/tools exist and extend
        layers = payload.get("layers") or {}
        llm = layers.get("llm") or {}
        existing_tools = llm.get("tools") or []
        llm["tools"] = existing_tools + merged_tools
        layers["llm"] = llm
        payload["layers"] = layers

    # Detect update mode and target persona_id if provided
    update_mode = bool(getattr(args, "update", False) or cfg.get("update"))
    persona_id_for_update = getattr(args, "persona_id", None) or cfg.get("persona_id")
    target_persona_name = getattr(args, "target_persona_name", None) or cfg.get(
        "target_persona_name"
    )
    # If updating without explicit ID, try to resolve by targetPersonName; as a fallback, try current persona_name
    if update_mode and not persona_id_for_update:
        name_to_resolve = target_persona_name or persona_name
        if name_to_resolve:
            resolved = _resolve_persona_id_by_name(name_to_resolve)
            if not resolved:
                # Fallback to logs if API lookup fails
                resolved = _resolve_persona_id_from_logs(name_to_resolve)
            if resolved:
                persona_id_for_update = resolved
                print(
                    f"Resolved persona_id '{resolved}' from name '{name_to_resolve}'."
                )
        else:
            # Last ditch: any latest persona from logs
            resolved = _resolve_persona_id_from_logs(None)
            if resolved:
                persona_id_for_update = resolved
                print(f"Resolved persona_id '{resolved}' from latest logs.")

    # Validate minimal required fields
    if update_mode:
        if not persona_id_for_update:
            sys.exit(
                "--update requires a persona_id (via --persona-id, target_persona_name, or config)"
            )
        # For update, allow partials; ensure at least one field is present
        if not payload:
            sys.exit(
                "--update provided but no updatable fields were set in flags or config"
            )
    else:
        if not persona_name:
            sys.exit(
                "persona_name is required (via --persona-name or config persona_name)"
            )
        if pipeline_mode == "full" and not system_prompt:
            sys.exit("system_prompt is required when pipeline_mode is 'full'")

    if args.print_payload:
        print(json.dumps(payload, indent=2))
    if args.dry_run:
        return 0

    if update_mode:
        url = f"{PERSONA_ENDPOINT}/{persona_id_for_update}"
        # Build JSON Patch operations for provided fields
        ops = []
        for k, v in payload.items():
            ops.append({"op": "replace", "path": f"/{k}", "value": v})
        h = dict(H)
        h["Content-Type"] = "application/json-patch+json"
        r = requests.patch(url, headers=h, json=ops, timeout=90)
        print("\nStatus:", r.status_code)
        try:
            print(json.dumps(r.json(), indent=2))
        except Exception:
            print(r.text)
        save_log("persona_update", payload, r, url)
        return 0 if r.status_code < 400 else 1
    else:
        r = requests.post(PERSONA_ENDPOINT, headers=H, json=payload, timeout=90)
        print("\nStatus:", r.status_code)
        try:
            print(json.dumps(r.json(), indent=2))
        except Exception:
            print(r.text)
        save_log("persona_create", payload, r, PERSONA_ENDPOINT)
        return 0 if r.status_code < 400 else 1


def _build_conversational_context(args: argparse.Namespace) -> Optional[str]:
    """Build conversational_context; prefer explicit --context, else synthesize."""
    if args.context:
        return args.context
    if all(
        [
            args.meeting_type,
            args.framework,
            args.duration is not None,
            args.participants is not None,
            args.topic,
            args.comment,
        ]
    ):
        return (
            f"You are a facilitator guiding a {int(args.duration)}-minute {args.meeting_type} "
            f"using the {args.framework} framework.\n"
            f"Topic: \u201c{args.topic}\u201d\n"
            f"Participants: {int(args.participants)}. Include quiet voices; announce time checks; "
            f"cluster ideas; end with 1 clear action item.\n"
            f"Host comment: {args.comment}."
        )
    return None


def cmd_conversation(args: argparse.Namespace) -> int:
    """Create a Conversation via Tavus API from CLI flags and/or a config file."""
    # Load optional config for defaults
    cfg = {}
    if getattr(args, "config", None):
        cfg_path = pathlib.Path(args.config)
        if not cfg_path.exists():
            sys.exit(f"Conversation config not found: {cfg_path}")
        try:
            cfg = _load_json_config(cfg_path)
        except Exception as e:
            sys.exit(f"Conversation config is not valid JSON/JSONC: {e}")

    payload: dict = {}
    persona_id = args.persona_id or cfg.get("persona_id")
    replica_id = args.replica_id or cfg.get("replica_id")

    if not persona_id:
        persona_name = cfg.get("persona_name") or getattr(args, "persona_name", None)
        if persona_name:
            persona_id = _resolve_persona_id_by_name(
                persona_name
            ) or _resolve_persona_id_from_logs(persona_name)
            if persona_id:
                print(
                    f"Resolved persona_id '{persona_id}' from persona_name '{persona_name}'."
                )
        else:
            # fallback: pick the most recent persona created in logs
            persona_id = _resolve_persona_id_from_logs(None)
            if persona_id:
                print(
                    f"Resolved persona_id '{persona_id}' from recent persona_create logs."
                )

    if persona_id:
        payload["persona_id"] = persona_id
    if replica_id:
        payload["replica_id"] = replica_id
    elif not persona_id:
        # Neither provided: auto-pick a completed replica
        payload["replica_id"] = pick_replica(None)

    name = args.name or cfg.get("name") or cfg.get("conversation_name")
    # (3) Auto derive name from config filename if still missing
    if not name and getattr(args, "config", None):
        stem = pathlib.Path(args.config).stem
        # strip generic prefixes/suffixes
        cleaned = re.sub(r"[_\-.]+", " ", stem).strip()
        name = cleaned.title()
    if name:
        payload["conversation_name"] = name
    # Prefer explicit --context, else config conversational_context, else meeting helpers
    cc = (
        args.context
        or cfg.get("conversational_context")
        or _build_conversational_context(args)
    )
    if cc:
        payload["conversational_context"] = cc
    # (6) Callback URL implicit: only set if non-empty value from explicit flag or config, else take WEBHOOK_URL env.
    cb_flag = (args.callback_url or "").strip()
    cb_cfg = str(cfg.get("callback_url") or "").strip()
    if cb_flag:
        payload["callback_url"] = cb_flag
    elif cb_cfg:
        payload["callback_url"] = cb_cfg
    elif WEBHOOK_URL:
        payload["callback_url"] = WEBHOOK_URL
    if args.custom_greeting:
        payload["custom_greeting"] = args.custom_greeting
    elif cfg.get("custom_greeting"):
        payload["custom_greeting"] = cfg.get("custom_greeting")
    if args.audio_only:
        payload["audio_only"] = True
    elif isinstance(cfg.get("audio_only"), bool):
        payload["audio_only"] = cfg.get("audio_only")
    # Test mode only when explicitly set via flags or config (no env default)
    if args.test_mode:
        payload["test_mode"] = True
    elif getattr(args, "disable_test_mode", False):
        payload["test_mode"] = False
    elif isinstance(cfg.get("test_mode"), bool):
        payload["test_mode"] = cfg.get("test_mode")
    if args.document_retrieval_strategy:
        payload["document_retrieval_strategy"] = args.document_retrieval_strategy
    elif cfg.get("document_retrieval_strategy"):
        payload["document_retrieval_strategy"] = cfg.get("document_retrieval_strategy")

    doc_ids = _csv_list(args.document_ids) or _csv_list(cfg.get("document_ids"))
    doc_tags = _csv_list(args.document_tags) or _csv_list(cfg.get("document_tags"))
    mems = _csv_list(args.memory_stores) or _csv_list(cfg.get("memory_stores"))
    if doc_ids:
        payload["document_ids"] = doc_ids
    if doc_tags:
        payload["document_tags"] = doc_tags
    if mems:
        payload["memory_stores"] = mems

    properties_file = args.properties_file or cfg.get("properties_file")
    if properties_file:
        p = pathlib.Path(properties_file)
        if not p.exists():
            sys.exit(f"properties file not found: {p}")
        try:
            props = json.loads(p.read_text())
        except Exception as e:
            sys.exit(f"properties file is not valid JSON: {e}")
        # Accept either a plain properties object or an object with top-level "properties"
        if (
            isinstance(props, dict)
            and "properties" in props
            and isinstance(props.get("properties"), dict)
            and (
                len(props.keys()) == 1
                or (len(props.keys()) == 2 and "comment" in props)
            )
        ):
            payload["properties"] = props["properties"]
        else:
            if not isinstance(props, dict):
                sys.exit(
                    'properties file must be a JSON object (either the properties object or { "properties": { ... } })'
                )
            payload["properties"] = props
    elif isinstance(cfg.get("properties"), dict):
        # Accept inline properties from config directly
        payload["properties"] = cfg["properties"]
    elif getattr(args, "use_s3_recording_from_env", False):
        # Build properties from environment variables for native Tavus S3 recording
        props = _build_s3_recording_properties_from_env(exit_on_missing=True)
        payload["properties"] = props
    else:
        # (5) Auto recording: config shortcut OR env TUNE_AUTO_RECORDING
        auto_record_cfg = bool(cfg.get("enable_recording") or cfg.get("recording"))
        auto_record_env = os.getenv("TUNE_AUTO_RECORDING", "").lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        if auto_record_cfg or (auto_record_env and not cfg.get("disable_recording")):
            props = _build_s3_recording_properties_from_env(exit_on_missing=True)
            if props:
                payload["properties"] = props

    if args.print_payload or os.getenv("TUNE_VERBOSE"):
        print(json.dumps(payload, indent=2))
    if args.dry_run:
        return 0

    r = requests.post(CONVERSATION_ENDPOINT, headers=H, json=payload, timeout=90)
    print("\nStatus:", r.status_code)
    try:
        print(json.dumps(r.json(), indent=2))
    except Exception:
        print(r.text)
    save_log("conversation_create", payload, r, CONVERSATION_ENDPOINT)
    return 0 if r.status_code < 400 else 1


def main():
    """Parse CLI args and dispatch to Persona or Conversation creation."""
    ap = argparse.ArgumentParser(
        description="Tavus tuning CLI: create personas and conversations via flags."
    )
    sp = ap.add_subparsers(dest="cmd", required=True)

    # Persona subcommand flags map 1:1 to Tavus Create Persona body where possible
    pp = sp.add_parser("persona", help="Create a persona with flags or a config file")
    pp.add_argument("--config", help="Path to a JSON config with persona fields")
    pp.add_argument("--persona-name")
    pp.add_argument(
        "--system-prompt",
        required=False,
        help="LLM system prompt; required for pipeline_mode=full",
    )
    pp.add_argument(
        "--pipeline-mode",
        choices=["full", "echo"],
        default="full",
        help="CVI pipeline mode",
    )
    pp.add_argument("--context")
    pp.add_argument("--default-replica-id")
    pp.add_argument("--document-ids", help="Comma-separated document IDs")
    pp.add_argument("--document-tags", help="Comma-separated document tags")
    pp.add_argument("--layers-file", help="Path to a JSON file for persona layers")
    pp.add_argument(
        "--layers-dir",
        help="Directory where modular layer JSON files live (default: presets/layers)",
    )
    pp.add_argument(
        "--llm", help="LLM layer by name or file (resolved under layers-dir/llm)"
    )
    pp.add_argument(
        "--tts", help="TTS layer by name or file (resolved under layers-dir/tts)"
    )
    pp.add_argument(
        "--stt", help="STT layer by name or file (resolved under layers-dir/stt)"
    )
    pp.add_argument(
        "--perception",
        help="Perception layer by name or file (resolved under layers-dir/perception)",
    )
    pp.add_argument(
        "--conversational-flow",
        help="Conversational flow layer by name or file (resolved under layers-dir/conversational_flow)",
    )
    pp.add_argument(
        "--tools",
        help="Comma-separated tool names or JSON files (resolved under presets/tools by default)",
    )
    pp.add_argument(
        "--tools-dir",
        help="Directory where tool JSON files live (default: presets/tools)",
    )
    pp.add_argument(
        "--objectives-id",
        dest="objectives_id",
        help="Attach Objectives by ID (created in Tavus dashboard)",
    )
    pp.add_argument(
        "--guardrails-id",
        dest="guardrails_id",
        help="Attach Guardrails by ID (created in Tavus dashboard)",
    )
    pp.add_argument(
        "--objectives-name",
        dest="objectives_name",
        help="Resolve and attach Objectives by NAME (looks up via API)",
    )
    pp.add_argument(
        "--guardrails-name",
        dest="guardrails_name",
        help="Resolve and attach Guardrails by NAME (looks up via API)",
    )
    pp.add_argument(
        "--target-persona-name",
        help="When using --update, resolve persona_id by this name if --persona-id is not provided",
    )
    pp.add_argument(
        "--update",
        action="store_true",
        help="Update an existing persona (PATCH) instead of creating (POST)",
    )
    pp.add_argument(
        "--persona-id",
        help="Persona ID to patch when using --update; can also be set in config as persona_id",
    )
    pp.add_argument(
        "--print-payload", action="store_true", help="Print the request body then exit"
    )
    pp.add_argument("--dry-run", action="store_true", help="Skip the API call")
    pp.set_defaults(func=cmd_persona)

    # Conversation subcommand flags map to Tavus Create Conversation body
    pc = sp.add_parser(
        "conversation", help="Create a conversation with flags or a config file"
    )
    pc.add_argument("--config", help="Path to a JSON config with conversation fields")
    pc.add_argument("--persona-id", help="Use a Persona by ID (preferred)")
    pc.add_argument(
        "--replica-id",
        help="Override persona's default or use when no persona is provided",
    )
    pc.add_argument("--name", help="conversation_name")
    pc.add_argument("--context", help="Explicit conversational context to send")
    pc.add_argument("--callback-url")
    pc.add_argument("--custom-greeting", help="Replica opening line")
    pc.add_argument(
        "--audio-only", action="store_true", help="Create audio-only conversation"
    )
    pc.add_argument(
        "--test-mode", action="store_true", help="Validate without joining/billing"
    )
    pc.add_argument(
        "--disable-test-mode",
        action="store_true",
        help="Force test_mode=false even if config sets it true",
    )
    pc.add_argument("--document-ids", help="Comma-separated document IDs")
    pc.add_argument("--document-tags", help="Comma-separated document tags")
    pc.add_argument(
        "--document-retrieval-strategy",
        choices=["speed", "quality", "balanced"],
        default="balanced",
        help="Doc retrieval mode",
    )
    pc.add_argument("--memory-stores", help="Comma-separated memory store names")
    pc.add_argument("--properties-file", help="Path to a JSON file for properties")
    pc.add_argument(
        "--use-s3-recording-from-env",
        action="store_true",
        help="Enable native Tavus S3 recording using env vars S3_RECORDING_ASSUME_ROLE_ARN, S3_RECORDING_BUCKET_REGION, S3_RECORDING_BUCKET_NAME",
    )
    pc.add_argument(
        "--print-payload", action="store_true", help="Print the request body then exit"
    )
    pc.add_argument("--dry-run", action="store_true", help="Skip the API call")
    # Optional meeting param helpers to generate context if --context is not provided
    pc.add_argument("--meeting-type", help="e.g., Brainstorming, Retrospective")
    pc.add_argument("--framework", help="e.g., Double Diamond, SCAMPER")
    pc.add_argument("--duration", type=int, help="Minutes")
    pc.add_argument("--participants", type=int, help="Headcount")
    pc.add_argument("--topic", help="Primary discussion topic")
    pc.add_argument("--comment", help="Host comment/constraints")
    pc.set_defaults(func=cmd_conversation)

    # Scenario subcommand: single JSON with { "persona": {..}, "conversation": {..} }
    sc = sp.add_parser(
        "scenario",
        help="Create/update persona then create conversation from one JSON file",
    )
    sc.add_argument(
        "--config",
        required=True,
        help="Path to scenario JSON/JSONC: { persona: {...}, conversation: {...} }",
    )
    sc.add_argument(
        "--print-payload",
        action="store_true",
        help="Print combined persona & conversation payloads",
    )
    sc.add_argument(
        "--dry-run", action="store_true", help="Skip API calls (show resolution only)"
    )

    def cmd_scenario(args: argparse.Namespace) -> int:
        cfg_path = pathlib.Path(args.config)
        if not cfg_path.exists():
            sys.exit(f"Scenario config not found: {cfg_path}")
        try:
            root = _load_json_config(cfg_path)
        except Exception as e:
            sys.exit(f"Scenario config invalid: {e}")
        if not isinstance(root, dict):
            sys.exit(
                "Scenario config must be a JSON object with persona and conversation keys"
            )
        persona_cfg = root.get("persona") or {}
        conv_cfg = root.get("conversation") or {}
        if not isinstance(persona_cfg, dict) or not isinstance(conv_cfg, dict):
            sys.exit("persona and conversation must be JSON objects")
        # Implicit persona create/update by name + optional persona_id
        persona_name = persona_cfg.get("persona_name")
        persona_id = persona_cfg.get("persona_id")
        update_mode = bool(persona_cfg.get("update") or persona_cfg.get("force_update"))
        # Auto detect update if persona_id present or persona_name matches existing
        if not update_mode and not persona_id and persona_name:
            resolved = _resolve_persona_id_by_name(persona_name)
            if not resolved:
                resolved = _resolve_persona_id_from_logs(persona_name)
            if resolved:
                persona_id = resolved
                update_mode = True
        # Build persona payload using existing builder logic reusing cmd_persona pieces lightly
        # Instead of duplicating fully, reconstruct minimal fields
        p_payload = {
            k: v
            for k, v in persona_cfg.items()
            if k
            in (
                "persona_name",
                "system_prompt",
                "pipeline_mode",
                "context",
                "default_replica_id",
                "document_ids",
                "document_tags",
                "objectives_id",
                "guardrails_id",
            )
            and v not in (None, "")
        }
        # Layers provided inline or via modular keys
        layers = persona_cfg.get("layers")
        # Modular fragments
        layers_dir = pathlib.Path(
            persona_cfg.get("layers_dir")
            or (pathlib.Path(__file__).parent / "presets" / "layers")
        )

        def resolve_fragment(kind: str, value: Optional[str]) -> Optional[pathlib.Path]:
            if not value:
                return None
            cand = pathlib.Path(value)
            if cand.exists():
                return cand
            p = (
                layers_dir
                / kind
                / (value if value.endswith(".json") else f"{value}.json")
            )
            return p if p.exists() else None

        llm_path = resolve_fragment("llm", persona_cfg.get("llm"))
        tts_path = resolve_fragment("tts", persona_cfg.get("tts"))
        stt_path = resolve_fragment("stt", persona_cfg.get("stt"))
        perc_path = resolve_fragment("perception", persona_cfg.get("perception"))
        conversational_flow_path = resolve_fragment(
            "conversational_flow", persona_cfg.get("conversational_flow")
        )
        if layers:
            if not isinstance(layers, dict):
                sys.exit("persona.layers must be a JSON object")
        else:
            layers = {}
        if llm_path:
            frag = _load_layer_fragment(llm_path)
            layers["llm"] = _merge_llm(layers.get("llm"), frag)
        if tts_path:
            layers["tts"] = _load_layer_fragment(tts_path)
        if stt_path:
            stt_frag = _load_layer_fragment(stt_path)
            hw = stt_frag.get("hotwords")
            if isinstance(hw, list):
                stt_frag["hotwords"] = ", ".join(
                    [str(x).strip() for x in hw if str(x).strip()]
                )
            layers["stt"] = stt_frag
        if perc_path:
            layers["perception"] = _load_layer_fragment(perc_path)
        if conversational_flow_path:
            layers["conversational_flow"] = _load_layer_fragment(
                conversational_flow_path
            )
        # Tools merging
        tools_list = []
        tnames = []
        if isinstance(persona_cfg.get("tools"), list):
            tnames = [str(x).strip() for x in persona_cfg["tools"] if str(x).strip()]
        if tnames:
            # Updated default tools directory (was presets/layers/llm/tools)
            default_tools_dir = pathlib.Path(__file__).parent / "presets" / "tools"
            for name in tnames:
                candidate = pathlib.Path(name)
                if candidate.exists():
                    tool_path = candidate
                else:
                    tool_path = default_tools_dir / (
                        name if name.endswith(".json") else f"{name}.json"
                    )
                if not tool_path.exists():
                    sys.exit(f"tool not found: {tool_path}")
                tools_list.extend(_load_tool_file(tool_path))
        if tools_list:
            llm_layer = layers.get("llm") or {}
            existing_tools = llm_layer.get("tools") or []
            llm_layer["tools"] = existing_tools + tools_list
            layers["llm"] = llm_layer
        if layers:
            p_payload["layers"] = layers
        # Validate persona create/update minimal requirements
        if update_mode:
            if not persona_id:
                sys.exit("Scenario: resolved update mode but no persona_id found")
        else:
            if not p_payload.get("persona_name"):
                sys.exit("Scenario: persona_name required for create")
            if (p_payload.get("pipeline_mode", "full") == "full") and not p_payload.get(
                "system_prompt"
            ):
                sys.exit("Scenario: system_prompt required for pipeline_mode=full")
        # If dry-run or print, output payloads
        # Create/update persona unless dry-run
        created_persona_id = persona_id
        if args.print_payload:
            print("Persona payload:")
            print(json.dumps(p_payload, indent=2))
        if not args.dry_run:
            if update_mode:
                url = f"{PERSONA_ENDPOINT}/{persona_id}"
                ops = []
                for k, v in p_payload.items():
                    ops.append({"op": "replace", "path": f"/{k}", "value": v})
                h = dict(H)
                h["Content-Type"] = "application/json-patch+json"
                r = requests.patch(url, headers=h, json=ops, timeout=90)
                print("\nPersona status:", r.status_code)
                try:
                    print(json.dumps(r.json(), indent=2))
                except Exception:
                    print(r.text)
                save_log("persona_update", p_payload, r, url)
                if r.status_code >= 400:
                    return 1
                created_persona_id = persona_id
            else:
                r = requests.post(
                    PERSONA_ENDPOINT, headers=H, json=p_payload, timeout=90
                )
                print("\nPersona status:", r.status_code)
                try:
                    print(json.dumps(r.json(), indent=2))
                except Exception:
                    print(r.text)
                save_log("persona_create", p_payload, r, PERSONA_ENDPOINT)
                if r.status_code >= 400:
                    return 1
                try:
                    created_persona_id = r.json().get("persona_id") or r.json().get(
                        "id"
                    )
                except Exception:
                    created_persona_id = None
        # Build conversation payload using existing logic with inline config conv_cfg
        # Inject persona_id if not already set
        if created_persona_id and not conv_cfg.get("persona_id"):
            conv_cfg["persona_id"] = created_persona_id
        # When scenario provides persona_name only, attempt resolution
        if not conv_cfg.get("persona_id") and conv_cfg.get("persona_name"):
            resolved = _resolve_persona_id_by_name(
                conv_cfg["persona_name"]
            ) or _resolve_persona_id_from_logs(conv_cfg["persona_name"])
            if resolved:
                conv_cfg["persona_id"] = resolved
        # Conversation payload assembly similar to cmd_conversation but only config-driven
        c_payload = {}
        for k in [
            "persona_id",
            "replica_id",
            "conversation_name",
            "name",
            "conversational_context",
            "callback_url",
            "custom_greeting",
            "audio_only",
            "test_mode",
            "document_retrieval_strategy",
            "properties",
        ]:
            v = conv_cfg.get(k)
            if v not in (None, ""):
                # unify name field
                if k == "name":
                    c_payload["conversation_name"] = v
                else:
                    c_payload[
                        k if k != "conversational_context" else "conversational_context"
                    ] = v
        # Arrays
        for k in ["document_ids", "document_tags", "memory_stores"]:
            v = conv_cfg.get(k)
            if isinstance(v, list) and v:
                c_payload[k] = v
        # Auto name derive if missing
        if not c_payload.get("conversation_name"):
            stem = cfg_path.stem
            cleaned = re.sub(r"[_\-.]+", " ", stem).strip().title()
            c_payload["conversation_name"] = cleaned
        # Callback from env if absent
        if not c_payload.get("callback_url") and WEBHOOK_URL:
            c_payload["callback_url"] = WEBHOOK_URL
        if args.print_payload:
            print("\nConversation payload:")
            print(json.dumps(c_payload, indent=2))
        if args.dry_run:
            return 0
        r = requests.post(CONVERSATION_ENDPOINT, headers=H, json=c_payload, timeout=90)
        print("\nConversation status:", r.status_code)
        try:
            print(json.dumps(r.json(), indent=2))
        except Exception:
            print(r.text)
        save_log("conversation_create", c_payload, r, CONVERSATION_ENDPOINT)
        return 0 if r.status_code < 400 else 1

    sc.set_defaults(func=cmd_scenario)

    args = ap.parse_args()
    try:
        rc = args.func(args)
    except KeyboardInterrupt:
        rc = 130
    sys.exit(rc)


if __name__ == "__main__":
    main()
