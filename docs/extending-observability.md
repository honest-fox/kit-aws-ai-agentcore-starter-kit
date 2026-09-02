# Extension guide: observability

Kit is instrumented with OpenTelemetry out of the box — the container
runs under `opentelemetry-instrument` with the AWS Distro (ADOT), and
AgentCore ships traces, logs, and metrics to CloudWatch automatically.

## What you already have

- **Logs:** `agentcore logs --runtime kit --since 1h`, or CloudWatch Logs
  under `/aws/bedrock-agentcore/runtimes/…`
- **Traces:** `agentcore traces`, or CloudWatch → Transaction Search.
  Each agent invocation is a trace with model calls and tool executions
  as spans.
- **Metrics:** CloudWatch namespace `bedrock-agentcore` (latency,
  invocations, errors).

For most teams this is enough — start here before adding anything.

## Langfuse (LLM-native observability)

[Langfuse](https://langfuse.com) adds prompt-level analytics: token
costs per conversation, prompt/completion inspection, evals. Strands
exports OTel traces, so Langfuse connects via environment variables on
the runtime (`agentcore/agentcore.json` → `envVars`):

```json
{ "name": "OTEL_EXPORTER_OTLP_ENDPOINT", "value": "https://cloud.langfuse.com/api/public/otel" },
{ "name": "OTEL_EXPORTER_OTLP_HEADERS", "value": "Authorization=Basic <base64 public:secret>" }
```

Note this sends trace data (including prompt content) to Langfuse —
the same opt-in consideration as any third-party service. Self-hosted
Langfuse keeps it in your VPC.

## Custom dashboards

The runtime logs a structured line per invocation
(`Invoking agent: session=… actor=…`). CloudWatch Logs Insights over the
runtime log group gives you sessions per day, active actors, and error
rates without any extra infrastructure.
