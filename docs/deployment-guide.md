# Kit Deployment Guide

This guide takes you from an empty AWS account to a working conversation
with your own AI agent — including one answer retrieved from the built-in
knowledge base — in about 10 minutes, most of which is waiting for AWS to
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
- Working AWS credentials — with one caveat that trips almost everyone.
  It gets its own section, next.
- **A CDK-bootstrapped account and region.** One-time setup per
  account *and* per region, described in step 4 below. A fresh account,
  or an account you have never deployed CDK into in this region, will
  need it.

Check the lot in one go:

```bash
./scripts/preflight.sh
```

It verifies your tooling, your target file, and — the important one —
that your credentials are actually visible to the deploy, telling you
exactly what to fix if they aren't. Worth thirty seconds before a
twenty-minute deploy.

## 3. Credentials

Read this before your first deploy. It is the single most common way the
first attempt fails, and the error message points somewhere unhelpful.

**The AgentCore CLI has no `--profile` flag.** It resolves credentials
through the standard AWS SDK provider chain: environment variables first,
then whichever profile `AWS_PROFILE` names, and failing that the profile
literally called `default`.

So `aws sso login --profile my-profile` writes a token into a cache
belonging to *that named profile*, and nothing tells the default chain to
go and read it. You log in successfully, the CLI still sees nothing, and
the deploy fails on step one with `AWS credentials are invalid` — whose
suggested fix, `aws login`, is not a real command.

Point the chain at the profile you logged into:

```bash
aws sso login --profile my-profile
export AWS_PROFILE=my-profile

# confirm — note there is no --profile on this one
aws sts get-caller-identity
```

If that prints your account id, the deploy will work. `export` lasts for
the shell session and covers `agentcore deploy`, `invoke`, `status` and
`logs` alike.

To avoid the export entirely, make `default` your SSO profile in
`~/.aws/config`:

```ini
[sso-session my-org]
sso_start_url = https://my-org.awsapps.com/start
sso_region = us-east-1
sso_registration_scopes = sso:account:access

[default]
sso_session = my-org
sso_account_id = 123456789012
sso_role_name = AdministratorAccess
region = ap-southeast-2
```

**If it still fails after all that:** look for a leftover `[default]`
block in `~/.aws/credentials`. The credentials file always beats the
config file for the same profile name, so old static keys sitting there
will shadow the SSO profile you just configured, producing
`InvalidClientTokenId` no matter how many times you log in. Delete the
stale block, or use `AWS_PROFILE`, which sidesteps it.

## 4. Deploy

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

# 4. Check you're ready (thirty seconds, saves twenty minutes)
./scripts/preflight.sh

# 5. One-time per account AND region: CDK bootstrap
#    Skip if preflight says the region is already bootstrapped.
(cd agentcore/cdk && npx cdk bootstrap aws://<account-id>/<region>)

# 6. Ship it — from the repo root, not from agentcore/
agentcore deploy
```

### About step 5

CDK cannot deploy into an account and region until that pair has been
bootstrapped: a one-time `CDKToolkit` stack holding a staging bucket, an
ECR repository, IAM roles, and a KMS key. It is per *region*, so an
account that happily deploys Kit in `ap-southeast-2` still needs
bootstrapping before its first deploy in `us-west-2`.

**You must do this yourself.** `agentcore deploy` does not bootstrap for
you — verified both interactively and non-interactively (`-y`). In an
un-bootstrapped region the deploy runs for a couple of minutes and then
fails with `SSM parameter /cdk-bootstrap/hnb659fds/version not found`.
(The CLI does contain a bootstrap-confirmation code path, so this may be
version-dependent or may yet appear; as of CLI 0.28.1 it does not fire.)

Its own `✓ Check bootstrap status` step is no help either: it passes even
when the region is *not* bootstrapped, so the failure lands minutes later.
`./scripts/preflight.sh` checks the bootstrap parameter directly and tells
you before you start.

Bootstrapping is not free: the KMS key it creates costs roughly US$1/month
and outlives the Kit stack. See [Clean removal](#8-clean-removal).

`agentcore` commands expect the project root, the directory holding
`agentcore/`. From the wrong directory they refuse with `Please run this
command from your project root directory`.

`agentcore deploy --dry-run` validates credentials, builds and synthesises
the stack, and checks bootstrap status without creating anything.

The first deploy takes about **5 minutes**: it builds the agent container
with CodeBuild, creates the knowledge base, ingests the sample documents,
and wires everything together. Subsequent deploys are faster still
(~2 minutes).

Measured on a clean first deploy into a freshly-bootstrapped `us-west-2`:
4m50s. Add ~90 seconds if the region also needs bootstrapping.

## 5. First conversation

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

**Don't take the agent's word for it.** The extracted facts are stored
server-side and you can read them yourself, with no model in the loop:

```bash
aws bedrock-agentcore list-memory-records \
  --memory-id <memory-id-from-stack-outputs> \
  --namespace /users/default-user/facts \
  --query 'memoryRecordSummaries[].content.text' --output text
```

Swap `facts` for `preferences` to see the structured preference records.
Both namespaces are declared in `agentcore.json`.

Two properties worth verifying while you're there, because they are what
separate real memory from a model that sounds confident:

- **Isolation.** Call the API with a fresh `actor_id` and ask what it
  remembers. It should report nothing — each actor gets its own namespace.
- **No confabulation.** Ask the *known* actor about something you never
  told it. It should say it has no record, not invent one.

Extraction also infers, not just records: greeting the agent with "G'day"
produced a stored fact noting likely Australian English. That inference
happens at write time and lands in the store, so it is inspectable like
any other record.

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

## 6. Use the API

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

## 7. What it costs

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

## 8. Clean removal

```bash
aws cloudformation delete-stack --stack-name AgentCore-kit-default
```

The stack removes everything it created — including the S3 buckets **with
their contents**. That is not CloudFormation's default behaviour: a
non-empty bucket normally fails deletion with `BucketNotEmpty`. Kit sets
`autoDeleteObjects: true` on the corpus bucket, which provisions a custom
resource that empties it before CloudFormation removes it, and the same
applies to the ECR repository and its images.

Verified on a real teardown of the full 54-resource stack: runtime,
memory, guardrail, knowledge base, vector store, both S3 buckets, ECR
repo and images, and the API all removed.

Two things survive, for two different reasons.

### 1. CloudWatch log groups

These survive for **two** different reasons, which is worth knowing if you
are auditing an account:

- **Created outside the stack.** The AgentCore runtime's log group, the
  CodeBuild project's, and the S3-auto-delete Lambda's are created by the
  services themselves at runtime, so CloudFormation never has a handle on
  them.
- **In the stack, but retained deliberately.** The four Lambda log groups
  CDK creates explicitly carry `DeletionPolicy: Retain` (the CDK `LogGroup`
  L2 default) with 731-day retention, so they outlive the stack by design.

Either way they cost fractions of a cent, and are sometimes exactly what
you want after a teardown. To remove them, all three prefixes:

```bash
for prefix in \
  /aws/bedrock-agentcore/runtimes/kit \
  /aws/lambda/AgentCore-kit \
  /aws/codebuild/AgentCore-kit
do
  aws logs describe-log-groups --log-group-name-prefix "$prefix" \
    --query 'logGroups[].logGroupName' --output text | \
    tr '\t' '\n' | xargs -r -n1 aws logs delete-log-group --log-group-name
done
```

Adjust `AgentCore-kit` if you deployed under a different stack name.

**Not covered on purpose:** enabling the runtime's transaction search also
creates account-level `/aws/application-signals/data` and `aws/spans` log
groups. Those are shared by anything using Application Signals in the
region, so Kit's teardown deliberately leaves them alone — delete them only
if you know nothing else depends on them.

### 2. The CDK bootstrap stack

`CDKToolkit` is a **separate stack**, created once per account and region
before Kit ever deploys, and deliberately outliving it. It holds the
staging bucket your assets were uploaded to (tens of MB per deploy), an
ECR repository, five IAM roles, and a customer-managed KMS key.

That KMS key is the only survivor with a **real recurring cost** — around
US$1/month, charged whether or not you use it. Everything else here
rounds to nothing.

Only remove it if **nothing else in that account and region uses CDK** —
it is shared infrastructure, and deleting it will break other CDK
projects:

```bash
aws cloudformation delete-stack --stack-name CDKToolkit

# The staging bucket is DeletionPolicy: Retain, so it outlives even that
aws s3 rb s3://cdk-hnb659fds-assets-<account-id>-<region> --force
```

## 9. Troubleshooting

- **`AWS credentials are invalid` / `InvalidClientTokenId`, even after a
  fresh SSO login** — the CLI has no `--profile` flag, so an SSO login on
  a named profile is invisible to it. Run `./scripts/preflight.sh`, which
  diagnoses this precisely and names a profile that works. See
  [Credentials](#3-credentials).
- **`Please run this command from your project root directory`** — you're
  inside `agentcore/`. All `agentcore` commands run from the repo root.
- **`agentcore status` shows an agent as Deployed but with a security
  token error** — the resource list comes from local cached state while
  the live probe used bad credentials. Same fix as above.
- **`AccessDeniedException` mentioning a model** — Bedrock model access
  isn't enabled in your region. See Prerequisites.
- **Deploy succeeds but every invoke fails with `AccessDeniedException:
  Your account is currently being verified`** — an AWS account-verification
  gate on Bedrock in that region, not a Kit problem. CloudFormation does not
  check model entitlement, so the stack builds fine and only invocation
  fails. AWS says verification normally takes under two hours. Probe a
  region before committing to it:

  ```bash
  aws bedrock-runtime converse --region <region> \
    --model-id us.anthropic.claude-sonnet-5 \
    --messages '[{"role":"user","content":[{"text":"hi"}]}]' \
    --inference-config '{"maxTokens":1}'
  ```

  Encountered on a real account in `us-east-2` while `us-west-1` and
  `us-west-2` worked, so it is per-region.
- **`SSM parameter /cdk-bootstrap/... not found`** — your account/region
  hasn't been CDK-bootstrapped (a one-time setup): run
  `npx cdk bootstrap aws://<account-id>/<region>` from `agentcore/cdk/`,
  then `agentcore deploy` again.
- **Deploy fails in `CorpusIngestion`** — re-run `agentcore deploy`;
  ingestion is retryable.
- **Agent doesn't remember across sessions** — long-term extraction is
  asynchronous; give it a minute or two after the conversation.
- **A benign question got blocked** — content filters are classifier-based
  and probabilistic; a borderline response occasionally trips one. Retry
  first. If it recurs, the guardrail configuration lives in
  `agentcore/cdk/lib/cdk-stack.ts`; adjust filter strengths and redeploy
  (bump the guardrail version description to snapshot a new version).

## 10. Next steps

- [Swap in your own knowledge base](extending-knowledge-base.md)
- [Connect an MCP server](extending-mcp.md)
- [Observability with ADOT or Langfuse](extending-observability.md)

Built by [Honest Fox](https://honestfox.com.au). If Kit has you wondering
what an agent could do with your own data and workflows, that's the
conversation we're best at — book an AI Proof of Concept.
