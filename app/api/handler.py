"""Kit API — Lambda handler bridging API Gateway to the AgentCore runtime.

POST body: {"prompt": "...", "session_id": "optional, >=33 chars", "actor_id": "optional"}
Response:  {"result": "...", "session_id": "..."}

The session_id in the response can be sent back on the next request for
conversation continuity (Kit persists sessions in AgentCore Memory).
"""

import json
import os
import uuid

import boto3

RUNTIME_ARN = os.environ["KIT_RUNTIME_ARN"]

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

    session_id = body.get("session_id") or f"kit-api-{uuid.uuid4()}"
    if not isinstance(session_id, str) or len(session_id) < 33:
        return _resp(400, {"error": "'session_id' must be a string of at least 33 characters"})

    payload = {"prompt": prompt}
    actor_id = body.get("actor_id")
    if isinstance(actor_id, str) and actor_id:
        payload["actor_id"] = actor_id

    response = client.invoke_agent_runtime(
        agentRuntimeArn=RUNTIME_ARN,
        runtimeSessionId=session_id,
        payload=json.dumps(payload).encode(),
    )

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
