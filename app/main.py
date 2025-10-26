from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from typing import Any, Dict, Optional, cast, List
import os
import time
import uuid
import json
from datetime import datetime
from pathlib import Path


APP_SECRET = os.getenv("WEBHOOK_SHARED_SECRET", "")


class ToolCall(BaseModel):
    name: str = Field(..., description="Tool/function name")
    arguments: Dict[str, Any] = Field(default_factory=dict)


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
    # Direct tool format
    direct_tool = payload.get("tool")
    if isinstance(direct_tool, dict) and isinstance(direct_tool.get("name"), str):
        args = direct_tool.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {"raw": args}
        calls.append(ToolCall(name=direct_tool["name"], arguments=args))
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
        calls.append(ToolCall(name=str(data["tool"]), arguments=args))
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
                calls.append(ToolCall(name=name, arguments=args))
    return calls


def _persist_webhook_payload(payload: Dict[str, Any]) -> None:
    """Append the raw payload to a JSONL file and, if present, append
    transcript lines to a plain text file per conversation.
    Files are created under logs/webhook/<conversation_id>/.
    """
    try:
        conv_id = str(payload.get("conversation_id") or "unknown")
        base = Path("logs") / "webhook" / conv_id
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
                    role = str(msg.get("role", ""))
                    content = str(msg.get("content", ""))
                    if role or content:
                        f.write(f"{role}: {content}\n")
    except Exception as e:
        print(f"[Webhook] Failed to persist payload: {e}")


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
        tool_calls = _extract_tool_calls_from_payload(payload)
        if tool_calls:
            for call in tool_calls:
                evt = TavusEvent.model_validate({
                    **payload,
                    "tool": call.model_dump(),
                    "event_id": payload.get("event_id") or str(uuid.uuid4()),
                    "timestamp": payload.get("timestamp") or time.time(),
                    "event_type": payload.get("event_type") or "tool_call",
                })
                background.add_task(process_event, evt)
        else:
            # No tool calls found, still log the event type for visibility
            print(f"[Webhook] Received event_type={payload.get('event_type')} with no tool calls")
    except Exception as e:
        print(f"[Webhook] Error parsing payload: {e}")

    return {"ok": True}


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
