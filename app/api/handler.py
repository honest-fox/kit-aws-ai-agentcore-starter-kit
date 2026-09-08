"""Kit API — Lambda handler bridging API Gateway to the AgentCore runtime.

POST body: {"prompt": "...", "session_id": "optional, >=33 chars", "actor_id": "optional"}
Response:  {"result": "...", "session_id": "..."}

The session_id in the response can be sent back on the next request for
conversation continuity (Kit persists sessions in AgentCore Memory).

SECURITY: actor_id selects the caller's long-term memory namespace and is
caller-asserted, not authenticated. Set it server-side from your own
authenticated session; never forward it straight from an untrusted client.
See docs/security.md.
"""

import json
import os
import re
import uuid

import boto3

RUNTIME_ARN = os.environ["KIT_RUNTIME_ARN"]

# Bounds a single request's model spend. API Gateway alone would accept a
# body up to 10 MB, which is a large token bill per call.
MAX_PROMPT_CHARS = int(os.environ.get("KIT_MAX_PROMPT_CHARS", "20000"))

# actor_id becomes a memory namespace path segment: keep separators and
# traversal sequences out of it. Mirrors _valid_actor_id in app/kit/main.py.
ACTOR_ID_MAX_LEN = 128
ACTOR_ID_RE = re.compile(r"\A[A-Za-z0-9\-_.:@]{1,%d}\Z" % ACTOR_ID_MAX_LEN)

client = boto3.client("bedrock-agentcore")


def _resp(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def _aggregate_stream(response) -> str:
    """Collect streamed text deltas from the runtime's SSE response."""
    text_parts = []
    buffer = b""
    for chunk in response["response"].iter_chunks():
        buffer += chunk
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            line = line.strip()
            if not line.startswith(b"data: "):
                continue
            try:
                event = json.loads(line[len(b"data: "):])
            except json.JSONDecodeError:
                continue
            delta = (
                event.get("event", {})
                .get("contentBlockDelta", {})
                .get("delta", {})
                .get("text")
            )
            if delta:
                text_parts.append(delta)
    return "".join(text_parts)


def handler(event, context):
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _resp(400, {"error": "Request body must be valid JSON"})

    prompt = body.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return _resp(400, {"error": "'prompt' (non-empty string) is required"})
    if len(prompt) > MAX_PROMPT_CHARS:
        return _resp(
            413,
            {"error": f"'prompt' exceeds {MAX_PROMPT_CHARS} characters"},
        )

    session_id = body.get("session_id") or f"kit-api-{uuid.uuid4()}"
    if not isinstance(session_id, str) or len(session_id) < 33:
        return _resp(400, {"error": "'session_id' must be a string of at least 33 characters"})

    payload = {"prompt": prompt}
    actor_id = body.get("actor_id")
    if actor_id is not None:
        if not (isinstance(actor_id, str) and ACTOR_ID_RE.match(actor_id)) or actor_id in (".", ".."):
            return _resp(
                400,
                {"error": "'actor_id' must be 1-128 chars of [A-Za-z0-9-_.:@]"},
            )
        payload["actor_id"] = actor_id

    try:
        response = client.invoke_agent_runtime(
            agentRuntimeArn=RUNTIME_ARN,
            runtimeSessionId=session_id,
            payload=json.dumps(payload).encode(),
        )
    except Exception:
        # Detail goes to CloudWatch; the caller gets no internals.
        print(f"invoke_agent_runtime failed for session {session_id}", flush=True)
        raise

    content_type = response.get("contentType", "")
    if "text/event-stream" in content_type:
        result = _aggregate_stream(response)
    else:
        raw = response["response"].read()
        try:
            parsed = json.loads(raw)
            result = parsed.get("result", parsed) if isinstance(parsed, dict) else parsed
        except json.JSONDecodeError:
            result = raw.decode(errors="replace")

    return _resp(200, {"result": result, "session_id": session_id})
