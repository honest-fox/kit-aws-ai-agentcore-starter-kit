"""Transport between the harness and a deployed Kit agent.

The runner depends on the Transport protocol, never on boto3 directly, so
every orchestration test runs offline against FakeTransport.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Response:
    text: str
    latency_ms: float = 0.0


class Transport(Protocol):
    def send(self, prompt: str, session_id: str, actor_id: str) -> Response: ...


def new_session_id(run_id: str, case_id: str, turn_index: int = 0) -> str:
    """AgentCore requires runtime session ids of at least 33 characters."""
    base = f"eval-{run_id}-{case_id}-{turn_index}"
    if len(base) < 33:
        base = f"{base}-{uuid.uuid4().hex}"
    return base[:96]


def parse_sse_stream(lines) -> str:
    """Concatenate text deltas from the runtime's SSE response."""
    chunks: list[str] = []
    for raw in lines:
        if not raw or not raw.startswith(b"data: "):
            continue
        try:
            event = json.loads(raw[6:])
        except json.JSONDecodeError:
            continue
        delta = (
            event.get("event", {})
            .get("contentBlockDelta", {})
            .get("delta", {})
            .get("text")
        )
        if delta:
            chunks.append(delta)
    return "".join(chunks)


class RuntimeTransport:
    """Invoke the AgentCore runtime directly, as the API Lambda does."""

    def __init__(self, runtime_arn: str, client):
        self._runtime_arn = runtime_arn
        self._client = client

    def send(self, prompt: str, session_id: str, actor_id: str) -> Response:
        started = time.monotonic()
        resp = self._client.invoke_agent_runtime(
            agentRuntimeArn=self._runtime_arn,
            runtimeSessionId=session_id,
            payload=json.dumps({"prompt": prompt, "actor_id": actor_id}).encode(),
        )
        text = parse_sse_stream(resp["response"].iter_lines())
        return Response(text=text, latency_ms=(time.monotonic() - started) * 1000)


@dataclass
class FakeTransport:
    """Scripted transport for offline tests.

    Each element of `replies` is returned in order. An element that is an
    Exception instance is raised instead, to simulate infrastructure failure.
    """
    replies: list
    calls: list = field(default_factory=list)
    _index: int = 0

    def send(self, prompt: str, session_id: str, actor_id: str) -> Response:
        self.calls.append(
            {"prompt": prompt, "session_id": session_id, "actor_id": actor_id})
        if self._index >= len(self.replies):
            reply = ""
        else:
            reply = self.replies[self._index]
        self._index += 1
        if isinstance(reply, Exception):
            raise reply
        return Response(text=reply, latency_ms=1.0)
