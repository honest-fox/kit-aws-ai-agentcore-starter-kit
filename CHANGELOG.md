# Changelog

All notable changes to Kit are documented here. Kit follows
[Semantic Versioning](https://semver.org/): while the version is `0.x`,
the deployed resource shape may change between minor versions.

## [0.1.0] — 2026-09-08

First release. A complete, working agent deployable into a fresh AWS
account, with the enablement layer to evaluate it and the security posture
documented.

### The stack

- **Agent runtime** on Amazon Bedrock AgentCore, built with
  [Strands](https://strandsagents.com)
- **Geography-aware model default** — Claude Sonnet via a geography-scoped
  inference profile (`au.` in Australian regions, `us.`/`eu.` in those
  geographies), so inference stays in-geography. Override with
  `KIT_MODEL_ID`, no rebuild.
- **Durable memory** — AgentCore Memory with semantic, user-preference and
  summarisation strategies. Conversations survive restarts; facts and
  preferences persist across sessions, namespaced per actor.
- **Working RAG on first deploy** — a Bedrock Knowledge Base backed by S3
  Vectors (no OpenSearch Serverless minimum spend), pre-loaded with a
  sample corpus so retrieval answers a real question immediately.
- **Managed tools** — code interpreter and browser, running in AWS-managed
  sandboxes rather than the agent container.
- **Guardrails on by default** — content filters plus prompt-attack
  detection, tuned so ordinary first-contact phrasing is not blocked.
- **Authenticated API** — API Gateway + Lambda, API-key auth on every
  route, rate throttle and daily quota. No unauthenticated endpoints.
- **No third-party calls.** No MCP servers configured by default; nothing
  leaves your account unless you opt in.

### Enablement

- Deployment guide, from empty account to a working conversation
- `scripts/preflight.sh` — verifies tooling, credentials, deployment
  target and CDK bootstrap before a deploy can fail minutes in
- Console testing walkthrough for non-technical evaluators
- Technical evaluation notebook
- Agent payload/response schema documentation
- Extension guides: custom knowledge base, MCP server, observability
- `docs/security.md` — what the agent can and cannot reach, the
  prompt-injection model, and a pre-production hardening checklist

### Verified

- Clean first deploy into a fresh, freshly-bootstrapped region: **4m50s**
  (us-west-2). Verified in ap-southeast-2 and us-west-2.
- Memory, RAG, code interpreter, browser, guardrails and the authenticated
  API all exercised on a live deployment; memory recall confirmed
  store-backed and actor-isolated rather than model-inferred.
- Full teardown removes every billable resource. Surviving CloudWatch log
  groups and the shared CDK bootstrap stack are documented, with removal
  commands, and both were re-verified in two regions.

### Known limitations

- CDK bootstrap is a manual prerequisite: `agentcore deploy` does not do it
  for you in either interactive or non-interactive mode (CLI 0.28.1).
- Bedrock model access can be gated per region by AWS account
  verification. The deploy succeeds and invocation fails; probe a region
  first (see the deployment guide's troubleshooting section).
- Teardown can stop with `DELETE_FAILED` on the AgentCore runtime
  (`NotStabilized`), leaving other resources in place. Re-running the
  delete clears it.
- No PII filtering by default — a deliberate, documented default. See
  `docs/security.md`.
- API defaults (2,000 requests/day, 20,000-character prompts) are sized
  for evaluation, not production.

[0.1.0]: https://github.com/honest-fox/kit-aws-ai-agentcore-starter-kit/releases/tag/v0.1.0
