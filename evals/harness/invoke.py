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


class AgentStreamError(RuntimeError):
    """The runtime returned HTTP 200, then reported an error mid-stream.

    bedrock_agentcore wraps the entrypoint generator and, because headers
    are already flushed, emits failures as a well-formed
    `data: {"error": ..., "error_type": ...}` line. Parsed naively that
    yields an empty string, and the harness would score an infrastructure
    failure as a content FAIL - destroying the ERROR/FAIL separation the
    scorecard depends on. Raising here lets the runner classify it as ERROR.
    """


@dataclass(frozen=True)
class Response:
    text: str
    latency_ms: float = 0.0


class Transport(Protocol):
    def send(self, prompt: str, session_id: str, actor_id: str) -> Response: ...


def new_session_id(run_id: str, case_id: str, turn_index: int = 0) -> str:
    """A fresh runtime session id. AgentCore requires at least 33 characters.

    Entropy is added unconditionally, not only when the base is short: a
    deterministic id means a retried case reuses its session, and AgentCore
    Memory then restores the failed attempt's history into the retry, so the
    retry sees contaminated context.

    The turn index and entropy sit BEFORE the case id so that truncation at
    96 characters eats the case id - cosmetic - rather than the parts that
    make the id unique.
    """
    base = f"eval-{run_id}-t{turn_index}-{uuid.uuid4().hex[:12]}-{case_id}"
    if len(base) < 33:
        base = base.ljust(33, "0")
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
        if "event" not in event and ("error" in event or "error_type" in event):
            raise AgentStreamError(
                f"{event.get('error_type', 'Error')}: {event.get('error', event)}")
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
        if not text.strip():
            # A 200 carrying no text is never a valid answer: it means a
            # non-streaming response shape, or a silently dropped stream.
            # ERROR is the honest classification, not an empty FAIL.
            raise AgentStreamError("runtime returned no answer text")
        return Response(text=text, latency_ms=(time.monotonic() - started) * 1000)


@dataclass
class FakeTransport:
    """Scripted transport for offline tests.

    Each element of `replies` is returned in order. An element that is an
    Exception instance is raised instead, to simulate infrastructure failure.
    """
    replies: list
    calls: list = field(default_factory=list)
    _index: int = field(default=0, repr=False)

    def send(self, prompt: str, session_id: str, actor_id: str) -> Response:
        self.calls.append(
            {"prompt": prompt, "session_id": session_id, "actor_id": actor_id})
        if self._index >= len(self.replies):
            # Strict on purpose. Returning "" here would manufacture the one
            # signal that is already ambiguous, so an off-by-one in retry or
            # multi-turn logic would surface as a plausible FAIL verdict and
            # send the author to debug the grader instead of the runner.
            raise AssertionError(
                f"FakeTransport exhausted after {len(self.replies)} replies; "
                f"call {self._index + 1} was unscripted")
        reply = self.replies[self._index]
        self._index += 1
        if isinstance(reply, Exception):
            raise reply
        return Response(text=reply, latency_ms=1.0)
