# Kit agent interface reference

## Invocation payload

Both invocation paths — direct `InvokeAgentRuntime` and the REST API —
accept the same JSON payload:

| Field | Type | Required | Notes |
|---|---|---|---|
| `prompt` | string | yes | The user's message |
| `actor_id` | string | no | Stable id for the human talking to the agent. Scopes long-term memory (facts, preferences). Defaults to `default-user` — set it in multi-user applications or everyone shares one memory. |
| `session_id` | string | REST only | ≥33 characters. Omit to start a new conversation; the response returns the id to continue it. (Direct runtime calls pass this as `runtimeSessionId` instead.) |

Advanced fields (`messages`, `tool_results`) exist for harness-style
integrations — see `_extract_prompt` in `app/kit/main.py`.

## Responses

**Runtime (streaming):** Server-sent events; each `data:` line is a JSON
event. Text arrives in `event.contentBlockDelta.delta.text` fragments.

**REST API (aggregated):**

```json
{ "result": "the agent's full reply", "session_id": "kit-api-…" }
```

Errors return `4xx` with `{ "error": "…" }`.

## Identity model

- **`session_id`** = one conversation. Short-term memory (the transcript)
  is keyed by session and restored on every invocation, surviving cold
  starts.
- **`actor_id`** = one human. Long-term memory namespaces
  (`/users/{actorId}/facts`, `/users/{actorId}/preferences`) are keyed by
  actor and shared across all their sessions.

## Environment variables (runtime)

| Variable | Set by | Purpose |
|---|---|---|
| `KIT_MODEL_ID` | you (optional) | Override the model inference profile (default `au.anthropic.claude-sonnet-5`) |
| `KIT_GUARDRAIL_ID` / `KIT_GUARDRAIL_VERSION` | CDK stack | Guardrail applied to model calls; empty id disables |
| `MEMORY_KITMEMORY_ID` | CDK stack | AgentCore Memory store |
| `KNOWLEDGE_BASE_ID` | CDK stack | Bedrock KB for the retrieve tool |
| `MIN_SCORE` | you (optional) | Retrieval relevance floor for the retrieve tool |
