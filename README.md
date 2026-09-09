# Kit — AI Agent Starter Kit by Honest Fox

**Deploy a genuinely working AI agent into your own AWS account in about 10 minutes.**
Not a chat demo: a production-shaped agent on Amazon Bedrock AgentCore with
durable memory, working RAG, guardrails, managed tools, and an authenticated
API — free, open source, and built Sydney-first.

Kit (a kit is a baby fox 🦊) is how [Honest Fox](https://honestfox.com.au)
shows rather than tells. Deploy it, poke it, read the code, keep it forever.

## What you get

One CloudFormation stack, deployed with one command:

- **Agent runtime** on Amazon Bedrock AgentCore, built with the
  [Strands](https://strandsagents.com) framework
- **Claude Sonnet on Bedrock** via the `au.` inference profile —
  **inference stays in Australia** by default (swap models or regions with
  one environment variable, no rebuild)
- **Durable memory** — conversations survive restarts, and the agent
  remembers facts and preferences across sessions (AgentCore Memory,
  semantic + preference + summary strategies). Per-actor isolated, and
  the extracted records are readable server-side with
  `aws bedrock-agentcore list-memory-records` — verify it rather than
  trusting the agent's summary
- **Working RAG out of the box** — a Bedrock Knowledge Base backed by S3
  Vectors, pre-loaded with a sample corpus so retrieval works on your very
  first question. Swap in your own documents by replacing one folder.
- **Managed tools** — code interpreter and web browser running in isolated
  AWS sandboxes, not in your agent's container
- **Guardrails on by default** — content filters and prompt-attack
  detection, tuned so benign questions pass
- **Authenticated API** — API Gateway + Lambda with API-key auth and
  throttling; no open endpoints, ever
- **No third-party calls** — nothing leaves AWS unless you opt in

## Quick start

Prerequisites: an AWS account, Node.js 20+, Python 3.10+ with
[uv](https://docs.astral.sh/uv/), Docker, and AWS credentials.

```bash
npm install -g @aws/agentcore
git clone https://github.com/honest-fox/kit-aws-ai-agentcore-starter-kit kit && cd kit
cp agentcore/aws-targets.example.json agentcore/aws-targets.json
# edit aws-targets.json: your account id and region

./scripts/preflight.sh   # thirty seconds, saves twenty minutes
agentcore deploy
```

> **On credentials.** The AgentCore CLI has no `--profile` flag — it reads
> the standard AWS SDK chain. If you use SSO, `aws sso login --profile foo`
> alone won't reach it; `export AWS_PROFILE=foo` as well. `preflight.sh`
> checks this and tells you exactly what to fix. Full detail in the
> [deployment guide](docs/deployment-guide.md#3-credentials).

Then talk to your agent:

```bash
agentcore invoke "G'day! What can you do?"
```

### Prove the RAG works

The knowledge base ships with documents about a fictional Sydney coffee
roaster. These answers exist nowhere else:

```bash
agentcore invoke "How much is a 250g bag of Marrickville Morning?"
agentcore invoke "What's Kookaburra Coffee's return policy on equipment?"
```

### Call the API

The stack outputs your endpoint URL and API key id:

```bash
KEY=$(aws apigateway get-api-key --api-key <key-id> --include-value --query value --output text)
curl -X POST <api-url> \
  -H "x-api-key: $KEY" -H "Content-Type: application/json" \
  -d '{"prompt": "Remember that my name is Dana.", "actor_id": "dana"}'
```

Send the returned `session_id` back on your next call for conversation
continuity.

## What it costs

Kit is free. The AWS services it uses are not, though the defaults are
deliberately modest: AgentCore consumption pricing, Claude Sonnet tokens,
S3 Vectors (cents), Lambda and API Gateway (near-zero at trial volume).
A day of enthusiastic tinkering typically costs a few dollars, dominated
by model tokens. The deployment guide has an honest cost table.
Delete the stack and everything it created goes with it — no orphaned
resources, no surprise bills.

## Extend it

- **Your own knowledge base:** replace `sample-data/` and redeploy
- **Different model:** set `KIT_MODEL_ID` (any Bedrock inference profile)
- **MCP servers:** sample client included (`app/kit/mcp_client/`) — off by
  default because your traffic is yours
- **Observability:** OpenTelemetry instrumentation is already wired;
  extension guides cover ADOT and Langfuse

## Security posture

API-key auth on every route (plus a rate throttle and daily quota),
least-privilege IAM, guardrails on by default, no unauthenticated
endpoints, no third-party calls. The agent's sandboxed tools (code
interpreter, browser) run in AWS-managed isolation outside your container,
and cannot reach your other AWS resources or your VPC.

Kit ships a browser and a code interpreter into your account, so
**[docs/security.md](docs/security.md)** states plainly what the agent can
and cannot reach — including the prompt-injection exposure that comes with
combining web access, private data, and code execution, and the fact that
`actor_id` is caller-asserted rather than authenticated. Worth reading
before you put Kit in front of anyone but yourself.

## Who made this

[Honest Fox](https://honestfox.com.au) is a Melbourne-based digital agency
building serverless and AI systems on AWS. Kit is the free, self-serve
version of how we start every AI engagement: prove it works in *your*
account first.

If Kit gets you thinking about what an agent could do with your data and
your workflows — that conversation is what we do.
**[Book an AI Proof of Concept →](https://honestfox.com.au)**

## License

Apache-2.0. Use it, fork it, ship it.
