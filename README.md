# Tavus Test Harness

One repo, one README. This is a minimal harness to create personas (agents) and conversations against Tavus APIs, optionally with a local webhook for tool callbacks and (native) S3 recording.

## 1. Environment Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
${EDITOR:-nano} .env    # add TAVUS_API_KEY and other values
```

You only need to do this once per clone. Always `source .venv/bin/activate` before running commands.

### .env Variables (single place to configure)
Required:
- `TAVUS_API_KEY` – your Tavus API key.

Optional (native S3 recording; used to auto-build conversation properties with `--use-s3-recording-from-env`):
- `S3_RECORDING_ASSUME_ROLE_ARN`
- `S3_RECORDING_BUCKET_REGION`
- `S3_RECORDING_BUCKET_NAME`

Optional (webhook fallback upload path):
- `AWS_REGION`
- `S3_BUCKET`
- `S3_PREFIX`

Optional (callback + security):
- `WEBHOOK_URL` – populated automatically by `bin/set_webhook_url.sh` or `bin/quickstart.sh`.
- `WEBHOOK_SHARED_SECRET` – if set, callbacks must include `x-webhook-secret` (or `x-tavus-secret`).

Replica convenience:
- `TAVUS_REPLICA_ID` – default replica if you don’t pass `--replica-id`.

## 2. Three Run Modes

### Mode A: Simple (create persona + conversation by name)
Use existing config files and run a test conversation (no recording).
```bash
source .venv/bin/activate
bin/tune.sh persona --config configs/persona/facilitator.example.json --update || bin/tune.sh persona --config configs/persona/facilitator.example.json
bin/tune.sh conversation --config configs/conversation/facilitator_kickoff.json --test-mode
```
Print payload only:
```bash
bin/tune.sh persona --config configs/persona/facilitator.example.json --print-payload --dry-run
```

### Mode B: Recording (native Tavus S3)
Two options:

1) Easiest: add `enable_recording: true` at the top-level of your conversation config. The CLI will auto-inject default S3 settings (role/region/bucket) used in this project.
```bash
source .venv/bin/activate
bin/tune.sh conversation \
  --config configs/conversation/facilitator_kickoff.recording.json \
  --disable-test-mode \
  --replica-id r4317e64d25a
```

2) Env-driven: populate recording vars in `.env` then create a conversation with recording enabled.
```bash
source .venv/bin/activate
bin/tune.sh persona --config configs/persona/facilitator.example.json --update || bin/tune.sh persona --config configs/persona/facilitator.example.json
bin/tune.sh conversation \
  --config configs/conversation/facilitator_kickoff.json \
  --use-s3-recording-from-env \
  --disable-test-mode \
  --replica-id r4317e64d25a
```
If you need a custom properties file instead:
```bash
bin/tune.sh conversation --replica-id r4317e64d25a --properties-file configs/conversation/recording.s3.example.json --disable-test-mode
```

### Mode C: Full local (webhook + tunnel + live conversation)
Three terminals: A webhook, B tunnel, C create conversation.

Terminal A – webhook:
```bash
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
Terminal B – tunnel, then persist callback:
```bash
ngrok http 8000
bin/set_webhook_url.sh "https://<your-ngrok>.ngrok-free.app/tavus/callback"
```
Terminal C – run persona + conversation (with optional recording):
```bash
source .venv/bin/activate
bin/tune.sh persona --config configs/persona/facilitator.example.json --update || bin/tune.sh persona --config configs/persona/facilitator.example.json
bin/tune.sh conversation \
  --config configs/conversation/facilitator_kickoff.json \
  --replica-id r4317e64d25a \
  --use-s3-recording-from-env \
  --disable-test-mode
```
Shortcut all-in-one (webhook + tunnel + test conversation):
```bash
bin/quickstart.sh -- --test-mode
```

## 3. Native Recording IAM Summary
Role trust: AWS Account `291871421005` with ExternalId `tavus`. Policy needs S3 write perms to your bucket. Put role ARN, region, bucket name in `.env` for Mode B/C.

## 4. Minimal Presets Reference
Presets live under `presets/layers/`. Use their file stem names in persona configs:
- LLM: `tavus_llama_4`, `tavus_llama`, `tavus_gpt_4o`, `tavus_gpt_4o_mini`
- TTS: `cartesia_sonic`, `cartesia_sonic.teamwise`
- STT: `tavus_advanced`, `names_meeting.demo`, `teamwise.demo`, `janet.demo`
- Perception: `basic`, `raven_0`, `off`

Attach tools via persona config `tools` array or CLI `--tools`: examples include `summarize_discussion`, `take_meeting_notes`, `cluster_ideas`, `get_speaker_name`, `get_current_speaker`, `get_roster`, `print_message`.

## 5. Common Troubleshooting
- Missing module (e.g., boto3): ensure you activated `.venv` and ran `pip install -r requirements.txt`.
- 400 on recording creation: verify IAM trust (Principal 291871421005, ExternalId tavus) and bucket policy.
- No callbacks: check `WEBHOOK_URL` in `.env`, tunnel active, and conversation not in test mode if expecting full behavior.
- Persona update fails (`--update requires persona_id`): run without `--update` once to create or set `target_persona_name` in config.

## 6. Logs
All API calls logged under `logs/<timestamp>_{persona|conversation}_*/`. Webhook events and transcripts saved under `logs/webhook/<conversation_id>/`.

## 7. One‑liners
Create a quick test conversation (auto-picks replica):
```bash
bin/tune.sh conversation --name "Quick Test" --context "Hello there." --test-mode
```
Create a recording conversation from env (replica required):
```bash
bin/tune.sh conversation --replica-id r4317e64d25a --use-s3-recording-from-env --disable-test-mode
```
Create a recording conversation using the shortcut flag in config:
```bash
bin/tune.sh conversation --config configs/conversation/facilitator_kickoff.recording.json --replica-id r4317e64d25a --disable-test-mode
```

## 8. Cleanup
Remove old logs:
```bash
bin/clean_logs.sh --days 0
```

## 9. Updating This Harness
Add new presets in `presets/layers/<kind>/your_name.json` then reference by file stem in persona config fields `llm`, `tts`, `stt`, `perception`.

---
Single README complete. For layer details, see `presets/README.md`.
