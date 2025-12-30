#!/usr/bin/env python3
"""
Sync Objectives and Guardrails from presets into Tavus.
- Scans presets/objectives/*.json and presets/guardrails/*.json
- For each file, reads the JSON and uses the "name" field to upsert.
- If a resource with the same name exists (case-insensitive), it updates it.
- Otherwise, it creates a new one.

Usage:
  python bin/sync_policies.py [--dry-run] [--verbose]

Requirements:
  - .env with TAVUS_API_KEY
  - util.py endpoints and headers
"""

import sys, json, pathlib, argparse
from typing import Dict, Any, Optional, List
import requests
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from util import (
    H,
    OBJECTIVES_ENDPOINT,
    GUARDRAILS_ENDPOINT,
)

PRESETS_DIR = pathlib.Path("presets")
OBJ_DIR = PRESETS_DIR / "objectives"
GRD_DIR = PRESETS_DIR / "guardrails"


def _load_json(path: pathlib.Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except Exception as e:
        raise SystemExit(f"Failed to parse JSON at {path}: {e}")


def _list_existing(url: str) -> List[Dict[str, Any]]:
    r = requests.get(url, headers=H, timeout=30)
    if r.status_code != 200:
        raise SystemExit(f"Failed to list {url}: {r.status_code} {r.text}")
    data = r.json()
    items = data.get("data") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    return items  # type: ignore[return-value]


def _find_by_name(items: List[Dict[str, Any]], name: str, name_keys: List[str]) -> Optional[Dict[str, Any]]:
    t = name.strip().lower()
    for it in items:
        if not isinstance(it, dict):
            continue
        for k in name_keys:
            v = it.get(k)
            if isinstance(v, str) and v.strip().lower() == t:
                return it
    return None


def _id_from(item: Dict[str, Any], id_keys: List[str]) -> Optional[str]:
    for k in id_keys:
        v = item.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _create(url: str, doc: Dict[str, Any], dry_run: bool, verbose: bool) -> Optional[str]:
    if dry_run:
        print(f"[dry-run] POST {url} name='{doc.get('name')}'")
        return None
    r = requests.post(url, headers={**H, "Content-Type": "application/json"}, json=doc, timeout=60)
    if verbose:
        print("Response:", r.status_code, r.text[:400])
    if r.status_code not in (200, 201):
        raise SystemExit(f"Create failed: {r.status_code} {r.text}")
    try:
        data = r.json()
    except Exception:
        data = {}
    rid = (
        _id_from(data, ["uuid", "id", "objectives_id", "guardrails_id", "policy_id"]) or
        _id_from(data.get("data", {}), ["uuid", "id", "objectives_id", "guardrails_id", "policy_id"]) or
        ""
    )
    print(f"Created: {doc.get('name')} -> {rid}")
    return rid or None


def _update(url: str, rid: str, doc: Dict[str, Any], dry_run: bool, verbose: bool) -> None:
    """Attempt to update an existing resource with multiple strategies:
    1) PATCH with JSON Patch operations (application/json-patch+json)
    2) PATCH with application/json body
    3) Fallback to create-new if server doesn't support update (405/404)
    """
    target = f"{url}/{rid}"
    if dry_run:
        print(f"[dry-run] PATCH {target} name='{doc.get('name')}'")
        return

    # Strategy 1: JSON Patch (replace fields)
    ops = []
    for k, v in doc.items():
        ops.append({"op": "replace", "path": f"/{k}", "value": v})
    r = requests.patch(
        target,
        headers={**H, "Content-Type": "application/json-patch+json"},
        json=ops,
        timeout=60,
    )
    if verbose:
        print("[update] PATCH json-patch ->", r.status_code, r.text[:400])
    if r.status_code in (200, 204, 304):  # 304 = Not Modified (treat as success)
        msg = "Updated" if r.status_code != 304 else "No changes"
        print(f"{msg}: {doc.get('name')} ({rid})")
        return

    # Strategy 2: PATCH with JSON body
    r2 = requests.patch(target, headers={**H, "Content-Type": "application/json"}, json=doc, timeout=60)
    if verbose:
        print("[update] PATCH json ->", r2.status_code, r2.text[:400])
    if r2.status_code in (200, 204, 304):  # 304 = Not Modified (treat as success)
        msg = "Updated" if r2.status_code != 304 else "No changes"
        print(f"{msg}: {doc.get('name')} ({rid})")
        return

    # Strategy 3: Fallback to create a new resource if update is not allowed
    if r.status_code in (404, 405) or r2.status_code in (404, 405):
        print(f"Update not allowed (status {r.status_code}/{r2.status_code}). Creating a new resource instead...")
        _create(url, doc, dry_run, verbose)
        return

    # If all strategies fail, raise
    raise SystemExit(f"Update failed: PATCH:{r.status_code} {r.text} | JSON-PATCH:{r2.status_code} {r2.text}")


def _slugify(s: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in s).strip("_")


def _to_objectives_data(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    # If already a list in proper shape, trust it
    if isinstance(raw.get("data"), list):
        return raw["data"]
    name = raw.get("name", "Objective")
    desc = raw.get("description", "")
    guidance = raw.get("guidance", "")
    criteria = raw.get("criteria") if isinstance(raw.get("criteria"), list) else []
    prompt_parts = []
    if desc:
        prompt_parts.append(desc)
    if guidance:
        prompt_parts.append(f"Guidance: {guidance}")
    if criteria:
        prompt_parts.append("Criteria: " + "; ".join(str(c) for c in criteria))
    prompt = " \n".join(prompt_parts) or f"Fulfill objective: {name}"
    return [{
        "objective_name": _slugify(name)[:60] or "objective",
        "objective_prompt": prompt[:1000],
        "confirmation_mode": "auto",
        "output_variables": [],
        "modality": "verbal",
        "next_conditional_objectives": {},
        "next_required_objectives": [],
        "callback_url": "",
    }]


def _to_guardrails_data(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    # If already a list in proper shape, trust it
    if isinstance(raw.get("data"), list):
        return raw["data"]
    name = raw.get("name", "Guardrails")
    desc = raw.get("description", "")
    must = raw.get("must") if isinstance(raw.get("must"), list) else []
    disallow = raw.get("disallow") if isinstance(raw.get("disallow"), list) else []
    style = raw.get("style", "")
    parts = []
    if desc:
        parts.append(desc)
    if must:
        parts.append("Always: " + "; ".join(must))
    if disallow:
        parts.append("Never: " + "; ".join(disallow))
    if style:
        parts.append(f"Style: {style}")
    prompt = " \n".join(parts) or f"Apply guardrails for: {name}"
    return [{
        "guardrail_name": _slugify(name)[:60] or "guardrail",
        "guardrail_prompt": prompt[:1000],
        "modality": "verbal",
        "callback_url": "",
    }]


def _sync_folder(kind: str, base_url: str, folder: pathlib.Path, dry_run: bool, verbose: bool):
    if not folder.exists():
        print(f"Skip: {kind} folder not found: {folder}")
        return
    files = sorted([p for p in folder.glob("*.json")])
    if not files:
        print(f"Skip: no {kind} JSON files in {folder}")
        return
    existing = _list_existing(base_url)
    name_keys = ["name", "title", f"{kind}_name", f"{kind}s_name"]
    id_keys = ["uuid", "id", f"{kind}_id", f"{kind}s_id", "policy_id", "guardrails_id", "objectives_id"]
    for f in files:
        raw = _load_json(f)
        nm = raw.get("name")
        if not isinstance(nm, str) or not nm.strip():
            print(f"Skip {f.name}: missing top-level 'name'")
            continue
        # Transform to API shape: wrap remaining fields into 'data'
        # Strategy: if no 'data' list present, synthesize minimal valid schema
        api_doc: Dict[str, Any] = {"name": nm.strip()}
        if kind == "objective":
            data_block = _to_objectives_data(raw)
        elif kind == "guardrails":
            data_block = _to_guardrails_data(raw)
        else:
            data_block = raw.get("data") if isinstance(raw.get("data"), list) else []
        if data_block:
            api_doc["data"] = data_block
        doc = api_doc
        found = _find_by_name(existing, nm, name_keys)
        if found:
            rid = _id_from(found, id_keys)
            if rid:
                print(f"Found existing {kind}: {nm} ({rid}) -> update")
                _update(base_url, rid, doc, dry_run, verbose)
            else:
                print(f"Found existing {kind} but missing ID; creating new: {nm}")
                _create(base_url, doc, dry_run, verbose)
        else:
            print(f"No existing {kind}: {nm} -> create")
            _create(base_url, doc, dry_run, verbose)


def main():
    ap = argparse.ArgumentParser(description="Sync Objectives and Guardrails from presets")
    ap.add_argument("--dry-run", action="store_true", help="Print actions without calling the API")
    ap.add_argument("--verbose", action="store_true", help="Print HTTP responses (truncated)")
    args = ap.parse_args()

    _sync_folder("objective", OBJECTIVES_ENDPOINT, OBJ_DIR, args.dry_run, args.verbose)
    _sync_folder("guardrails", GUARDRAILS_ENDPOINT, GRD_DIR, args.dry_run, args.verbose)

if __name__ == "__main__":
    main()
