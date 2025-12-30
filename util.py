
import os, json, time, pathlib, requests
from typing import Dict, Any, Optional, List
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("TAVUS_API_KEY")
if not API_KEY:
    raise SystemExit("Missing TAVUS_API_KEY in .env")

WEBHOOK_URL = os.getenv("WEBHOOK_URL") or None
PREFERRED_REPLICA = (os.getenv("TAVUS_REPLICA_ID") or "").strip()

PERSONA_ENDPOINT = os.getenv("PERSONA_ENDPOINT", "https://tavusapi.com/v2/personas")
CONVERSATION_ENDPOINT = os.getenv("CONVERSATION_ENDPOINT", "https://tavusapi.com/v2/conversations")
REPLICAS_ENDPOINT = os.getenv("REPLICAS_ENDPOINT", "https://tavusapi.com/v2/replicas")
OBJECTIVES_ENDPOINT = os.getenv("OBJECTIVES_ENDPOINT", "https://tavusapi.com/v2/objectives")
GUARDRAILS_ENDPOINT = os.getenv("GUARDRAILS_ENDPOINT", "https://tavusapi.com/v2/guardrails")

H = {"x-api-key": API_KEY}

def now_slug():
    return time.strftime("%Y%m%d-%H%M%S")

def save_log(action: str, payload: Dict[str, Any], response: requests.Response, endpoint: str) -> pathlib.Path:
    """Persist API request/response for debugging.
    Creates a dated folder under logs/<category>/<timestamp>_<action>/ where category is derived from action.
    Categories:
      persona_create, persona_update -> personas/
      conversation_create -> conversations/
      other -> misc/
    """
    category = "misc"
    if action.startswith("persona_"):
        category = "personas"
    elif action.startswith("conversation_"):
        category = "conversations"
    base = pathlib.Path("logs") / category
    run_dir = base / f"{now_slug()}_{action}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "payload.json").write_text(json.dumps(payload, indent=2))
    try:
        (run_dir / "response.json").write_text(json.dumps(response.json(), indent=2))
    except Exception:
        (run_dir / "response.json").write_text(response.text)
    (run_dir / "meta.json").write_text(json.dumps({
        "endpoint": endpoint,
        "status_code": response.status_code,
        "headers": dict(response.headers),
    }, indent=2))
    return run_dir

def pretty_print_response(r: requests.Response):
    print("\nStatus:", r.status_code)
    try:
        print(json.dumps(r.json(), indent=2))
    except Exception:
        print(r.text)

def pick_replica(overridden: Optional[str] = None) -> str:
    if overridden and overridden.strip():
        return overridden.strip()
    if PREFERRED_REPLICA:
        return PREFERRED_REPLICA
    r = requests.get(REPLICAS_ENDPOINT, headers=H, timeout=30)
    if r.status_code != 200:
        raise SystemExit(f"Failed to list replicas: {r.status_code} {r.text}")
    data = r.json().get("data", [])
    completed = [d for d in data if str(d.get("status", "")).lower() == "completed"]
    if not completed:
        raise SystemExit("No completed replicas found. Create/train one in the Tavus dashboard first.")
    print(f"Auto-selected replica: {completed[0].get('replica_name')} ({completed[0].get('replica_id')})")
    return completed[0]["replica_id"]


def _first_matching_id(item: Dict[str, Any], id_keys: List[str]) -> Optional[str]:
    for k in id_keys:
        v = item.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _match_name(item: Dict[str, Any], target: str, name_keys: List[str]) -> bool:
    t = target.strip().lower()
    for k in name_keys:
        v = item.get(k)
        if isinstance(v, str) and v.strip().lower() == t:
            return True
    return False


def resolve_objectives_id_by_name(name: str) -> Optional[str]:
    """Resolve an Objectives ID by its name. Returns None on failure or not found.
    Tries to be resilient to field naming differences (name/title/objective_name)."""
    try:
        r = requests.get(OBJECTIVES_ENDPOINT, headers=H, timeout=30)
    except Exception:
        return None
    if r.status_code != 200:
        return None
    data = r.json()
    items = data.get("data") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return None
    name_keys = ["name", "title", "objective_name", "objectives_name"]
    id_keys = ["uuid", "id", "objective_id", "objectives_id"]
    for it in items:
        if isinstance(it, dict) and _match_name(it, name, name_keys):
            rid = _first_matching_id(it, id_keys)
            if rid:
                return rid
    return None


def resolve_guardrails_id_by_name(name: str) -> Optional[str]:
    """Resolve a Guardrails ID by its name. Returns None on failure or not found.
    Tries to be resilient to field naming differences (name/title/guardrails_name)."""
    try:
        r = requests.get(GUARDRAILS_ENDPOINT, headers=H, timeout=30)
    except Exception:
        return None
    if r.status_code != 200:
        return None
    data = r.json()
    items = data.get("data") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return None
    name_keys = ["name", "title", "guardrails_name", "policy_name"]
    id_keys = ["uuid", "id", "guardrails_id", "policy_id"]
    for it in items:
        if isinstance(it, dict) and _match_name(it, name, name_keys):
            rid = _first_matching_id(it, id_keys)
            if rid:
                return rid
    return None


def render_system_prompt(template: str, participants: List[str]) -> str:
    participants_clean = [str(p).strip() for p in participants if str(p).strip()]
    if len(participants_clean) != 4:
        raise ValueError(f"Expected exactly 4 participants, got {len(participants_clean)}")

    def oxford_join(names: List[str]) -> str:
        if len(names) == 1:
            return names[0]
        if len(names) == 2:
            return f"{names[0]} and {names[1]}"
        return ", ".join(names[:-1]) + f", and {names[-1]}"

    participant_list = oxford_join(participants_clean)
    round_robin_order = " → ".join(participants_clean) + " (and repeat)"
    greeting_line = (
        f"Hi {participants_clean[0]}, hi {participants_clean[1]}, hi {participants_clean[2]}, hi {participants_clean[3]}. "
        "When you’re ready, just tell me — and we’ll begin."
    )

    p1, p2, p3, p4 = participants_clean

    replacements = {
        "{{P1}}": p1,
        "{{P2}}": p2,
        "{{P3}}": p3,
        "{{P4}}": p4,
        "{{participants[0]}}": p1,
        "{{participants[1]}}": p2,
        "{{participants[2]}}": p3,
        "{{participants[3]}}": p4,
        "{{NEXT_PROPOSER}}": p1,
        "{{PARTICIPANT_LIST}}": participant_list,
        "{{ROUND_ROBIN_ORDER}}": round_robin_order,
        "{{GREETING_LINE}}": greeting_line,
    }

    rendered = template
    for placeholder, value in replacements.items():
        rendered = rendered.replace(placeholder, value)
    return rendered
