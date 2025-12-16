from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from typing import Any, Dict, Optional, cast, List
import re
import os
import time
import uuid
import json
from datetime import datetime
import urllib.request
import tempfile
import boto3
import requests
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from a local .env file (development convenience)
load_dotenv()


APP_SECRET = os.getenv("WEBHOOK_SHARED_SECRET", "")


class ToolCall(BaseModel):
    name: str = Field(..., description="Tool/function name")
    arguments: Dict[str, Any] = Field(default_factory=dict)
    call_id: Optional[str] = Field(default=None, description="Upstream tool call id if provided")


class TavusEvent(BaseModel):
    # Permissive model; we can tighten when schema is confirmed
    event_type: str = Field("tool_call")
    message_type: Optional[str] = None
    conversation_id: Optional[str] = None
    event_id: Optional[str] = None
    timestamp: Optional[float] = None
    tool: Optional[ToolCall] = None
    data: Dict[str, Any] = Field(default_factory=dict)
    properties: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        extra = "ignore"

    @field_validator("timestamp", mode="before")
    @classmethod
    def _coerce_timestamp(cls, v: Any) -> Any:
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            # Try ISO 8601 with optional Z suffix
            s = v.strip()
            try:
                if s.endswith("Z"):
                    s = s.replace("Z", "+00:00")
                return datetime.fromisoformat(s).timestamp()
            except Exception:
                # Fallback: try plain float string
                try:
                    return float(v)
                except Exception:
                    return None
        return None


app = FastAPI(title="Tavus Webhook Backend", version="0.1.0")

app.add_middleware(
    cast(Any, CORSMiddleware),
    allow_origins=["*"],  # tighten in prod
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def verify_secret(req: Request) -> None:
    if not APP_SECRET:
        return  # disabled; dev mode
    provided = req.headers.get("x-webhook-secret") or req.headers.get("x-tavus-secret")
    if not provided or provided != APP_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")


handlers: Dict[str, Any] = {}
# In-memory roster per conversation
# ROSTER[conversation_id] = {
#   "participants": { participant_id: display_name, ... },
#   "last_speaker_id": str | None,
#   "last_speaker_name": str | None,
# }
ROSTER: Dict[str, Dict[str, Any]] = {}

TAVUS_INTERACTIONS_ENDPOINT = os.getenv("TAVUS_INTERACTIONS_ENDPOINT", "https://tavusapi.com/v2/interactions")
ENABLE_TAVUS_ECHO = (os.getenv("ENABLE_TAVUS_ECHO") or "").lower() in ("1", "true", "yes")
TAVUS_API_KEY = os.getenv("TAVUS_API_KEY") or ""
ACK_TEMPLATES = [
    "Thanks for sharing that, {name}.",
    "Appreciate that, {name}.",
    "Nice choice, {name}.",
    "Great point, {name}.",
    "Good to know, {name}.",
    "Glad you shared, {name}.",
]


def register_tool(name: str):
    def _decorator(fn):
        handlers[name] = fn
        return fn
    return _decorator


@register_tool("summarize_discussion")
def handle_summarize(payload: TavusEvent) -> Dict[str, Any]:
    transcript = (
        (payload.tool.arguments.get("transcript") if payload.tool else None)
        or payload.data.get("transcript")
        or ""
    )
    # Placeholder: return a trivial summary
    bullets = [line.strip() for line in transcript.split("\n") if line.strip()][:5]
    return {"summary": bullets}


@register_tool("take_meeting_notes")
def handle_take_notes(payload: TavusEvent) -> Dict[str, Any]:
    content = (
        (payload.tool.arguments.get("content") if payload.tool else None)
        or payload.data.get("content")
        or ""
    )
    return {"notes": [content] if content else []}


@register_tool("cluster_ideas")
def handle_cluster(payload: TavusEvent) -> Dict[str, Any]:
    ideas = (
        (payload.tool.arguments.get("ideas") if payload.tool else None)
        or payload.data.get("ideas")
        or []
    )
    clusters: Dict[str, list[str]] = {}
    for idea in ideas:
        key = idea.split(" ")[0].lower() if idea else "misc"
        clusters.setdefault(key, []).append(idea)
    return {"clusters": clusters}


@register_tool("print_message")
def handle_print_message(payload: TavusEvent) -> Dict[str, Any]:
    text = (
        (payload.tool.arguments.get("text") if payload.tool else None)
        or payload.data.get("text")
        or ""
    )
    print(f"[Webhook] print_message: {text}")
    return {"printed": True}


@register_tool("initiate_introduction")
def handle_initiate_introduction(payload: TavusEvent) -> Dict[str, Any]:
    print("[Webhook] Received initiate_introduction tool call. Frontend will handle script echo.")
    return {"status": "triggered"}


@register_tool("start_picnic_game")
def handle_start_picnic_game(payload: TavusEvent) -> Dict[str, Any]:
    print("[Webhook] Received start_picnic_game tool call. Frontend will handle script echo.")
    return {"status": "triggered"}


@register_tool("start_morning_enjoyment_round")
def handle_start_morning_enjoyment_round(payload: TavusEvent) -> Dict[str, Any]:
    print("[Webhook] Received start_morning_enjoyment_round tool call. Frontend will handle script echo.")
    return {"status": "triggered"}


@register_tool("start_fun_skill_round")
def handle_start_fun_skill_round(payload: TavusEvent) -> Dict[str, Any]:
    print("[Webhook] Received start_fun_skill_round tool call. Frontend will handle script echo.")
    return {"status": "triggered"}


@register_tool("start_shared_preference_task")
def handle_start_shared_preference_task(payload: TavusEvent) -> Dict[str, Any]:
    print("[Webhook] Received start_shared_preference_task tool call. Frontend will handle script echo.")
    return {"status": "triggered"}


@register_tool("transition_to_next_session")
def handle_transition_to_next_session(payload: TavusEvent) -> Dict[str, Any]:
    print("[Webhook] Received transition_to_next_session tool call. Frontend will handle script echo.")
    return {"status": "triggered"}


def _speaker_label_from_msg(m: Dict[str, Any]) -> Optional[str]:
    # Common keys seen across providers/schemas
    for k in ("display_name", "displayName", "name", "speaker_name", "speakerName"):
        v = m.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    # Nested speaker object cases
    sp = m.get("speaker")
    if isinstance(sp, dict):
        for k in ("display_name", "displayName", "name"):
            v = sp.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    # Sender/user nested objects
    for container_key in ("sender", "user", "participant"):
        c = m.get(container_key)
        if isinstance(c, dict):
            for k in ("display_name", "displayName", "name"):
                v = c.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()
    return None


def _speaker_id_from_msg(m: Dict[str, Any]) -> Optional[str]:
    # Common id-like keys
    for k in ("participant_id", "speaker_id", "user_id", "id"):
        v = m.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    # Nested objects
    for container_key in ("participant", "speaker", "user", "sender"):
        c = m.get(container_key)
        if isinstance(c, dict):
            for k in ("participant_id", "speaker_id", "user_id", "id"):
                v = c.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()
    return None


@register_tool("get_speaker_name")
def handle_get_speaker_name(payload: TavusEvent) -> Dict[str, Any]:
    """Return the latest human speaker name from transcript metadata if available.
    Strategy:
    - Look at properties.transcript (array of messages), scan from end
    - Prefer messages with role "user" or "participant"; fall back to any last message
    - Extract a display name via _speaker_label_from_msg
    """
    props = payload.properties or {}
    transcript = props.get("transcript") if isinstance(props, dict) else None
    name: Optional[str] = None
    if isinstance(transcript, list) and transcript:
        # Scan from last to first
        for msg in reversed(transcript):
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role", "")).lower()
            if role not in ("user", "participant", "speaker", "human"):
                # Prefer human turns first
                continue
            name = _speaker_label_from_msg(msg)
            if name:
                break
        # If nothing found on human roles, take the last message label if present
        if not name:
            for msg in reversed(transcript):
                if not isinstance(msg, dict):
                    continue
                name = _speaker_label_from_msg(msg)
                if name:
                    break
    return {"speaker_name": name or ""}


@register_tool("get_current_speaker")
def handle_get_current_speaker(payload: TavusEvent) -> Dict[str, Any]:
    conv_id = payload.conversation_id or ""
    # Fallback: if conversation_id missing or unknown but only one roster exists, use it
    if (not conv_id or conv_id not in ROSTER) and len(ROSTER) == 1:
        conv_id = list(ROSTER.keys())[0]
    # Prefer current payload message set
    props = payload.properties or {}
    transcript = props.get("transcript") if isinstance(props, dict) else None
    current_name = None
    current_id = None
    confident = False
    if isinstance(transcript, list) and transcript:
        for msg in reversed(transcript):
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role", "")).lower()
            if role in ("user", "participant", "speaker", "human"):
                current_name = _speaker_label_from_msg(msg)
                current_id = _speaker_id_from_msg(msg)
                confident = bool(current_name)
                break
    # Fallback to roster memory
    if (not current_name) and conv_id and conv_id in ROSTER:
        entry = ROSTER[conv_id]
        current_name = entry.get("last_speaker_name")
        current_id = entry.get("last_speaker_id")
        confident = bool(current_name)

    result = {"participant_id": current_id or "", "display_name": current_name or "", "confident": bool(confident)}
    try:
        print(f"[get_current_speaker] conv={conv_id} result={result} roster_size={len(ROSTER.get(conv_id, {}).get('participants', {}))} roster_keys={list(ROSTER.keys())}")
    except Exception:
        pass
    return result


@register_tool("get_roster")
def handle_get_roster(payload: TavusEvent) -> Dict[str, Any]:
    conv_id = payload.conversation_id or ""
    participants = []
    if conv_id and conv_id in ROSTER:
        for pid, name in ROSTER[conv_id].get("participants", {}).items():
            participants.append({"participant_id": pid, "display_name": name})
    return {"participants": participants}


def process_event(evt: TavusEvent) -> None:
    # Idempotency example: a real impl would use a DB keyed by event_id
    tool_name = evt.tool.name if evt.tool else (evt.data.get("tool") if evt.data.get("tool") is not None else None)
    if not isinstance(tool_name, str) or not tool_name:
        print(f"[Webhook] Missing or invalid tool name: {tool_name}")
        return
    handler = handlers.get(tool_name)
    if not handler:
        # Unknown tool; just log
        print(f"[Webhook] Unknown tool: {tool_name}")
        return
    try:
        result = handler(evt)
        # TODO: If Tavus expects async result submission, call Tavus API here.
        print(f"[Webhook] Processed {tool_name} result=", result)
    except Exception as e:
        print(f"[Webhook] Handler error for {tool_name}: {e}")


def _extract_tool_calls_from_payload(payload: Dict[str, Any]) -> List[ToolCall]:
    calls: List[ToolCall] = []
    props = payload.get("properties") or {}
    # Newer Tavus interaction format: event_type=conversation.tool_call with properties.name/arguments
    if payload.get("event_type") == "conversation.tool_call":
        if isinstance(props, dict) and isinstance(props.get("name"), str):
            args = props.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {"raw": args}
            calls.append(ToolCall(name=props["name"], arguments=args, call_id=props.get("id") or payload.get("inference_id")))
            return calls
    # Direct tool format
    direct_tool = payload.get("tool")
    if isinstance(direct_tool, dict) and isinstance(direct_tool.get("name"), str):
        args = direct_tool.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {"raw": args}
        calls.append(ToolCall(name=direct_tool["name"], arguments=args, call_id=direct_tool.get("id")))
        return calls
    # Some payloads may nest inside data
    data = payload.get("data") or {}
    if isinstance(data, dict) and isinstance(data.get("tool"), str):
        args = data.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {"raw": args}
        calls.append(ToolCall(name=str(data["tool"]), arguments=args, call_id=data.get("id")))
        return calls
    # Transcription-style payloads: properties.transcript[].tool_calls
    props = payload.get("properties") or {}
    transcript = props.get("transcript") if isinstance(props, dict) else None
    if isinstance(transcript, list):
        for msg in transcript:
            if not isinstance(msg, dict):
                continue
            tcs = msg.get("tool_calls")
            if not isinstance(tcs, list):
                continue
            for tc in tcs:
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function") or {}
                name = fn.get("name")
                args = fn.get("arguments")
                if not isinstance(name, str):
                    continue
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {"raw": args}
                elif not isinstance(args, dict):
                    args = {}
                calls.append(ToolCall(name=name, arguments=args, call_id=tc.get("id")))
    return calls


def _persist_webhook_payload(payload: Dict[str, Any]) -> None:
    """Append the raw payload to a JSONL file and, if present, append
    transcript lines to a plain text file per conversation.
    Files are created under <root>/webhook/<conversation_id>/ by default.
    Override with env WEBHOOK_OUT_DIR to point elsewhere.
    """
    try:
        conv_id = str(payload.get("conversation_id") or "unknown")
        out_root = os.getenv("WEBHOOK_OUT_DIR") or "webhook"
        base = Path(out_root) / conv_id
        base.mkdir(parents=True, exist_ok=True)
        # Save raw JSON event as JSONL
        (base / "events.jsonl").open("a", encoding="utf-8").write(json.dumps(payload, ensure_ascii=False) + "\n")
        # If transcript present, append a readable version
        props = payload.get("properties") or {}
        transcript = props.get("transcript") if isinstance(props, dict) else None
        if isinstance(transcript, list) and transcript:
            ts = payload.get("timestamp") or datetime.utcnow().isoformat()
            with (base / "transcript.txt").open("a", encoding="utf-8") as f:
                f.write(f"\n=== Event @ {ts} ===\n")
                for msg in transcript:
                    if not isinstance(msg, dict):
                        continue
                    # Prefer a human-friendly display name when available
                    # Reuse the same label extraction as our tool
                    def _name_from(m: Dict[str, Any]) -> Optional[str]:
                        return _speaker_label_from_msg(m)

                    role = str(msg.get("role", ""))
                    content = str(msg.get("content", ""))
                    label = _name_from(msg)
                    if not label:
                        label = role or "speaker"
                    if label or content:
                        # Example: "Julie (user): Hello there"
                        suffix = f" ({role})" if role and role.lower() not in label.lower() else ""
                        f.write(f"{label}{suffix}: {content}\n")
    except Exception as e:
        print(f"[Webhook] Failed to persist payload: {e}")


def _maybe_get_recording_url(payload: Dict[str, Any]) -> Optional[str]:
    """Try to find a recording / video URL in common locations of the payload."""
    # Direct top-level fields
    for k in ("recording_url", "video_url", "media_url"):
        v = payload.get(k)
        if isinstance(v, str) and v.startswith("http"):
            return v
    data = payload.get("data") or {}
    if isinstance(data, dict):
        for k in ("recording_url", "video_url", "media_url"):
            v = data.get(k)
            if isinstance(v, str) and v.startswith("http"):
                return v
    props = payload.get("properties") or {}
    if isinstance(props, dict):
        for k in ("recording_url", "video_url", "media_url"):
            v = props.get(k)
            if isinstance(v, str) and v.startswith("http"):
                return v
    return None


def _broadcast_echo(conversation_id: str, text: str, inference_id: Optional[str] = None) -> None:
    """Send a conversation.echo to Tavus to make the replica say the provided text.
    Requires ENABLE_TAVUS_ECHO=true and TAVUS_API_KEY to be set."""
    if not ENABLE_TAVUS_ECHO:
        return
    if not TAVUS_API_KEY:
        print("[Webhook] ENABLE_TAVUS_ECHO set but TAVUS_API_KEY missing; skipping echo")
        return
    # Note: Some Tavus deployments expect a leaner body without message_type.
    # We keep conversation_id + event_type + properties, and log full response.
    payload = {
        "event_type": "conversation.echo",
        "conversation_id": conversation_id,
        "properties": {
            "modality": "text",
            "text": text,
            "done": True,
        },
    }
    if inference_id:
        payload["properties"]["inference_id"] = inference_id
    try:
        r = requests.post(
            TAVUS_INTERACTIONS_ENDPOINT,
            headers={"x-api-key": TAVUS_API_KEY, "Content-Type": "application/json"},
            json=payload,
            timeout=10,
        )
        try:
            body_preview = r.text[:300]
        except Exception:
            body_preview = "<no body>"
        print(f"[Webhook] Sent conversation.echo status={r.status_code} body={body_preview}")
    except Exception as e:
        print(f"[Webhook] Failed to send conversation.echo: {e}")


def _s3_client_from_env() -> Optional[Any]:
    bucket = os.getenv("S3_BUCKET")
    if not bucket:
        return None
    # boto3 will pick up AWS creds from env/profile/IMDS
    try:
        s3 = boto3.client("s3", region_name=os.getenv("AWS_REGION") or None)
        return s3
    except Exception as e:
        print(f"[Webhook] boto3 S3 client error: {e}")
        return None


def _upload_recording_to_s3(conv_id: str, url: str) -> Optional[str]:
    bucket = os.getenv("S3_BUCKET")
    if not bucket:
        print("[Webhook] S3_BUCKET not set; skip upload")
        return None
    prefix = os.getenv("S3_PREFIX", "recordings/").strip()
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    # Download to temp file first
    try:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name
        urllib.request.urlretrieve(url, tmp_path)
    except Exception as e:
        print(f"[Webhook] Failed to download recording: {e}")
        return None
    # Compute key and upload
    name = url.split("/")[-1] or f"{uuid.uuid4()}.mp4"
    key = f"{prefix}{conv_id}/{name}"
    try:
        s3 = _s3_client_from_env()
        if not s3:
            return None
        s3.upload_file(tmp_path, bucket, key)
        print(f"[Webhook] Uploaded recording to s3://{bucket}/{key}")
        return f"s3://{bucket}/{key}"
    except Exception as e:
        print(f"[Webhook] S3 upload failed: {e}")
        return None
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass


def _update_roster_from_payload(payload: Dict[str, Any]) -> None:
    conv_id = str(payload.get("conversation_id") or "")
    if not conv_id:
        return
    entry = ROSTER.setdefault(conv_id, {"participants": {}, "last_speaker_id": None, "last_speaker_name": None})
    props = payload.get("properties") or {}
    # Update from transcript messages
    transcript = props.get("transcript") if isinstance(props, dict) else None
    if isinstance(transcript, list) and transcript:
        # Track last human message
        last_id = None
        last_name = None
        for msg in transcript:
            if not isinstance(msg, dict):
                continue
            name = _speaker_label_from_msg(msg)
            pid = _speaker_id_from_msg(msg)
            if pid and name:
                entry["participants"][pid] = name
            role = str(msg.get("role", "")).lower()
            if role in ("user", "participant", "speaker", "human"):
                if name:
                    last_name = name
                # Heuristic: if platform doesn't send names, try to capture "my name is X" / "I'm X" / "I am X"
                if not name:
                    content = str(msg.get("content", ""))
                    # Very conservative patterns to avoid false positives
                    # Examples captured: "my name is Alex", "I'm Alex", "I am Alex"
                    m = re.search(r"\bmy name is\s+([A-Z][a-zA-Z'-]{1,40})\b", content, flags=re.I)
                    if not m:
                        m = re.search(r"\bI\s*am\s+([A-Z][a-zA-Z'-]{1,40})\b", content)
                    if not m:
                        m = re.search(r"\bI\s*'\s*m\s+([A-Z][a-zA-Z'-]{1,40})\b", content)
                    if m:
                        last_name = m.group(1)
                if pid:
                    last_id = pid
        if last_id or last_name:
            entry["last_speaker_id"] = last_id
            entry["last_speaker_name"] = last_name


@app.post("/tavus/callback")
async def tavus_callback(request: Request, background: BackgroundTasks):
    verify_secret(request)
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    try:
        # Persist every payload for debugging/traceability
        _persist_webhook_payload(payload)
        # Update in-memory roster from this real-time payload
        try:
            _update_roster_from_payload(payload)
        except Exception:
            pass
        tool_calls = _extract_tool_calls_from_payload(payload)
        # If a recording URL is present, upload it in background
        rec_url = _maybe_get_recording_url(payload)
        if rec_url:
            conv = str(payload.get("conversation_id") or "unknown")
            background.add_task(_upload_recording_to_s3, conv, rec_url)
        if tool_calls:
            # Process synchronously so Tavus can receive results immediately in the HTTP response
            tool_results = []
            for call in tool_calls:
                evt = TavusEvent.model_validate({
                    **payload,
                    "tool": call.model_dump(),
                    "event_id": payload.get("event_id") or str(uuid.uuid4()),
                    "timestamp": payload.get("timestamp") or time.time(),
                    "event_type": payload.get("event_type") or "tool_call",
                })
                try:
                    result = handlers[call.name](evt)
                except Exception as e:
                    result = {"error": str(e)}
                    print(f"[Webhook] Handler error for {call.name}: {e}")
                tool_results.append({
                    "tool": call.name,
                    "tool_call_id": call.call_id,
                    "arguments": call.arguments,
                    "result": result,
                })
                # Optional varied affirmation echo when we know the current speaker with confidence
                if call.name == "get_current_speaker" and ENABLE_TAVUS_ECHO and ACK_TEMPLATES:
                    try:
                        name = str((result or {}).get("display_name") or "").strip()
                        confident = bool((result or {}).get("confident"))
                    except Exception:
                        name = ""
                        confident = False
                    if name and confident:
                        import random
                        inferred_text = random.choice(ACK_TEMPLATES).format(name=name)
                        inf_id = payload.get("inference_id") or call.call_id
                        _broadcast_echo(str(payload.get("conversation_id") or ""), inferred_text, inference_id=inf_id)
            # Mirror common tool-call response shapes: include both tool_results array and simplified mappings
            # Primary shape: tool_calls array with id/name/result minimal payload
            tool_calls_min = [
                {"id": tr["tool_call_id"], "name": tr["tool"], "result": tr["result"]}
                for tr in tool_results
            ]
            response_body: Dict[str, Any] = {
                "ok": True,
                "tool_calls": tool_calls_min,
                "results": {tr["tool"]: tr["result"] for tr in tool_results},
            }
            # Legacy / exploratory shapes retained for compatibility (can remove later)
            response_body["tool_results"] = tool_results
            response_body["responses"] = [
                {"tool_call_id": tr["tool_call_id"], "result": tr["result"]}
                for tr in tool_results
            ]
            if len(tool_results) == 1:
                response_body["tool_call_id"] = tool_results[0]["tool_call_id"]
                response_body["result"] = tool_results[0]["result"]
            try:
                print(f"[Webhook] Responding with tool_results: {response_body}")
            except Exception:
                pass
            return response_body
        else:
            # No tool calls found, still log the event type for visibility
            print(f"[Webhook] Received event_type={payload.get('event_type')} with no tool calls")
    except Exception as e:
        print(f"[Webhook] Error parsing payload: {e}")

    return {"ok": True}


@app.post("/admin/upload_recording")
async def admin_upload_recording(request: Request):
    """Manual trigger to upload a recording URL to S3.
    Body: { conversation_id: str, url: str }
    """
    verify_secret(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    conv_id = str((body or {}).get("conversation_id") or "").strip()
    url = str((body or {}).get("url") or "").strip()
    if not conv_id or not url:
        raise HTTPException(status_code=400, detail="conversation_id and url are required")
    out = _upload_recording_to_s3(conv_id, url)
    if not out:
        raise HTTPException(status_code=500, detail="Upload failed (see server logs)")
    return {"ok": True, "location": out}


@app.post("/roster/register")
async def roster_register(request: Request):
    """Register or update a participant's display name for a conversation.
    Body: { conversation_id: str, display_name: str, participant_id?: str, active?: bool }
    """
    verify_secret(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    conv_id = str((body or {}).get("conversation_id") or "").strip()
    name = str((body or {}).get("display_name") or "").strip()
    pid = str((body or {}).get("participant_id") or "").strip()
    active = bool((body or {}).get("active") or False)
    if not conv_id or not name:
        raise HTTPException(status_code=400, detail="conversation_id and display_name are required")
    entry = ROSTER.setdefault(conv_id, {"participants": {}, "last_speaker_id": None, "last_speaker_name": None})
    # Use participant_id if provided, else fall back to name as a synthetic key
    key = pid if pid else f"name:{name.lower()}"
    # Check if this is a new participant
    is_new = key not in entry["participants"]
    entry["participants"][key] = name
    if active:
        entry["last_speaker_id"] = key
        entry["last_speaker_name"] = name
    # Send intro echo when new participant joins (if ENABLE_TAVUS_ECHO is on)
    if is_new and ENABLE_TAVUS_ECHO:
        intro_text = f"{name} has joined the call"
        _broadcast_echo(conv_id, intro_text)
    return {"ok": True, "conversation_id": conv_id, "participant_id": key, "display_name": name, "active": active}


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/debug/roster/{conversation_id}")
async def debug_roster(conversation_id: str):
    """Inspect in-memory roster state for a conversation."""
    entry = ROSTER.get(conversation_id)
    return entry or {"participants": {}, "last_speaker_id": None, "last_speaker_name": None}
