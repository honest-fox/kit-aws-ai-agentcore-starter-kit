# Kit Deployment Guide

This guide takes you from an empty AWS account to a working conversation
with your own AI agent — including one answer retrieved from the built-in
knowledge base — in around 20 minutes, most of which is waiting for AWS to
build things.

No AI experience required. If you can run terminal commands, you can
deploy Kit.

## 1. What you're deploying

One CloudFormation stack containing:

| Piece | AWS service | What it does |
|---|---|---|
| Agent runtime | Bedrock AgentCore | Runs the agent in an isolated container |
| Model | Claude Sonnet on Bedrock | The intelligence (AU-resident inference by default) |
| Memory | AgentCore Memory | Conversations survive restarts; facts persist across sessions |
| Knowledge base | Bedrock KB + S3 Vectors | Working RAG, pre-loaded with sample documents |
| Tools | AgentCore Code Interpreter + Browser | Sandboxed code execution and web access |
| Guardrails | Bedrock Guardrails | Content filtering and prompt-attack protection, on by default |
| API | API Gateway + Lambda | Programmatic access, API-key authenticated |

Everything deploys into **your** account. Nothing phones home; no
third-party services are contacted unless you opt in.

## 2. Prerequisites

- An AWS account with administrator (or equivalently broad) credentials
- **Bedrock model access** enabled for Anthropic Claude models in your
  deployment region (AWS Console → Bedrock → Model access → enable
  Anthropic Claude). This is a one-time account setting.
- [Node.js](https://nodejs.org) 20 or later
- [Python](https://python.org) 3.10+ and [uv](https://docs.astral.sh/uv/)
- [Docker](https://docker.com) running locally
- AWS credentials configured (`aws configure`, SSO, or environment
  variables)

## 3. Deploy

```bash
# 1. Install the AgentCore CLI
npm install -g @aws/agentcore

# 2. Get Kit
git clone https://github.com/honestfox/kit
cd kit

# 3. Point it at your account
cp agentcore/aws-targets.example.json agentcore/aws-targets.json
# edit aws-targets.json: your 12-digit account id, and your region
# (ap-southeast-2 is tested first-class; us-east-1 also verified)

# 4. Ship it
agentcore deploy
```

The first deploy takes 10–20 minutes: it builds the agent container with
CodeBuild, creates the knowledge base, ingests the sample documents, and
wires everything together. Subsequent deploys are much faster (~2 minutes).

## 4. First conversation

```bash
agentcore invoke "G'day! Introduce yourself and list what you can do."
```

### Prove the memory works

```bash
agentcore invoke "Remember this: my favourite colour is green and I work at Acme."
# note the session id it prints, then in a NEW session:
agentcore invoke "What do you remember about me?"
```

The second answer comes from long-term memory, not the conversation —
give the extraction a minute or two after the first message.

### Prove the RAG works

The knowledge base ships with documents about **Kookaburra Coffee Co.**,
a fictional Sydney roaster. These answers exist nowhere on the internet:

```bash
agentcore invoke "How much is a 250g bag of Marrickville Morning?"
# → $19.50 AUD, straight from the corpus
agentcore invoke "What's the return window on unused equipment?"
# → 45 days, ditto
```

### Prove the tools work

```bash
agentcore invoke "Use your code interpreter to compute the SHA-256 of 'hello kit'"
agentcore invoke "Use your browser to check the main heading on https://example.com"
```

## 5. Use the API

Your stack outputs include the endpoint URL and API key id
(`aws cloudformation describe-stacks --stack-name AgentCore-kit-default`):

```bash
KEY=$(aws apigateway get-api-key --api-key <key-id> --include-value \
      --query value --output text)

curl -X POST <api-url> \
  -H "x-api-key: $KEY" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Hello from the API"}'
```

The response includes a `session_id` — send it back in your next request
to continue the conversation. Pass `actor_id` to give each of your users
their own long-term memory space.

Requests are throttled (5 req/s, burst 10) and every route requires the
key. There are no unauthenticated endpoints.

## 6. What it costs

Kit itself is free. Rough guide to the AWS charges (AUD, ap-southeast-2,
prices move — check your bill):

| Service | Driver | Ballpark |
|---|---|---|
| Claude Sonnet tokens | your conversations | dominant cost; single-digit dollars for a day of heavy tinkering |
| AgentCore runtime + memory + tools | per-use consumption | cents to low dollars |
| S3 Vectors, S3, Lambda, API Gateway | tiny at trial volume | cents |
| CodeBuild | container builds on deploy | cents per deploy |

There are **no always-on charges** in the default deployment — no
provisioned OpenSearch, no idle EC2. If nobody talks to the agent, the
bill rounds to zero.

## 7. Clean removal

```bash
aws cloudformation delete-stack --stack-name AgentCore-kit-default
```

The stack removes everything it created, including the S3 buckets and
their contents, the container images, and the vector store — verified:
no billable resources remain.

One honest footnote: CloudWatch **log groups** survive deletion (AWS
creates them outside the stack). They hold your agent's logs, cost
fractions of a cent, and are sometimes exactly what you want after a
teardown. To remove them too:

```bash
aws logs describe-log-groups \
  --log-group-name-prefix /aws/bedrock-agentcore/runtimes/kit \
  --query 'logGroups[].logGroupName' --output text | \
  xargs -n1 aws logs delete-log-group --log-group-name
aws logs describe-log-groups \
  --log-group-name-prefix /aws/lambda/AgentCore-kit \
  --query 'logGroups[].logGroupName' --output text | \
  xargs -n1 aws logs delete-log-group --log-group-name
```

## 8. Troubleshooting

- **`AccessDeniedException` mentioning a model** — Bedrock model access
  isn't enabled in your region. See Prerequisites.
- **Deploy fails in `CorpusIngestion`** — re-run `agentcore deploy`;
  ingestion is retryable.
- **Agent doesn't remember across sessions** — long-term extraction is
  asynchronous; give it a minute or two after the conversation.
- **A benign question got blocked** — the guardrail configuration lives in
  `agentcore/cdk/lib/cdk-stack.ts`; adjust filter strengths and redeploy
  (bump the guardrail version description to snapshot a new version).

## 9. Next steps

- [Swap in your own knowledge base](extending-knowledge-base.md)
- [Connect an MCP server](extending-mcp.md)
- [Observability with ADOT or Langfuse](extending-observability.md)

Built by [Honest Fox](https://honestfox.com.au). If Kit has you wondering
what an agent could do with your own data and workflows, that's the
conversation we're best at — book an AI Proof of Concept.
