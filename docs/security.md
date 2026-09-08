# Kit Security

Kit deploys an AI agent with a code interpreter, a web browser, durable
memory, and a public API endpoint into **your** AWS account. This document
states plainly what that agent can and cannot reach, what Kit does to
constrain it, and which risks are inherent to the design and therefore
yours to accept or mitigate.

Read the [prompt injection](#prompt-injection-the-one-that-matters) and
[actor identity](#actor-identity-is-caller-asserted) sections before you
put Kit in front of anyone but yourself.

## What the agent can reach

| Capability | Reach | Constrained by |
|---|---|---|
| Model | Claude on Bedrock, geography-scoped inference profile | `bedrock:InvokeModel` on that profile; guardrail applied on every call |
| Code interpreter | An **AWS-managed sandbox**, not your container or VPC | IAM scoped to `arn:aws:bedrock-agentcore:<region>:aws:code-interpreter/*` |
| Browser | An **AWS-managed browser sandbox** with general internet egress | IAM scoped to `arn:aws:bedrock-agentcore:<region>:aws:browser/*` |
| Memory | One AgentCore Memory resource, namespaced per actor | IAM scoped to that memory's ARN |
| Knowledge base | One Bedrock KB over Kit's S3 corpus bucket | `bedrock:Retrieve` on that KB ARN only |
| Guardrail | Kit's own guardrail | `bedrock:ApplyGuardrail` on that ARN only |

## What the agent cannot reach

- **Your other AWS resources.** The runtime role grants only the actions in
  the table above. It has no S3, DynamoDB, EC2, IAM, or Secrets Manager
  access beyond Kit's own corpus bucket.
- **Your network.** The default deployment uses `networkMode: PUBLIC` and
  is not attached to your VPC, so it cannot reach private subnets,
  databases, or internal services.
- **Your container.** Code execution and browsing happen in AWS-managed
  sandboxes outside the agent container.
- **Third parties.** Kit makes no third-party calls. No MCP servers are
  configured by default, and no telemetry leaves your account.

## Prompt injection: the one that matters

Kit combines three things that are individually fine and jointly risky:

1. **Untrusted content ingress** — the browser can fetch any page
2. **Private data** — the knowledge base, and memory that persists what
   users tell it
3. **Code execution** — the code interpreter

A web page can contain text that reads to the model as instructions.
Pointing Kit at attacker-controlled content and asking it to summarise
means the model has read instructions written by someone who is not you.

**Guardrails do not solve this.** Kit's `PROMPT_ATTACK` filter is set to
`LOW` deliberately: at higher strengths it blocked ordinary first-contact
phrasing. It screens *user input*, not the content the browser returns.

**What this means in practice:**

- Treat any agent output derived from browsing as untrusted input to
  whatever consumes it next.
- Do not put data in Kit's knowledge base that you would not want
  exfiltrated if the agent were successfully instructed to summarise it
  into a browser request.
- If your use case involves both sensitive data and untrusted web content,
  remove the browser tool (`app/kit/main.py`) rather than relying on
  guardrails.
- Kit's tools cannot reach your other AWS resources, so the blast radius
  is Kit's own data plus anything the agent can be induced to say — not
  your wider account.

This is a property of useful agents, not a Kit defect. We document it
because a product that ships a browser and a code interpreter into your
account and stays quiet about it has not earned your trust.

## Actor identity is caller-asserted

`actor_id` selects the caller's long-term memory namespace
(`/users/{actorId}/facts`). It is an identity **label**, not an
authenticated identity: whoever can invoke the runtime chooses it.

**Assign `actor_id` server-side from your own authenticated session.**
Never forward it from an untrusted client. If end users can set it, any
user can read another user's remembered facts by changing the value.

Kit validates the format — 1–128 characters of `[A-Za-z0-9-_.:@]`, with
`.` and `..` rejected — so it cannot contain namespace separators or
traversal sequences. That is defence in depth against malformed input, not
authentication. Authenticating the caller is the integrator's job.

## API posture

- **Every route requires an API key.** There are no unauthenticated
  endpoints. A request without `x-api-key` gets HTTP 403.
- **Rate throttle:** 5 req/s, burst 10.
- **Daily quota:** 2,000 requests. The throttle alone would permit roughly
  432,000 requests/day, which does not meaningfully bound model spend; the
  quota does. Both are sized for evaluation — raise them deliberately.
- **Prompt length capped** at 20,000 characters (`KIT_MAX_PROMPT_CHARS`),
  returning HTTP 413. API Gateway alone would accept a 10 MB body.
- **Errors** are logged server-side; callers get status codes, not
  internals.

Rotate or delete the default API key before exposing the endpoint to
anything real:

```bash
aws apigateway delete-api-key --api-key <key-id>
```

## IAM posture

Least privilege, with one honest exception.

Every policy Kit writes targets a specific resource ARN. The only
`Resource: "*"` entries in the synthesized template are AWS APIs that do
not support resource-level permissions:

- `ecr:GetAuthorizationToken`
- `logs:DescribeLogGroups`
- `xray:PutTraceSegments`, `xray:PutTelemetryRecords`

**The exception:** the `@aws/agentcore-cdk` L3 construct grants the runtime
role `bedrock-agentcore:*ConfigurationBundle*` on
`arn:aws:bedrock-agentcore:*:*:configuration-bundle/*` — wildcards on both
region and account — even though Kit declares no configuration bundles.
This comes from the upstream construct, not Kit's code. Cross-account use
would still require the other account's resource policy to allow it, so
practical exposure is low, but it is broader than Kit needs. Attach a
permissions boundary if your organisation requires strict least privilege.

## Data handling

- **Where it lives.** Conversations, extracted facts, and preferences live
  in AgentCore Memory in your account and region. The corpus lives in your
  S3 bucket. Nothing is sent outside your account.
- **Model geography.** Kit defaults to a geography-scoped inference profile
  (`au.` in Australian regions, `us.`/`eu.` in those geographies), so
  inference stays in-geography. Override with `KIT_MODEL_ID`.
- **Retention.** Memory events expire after 30 days
  (`eventExpiryDuration` in `agentcore.json`). Extracted long-term facts
  persist until the memory resource is deleted.
- **Inspect what is stored:**

  ```bash
  aws bedrock-agentcore list-memory-records \
    --memory-id <memory-id> --namespace /users/<actor-id>/facts
  ```

- **No PII filtering by default.** Kit's guardrail configures content
  filters and prompt-attack detection but **not**
  `sensitiveInformationPolicyConfig`. Anything a user types — including
  personal information — may be stored durably and extracted into
  long-term facts. This is deliberate: PII anonymisation changes agent
  behaviour in ways that depend on your use case, so Kit ships the
  permissive default and leaves the decision to you. If you handle personal
  data, add a sensitive-information policy in
  `agentcore/cdk/lib/cdk-stack.ts` and bump the guardrail version
  description to snapshot a new version.

## Guardrail defaults

| Filter | Input | Output |
|---|---|---|
| Sexual, Violence, Hate | HIGH | HIGH |
| Insults, Misconduct | MEDIUM | MEDIUM |
| Prompt attack | LOW | NONE (required by the Bedrock API) |

`PROMPT_ATTACK` is `LOW` because MEDIUM blocked benign first-contact
phrasing. LOW still blocks high-confidence instruction-override attempts —
verified on a fresh deployment. Filters are classifier-based and
probabilistic; tune them in `agentcore/cdk/lib/cdk-stack.ts`.

To disable the guardrail without a stack change, set `KIT_GUARDRAIL_ID` to
an empty string on the runtime.

## Secrets

- `agentcore/.env.local` and `agentcore/aws-targets.json` are gitignored;
  neither is committed.
- Kit needs no API keys of its own. It authenticates to AWS with the
  runtime's IAM role — there are no long-lived credentials in the image.
- The API key value is never in the stack outputs, only its id; fetch the
  value with `aws apigateway get-api-key --include-value`.

## Reporting a vulnerability

Open a GitHub issue for non-sensitive findings. For anything you would
rather not disclose publicly, contact Honest Fox directly rather than
filing an issue.

## Before you go to production

Kit is a starter kit. Its defaults are sized for evaluation:

- [ ] Rotate or delete the default API key
- [ ] Raise the throttle and quota to match real traffic
- [ ] Decide on a PII policy if you handle personal data
- [ ] Remove the browser tool if you combine sensitive data with untrusted
      web content
- [ ] Assign `actor_id` from an authenticated server-side session
- [ ] Review the guardrail filters against your own content standards
- [ ] Consider a permissions boundary on the runtime role
