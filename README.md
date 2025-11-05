# Tavus Test Harness (Python)

Single-CLI workflow to create Personas and Conversations against Tavus APIs. Keep it simple: a few commands to get started locally, plus an optional local webhook backend for tool callbacks.

## Getting started

```bash
# 1) Create a virtualenv and install deps
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2) Configure your API key
cp .env.example .env && ${EDITOR:-nano} .env   # set TAVUS_API_KEY
```

That’s it for setup. All commands are run from the repo root.

## Start the Dmo 
```bash
./bin/demo.sh
```

## Main commands (persona and conversation)

- Create or update a persona from the example config:
```bash
# Create
bin/tune.sh persona --config configs/persona/facilitator.example.json

# Update (PATCH) using fields from the same config
bin/tune.sh persona --config configs/persona/facilitator.example.json --update

# (Optional) Print the payload without sending
bin/tune.sh persona --config configs/persona/facilitator.example.json --print-payload --dry-run
```

- Create a conversation (choose one):
```bash
# From the example conversation config (safe test mode)
bin/tune.sh conversation --config configs/conversation/facilitator_kickoff.json --test-mode

# Or provide a persona by ID directly
bin/tune.sh conversation \
  --persona-id pe_XXXXXXXX \
  --name "Facilitator Demo" \
  --context "Let's kick off the session." \
  --document-retrieval-strategy balanced \
  --test-mode
```

- One‑shot flow (create/update persona → create conversation):
```bash
bin/scenarios/run_pair.sh \
  configs/persona/facilitator.example.json \
  configs/conversation/facilitator_kickoff.json \
  --update-persona --disable-test-mode
```

Logs for all requests and responses are saved in `logs/`.

## Try it: one‑command quickstart (webhook + tunnel + conversation)

Run everything with one command (requires ngrok installed on PATH):

```bash
bin/quickstart.sh -- --test-mode
```

What it does:
- Ensures venv and installs deps if needed
- Starts uvicorn on :8000
- Launches ngrok and reads the public URL
- Writes `WEBHOOK_URL` to `.env`
- Creates a test conversation and prints the `conversation_url`

Note: the STT hotwords help recognize and address participants by name. If you need alternate spellings or nicknames for “Mikkeline” or “Akila”, we can add them to the hotwords list in `presets/layers/stt/names_meeting.demo.json` (and/or your active STT preset).

## Recording to S3

There are two ways to get recordings into your S3 bucket. Use native Tavus recording when possible; use the webhook fallback if you can't or don't want to change IAM right now.

### Option A — Native Tavus S3 recording (recommended)

1) In AWS IAM:
   - Create an IAM Role (e.g., `CVIRecordingRole`) trusted by Tavus with ExternalId `tavus`:
     - Principal AWS Account: `291871421005`
     - ExternalId: `tavus`
     - Max session duration: 12 hours
   - Attach a policy granting S3 writes to your bucket (replace the bucket name if needed):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "TavusS3Access",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:ListBucketMultipartUploads",
        "s3:AbortMultipartUpload",
        "s3:ListBucketVersions",
        "s3:ListBucket",
        "s3:GetObjectVersion",
        "s3:ListMultipartUploadParts"
      ],
      "Resource": [
        "arn:aws:s3:::tavus-recording",
        "arn:aws:s3:::tavus-recording/*"
      ]
    }
  ]
}
```

2) Create the conversation with recording enabled:

- From a properties file (explicit):

```bash
source .venv/bin/activate
python tune.py conversation \
  --replica-id rf4703150052 \
  --properties-file configs/conversation/recording.s3.julie.json
```

Or with curl (replace your API key if not in `.env`):
Alternatively, drive from env (no file needed):

```
# In .env
S3_RECORDING_ASSUME_ROLE_ARN=arn:aws:iam::268922422948:role/CVIRecordingRole
S3_RECORDING_BUCKET_REGION=eu-north-1
S3_RECORDING_BUCKET_NAME=tavus-recording

# Then
source .venv/bin/activate
python tune.py conversation --replica-id rf4703150052 --use-s3-recording-from-env
```

```bash
curl --request POST \
  --url https://tavusapi.com/v2/conversations \
  --header 'Content-Type: application/json' \
  --header "x-api-key: $TAVUS_API_KEY" \
  --data '{
    "properties": {
      "enable_recording": true,
      "aws_assume_role_arn": "arn:aws:iam::268922422948:role/CVIRecordingRole",
      "recording_s3_bucket_region": "eu-north-1",
      "recording_s3_bucket_name": "tavus-recording"
    },
    "replica_id": "rf4703150052"
  }'
```

3) Join the `conversation_url` and start/stop recording from the meeting UI. Files will appear in your S3 bucket.

If you get HTTP 400 mentioning Daily and bucket config, verify the IAM Role trust policy (Principal `291871421005`, ExternalId `tavus`), the role’s S3 permissions, and (if used) your bucket/KMS policies.

### Option B — Webhook fallback upload (no IAM changes required)

If you can’t update IAM now, the webhook can auto-upload delivered recording URLs to S3. Enable it by setting these in `.env` (already present in `.env.example`):

```
AWS_REGION=eu-north-1
S3_BUCKET=tavus-recording
S3_PREFIX=recordings/
```
## Backend for callbacks (3 terminals)

If you want tool callbacks (e.g., printing when the model calls a tool), run the included FastAPI webhook locally and expose it via a tunnel.

- Terminal A — Webhook backend
```bash
uvicorn app.main:app --reload --port 8000
```

- Terminal B — Public tunnel (and export callback URL)
```bash
ngrok http 8000
# Persist the callback URL into .env (preferred)
bin/set_webhook_url.sh "https://<your-ngrok-id>.ngrok.io/tavus/callback"
```

- Terminal C — Create persona and conversation
```bash
# One‑shot: persona update + conversation
bin/scenarios/run_pair.sh \
  configs/persona/facilitator.example.json \
  configs/conversation/facilitator_kickoff.json \
  --update-persona --disable-test-mode

# Or just create a conversation (uses WEBHOOK_URL by default)
bin/tune.sh conversation --config configs/conversation/facilitator_kickoff.json --test-mode
```
- Webhook logs are saved under `logs/webhook/<conversation_id>/` (events.jsonl and transcript.txt).

That’s all you need to run locally. When ready, you can deploy the webhook service and set the `callback_url` to your hosted endpoint.

### Webhook environment variables (.env)

The webhook reads configuration from `.env` (loaded automatically on startup):

- WEBHOOK_SHARED_SECRET (optional): if set, incoming requests must include `x-webhook-secret: <value>` (or `x-tavus-secret`).
- AWS_REGION (optional): region for S3 fallback uploads (e.g., `eu-north-1`).
- S3_BUCKET (optional): if set, enables webhook fallback recording upload to this bucket.
- S3_PREFIX (optional): key prefix for uploaded files (default `recordings/`).
- WEBHOOK_URL (note): not used by the webhook itself; the CLI uses it as a default `callback_url` when creating conversations.
  - Set it once with: `bin/set_webhook_url.sh "https://<your-tunnel>/tavus/callback"`

Example `.env` snippet:

```
TAVUS_API_KEY=your_api_key_here
WEBHOOK_SHARED_SECRET=dev-secret
AWS_REGION=eu-north-1
S3_BUCKET=tavus-recording
S3_PREFIX=recordings/
WEBHOOK_URL=https://<your-ngrok>.ngrok-free.app/tavus/callback
```

Note on native Tavus S3 recording: do not set `AWS_ROLE_ARN`/`S3_REGION` in `.env`. Those belong in the conversation `properties` (see `configs/conversation/recording.s3.julie.json`). The webhook env vars above are only for the fallback upload path.

## Webhook shared secret (required for secured callbacks)

To prevent unauthorized posts to your webhook, the backend supports a shared secret. When the secret is set, every incoming request must include a matching header, or it will be rejected with 401.

- Environment variable (read by the webhook backend):
  - `WEBHOOK_SHARED_SECRET` — shared secret value. If set, the backend enforces verification.
- Accepted header names (either works):
  - `x-webhook-secret`
  - `x-tavus-secret`

### Local development

For quick local testing you can leave the secret unset:

```bash
# Terminal where uvicorn runs
unset WEBHOOK_SHARED_SECRET
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

If you prefer to test with the secret enabled:

```bash
export WEBHOOK_SHARED_SECRET="my-dev-secret"
uvicorn app.main:app --host 0.0.0.0 --port 8000

# When sending a manual test request
curl -s -X POST "http://localhost:8000/tavus/callback" \
  -H "Content-Type: application/json" \
  -H "x-webhook-secret: my-dev-secret" \
  -d '{"event_type":"local_test","conversation_id":"local","properties":{"transcript":[{"role":"user","content":"hello"}]}}'
```

### Production usage

1) Set `WEBHOOK_SHARED_SECRET` in your runtime environment (container/host/secret store).
2) Configure the sender (Tavus platform or your proxy) to include the same secret value on every callback in one of the supported headers:

```
x-webhook-secret: <your-secret>
```

If the header is missing or the value doesn’t match, the webhook responds with HTTP 401 and the event is ignored.

### Troubleshooting

- Seeing 401 in the webhook terminal logs? Ensure `WEBHOOK_SHARED_SECRET` is set (or unset) consistently between your server and the callback sender. For local tests with tunnels, either:
  - Unset the secret on the server; or
  - Include `-H "x-webhook-secret: <value>"` in your test requests and make sure Tavus (or your forwarder) adds the same header.
- No events in `logs/webhook/<conversation_id>/`? Confirm that:
  - Your `callback_url` ends with `/tavus/callback` and points to the public tunnel URL.
  - The uvicorn server is listening on the same port your tunnel forwards to.
  - You are not in `--test-mode` if you are expecting a live session.
