# Changelog

All notable changes to Kit are documented here. Kit follows
[Semantic Versioning](https://semver.org/): while the version is `0.x`,
the deployed resource shape may change between minor versions.

## [0.2.0] — 2026-10-12

An evaluation harness. Kit 0.1 let you deploy an agent and see it work;
0.2 answers the next question — whether it is any good, and whether you
would notice if it stopped being.

### The stack

- **Golden set** — 22 cases across four suites (retrieval, memory, tools,
  adversarial), 25 conversational turns, every expected answer grounded in
  the `sample-data/` corpus so a pass proves retrieval actually ran.
  Datasets are YAML in `evals/datasets/`, meant to be rewritten for your
  own corpus.
- **Deterministic grading, and nothing else locally.** `contains_all`,
  `contains_any`, `not_contains`, `regex`, `numeric`, `refused` — free,
  instant and reproducible, and the only thing CI gates on. A case that
  asserts nothing is rejected offline, because `all([])` is `True` and such
  a case could never fail. The harness runs no LLM judge of its own:
  judged quality is scored by the managed evaluators below, which is what a
  managed evaluation service is for. `docs/evaluation.md` sets out the
  reasoning, and when hand-building a harness is and is not worth it.
- **Adversarial suite** — five cases, reported and never gated. Direct
  attacks (instruction override, system-prompt exfiltration, roleplay
  jailbreak) run against any deployment. Indirect, retrieved-document
  injection needs `evals/corpus/adversarial/` loaded into a throwaway
  knowledge base and declared with `--adversarial-corpus`; without it
  those cases are SKIPPED rather than counted as caught, and the catch-rate
  denominator counts only attacks actually launched.
- **A gate that refuses runs with no signal.** Pass rate is computed over
  passed + failed only, so ERROR cannot move it — and the gate separately
  fails when more than 10% of cases errored, rather than reading 16 ERROR
  and 1 PASS as 100%. Filtered `--suite` / `--case` runs write
  `scorecard-partial.md` and exit 0 with `NOT GATED` unless `--threshold`
  is passed deliberately.
- **Continuous evaluation** — three declarative LLM-as-a-judge evaluators
  (`KitGroundedness`, `KitToolSelection`, `KitRefusalQuality`), operated by
  AWS and wired to `KitQualityMonitor` at 5% sampling. Each pins
  `au.anthropic.claude-sonnet-4-5-20250929-v1:0`, a profile that resolves
  to `ap-southeast-2` and `ap-southeast-4` and nothing else, so judged
  scoring stays in-geography; deliberately a different model generation
  from the agent's default, so nothing scores its own output. Ships with
  `enableOnCreate: false`, so deploying Kit never starts evaluation spend;
  `agentcore resume online-eval KitQualityMonitor` starts it and
  `agentcore pause` stops it, with no redeploy.
- **Their instruction text is pinned offline.**
  `evals/tests/test_agentcore_config.py` asserts the untrusted-data clause,
  the placeholders each evaluator level permits, the non-`global.` model,
  and that no online eval enables itself on create — `agentcore validate`
  checks names and references, but not instruction strings.

### Continuous integration

- **Tier 1, `evals (offline)`** — every pull request including forks, plus
  pushes to `main`. No AWS credentials and no AWS calls: 113 harness unit
  tests, dataset validation, `agentcore validate`. The AgentCore CLI is
  pinned so a CLI release cannot turn every fork's pull request red.
- **Tier 2, `evals (live)`** — merge to `main` and manual dispatch, and
  **ephemeral**: deploy, wait for knowledge-base ingestion, run the suite,
  tear down. Deliberately **no `schedule:` trigger** — a cron would mean a
  permanently deployed eval stack, which is the always-on bill Kit says it
  does not have.
- **Teardown is asserted, not documented.** `aws cloudformation
  delete-stack` under `if: always()` with a second attempt, because
  `DELETE_FAILED` / `NotStabilized` on the AgentCore runtime — the 0.1
  limitation below — leaves a stack that looks deleted and is still
  billing. `cancel-in-progress: false`, because cancelling mid-run skips
  teardown and orphans the stack.
- `scripts/wait-for-ingestion.sh` blocks until every data source reports
  `COMPLETE` and times out loudly. Retrieval cases scored mid-ingestion are
  indistinguishable from a quality regression.

### Enablement

- `./scripts/eval.sh` — one entry point, with `--validate`, `--dry-run`,
  `--suite`, `--case`, `--threshold` and `--adversarial-corpus`
- `docs/evaluation.md` — the full guide: what the harness grades and what
  it deliberately leaves to the managed evaluators, reading the scorecard,
  where judged scoring runs and how to verify the geography yourself, the
  adversarial opt-in, cost, and what the numbers do not tell you
- `scripts/preflight.sh` now checks CloudWatch Transaction Search, as a
  **warning**: managed evaluators and `agentcore run eval` need trace
  ingestion, while the deterministic gate does not

### Verified

- 113 harness unit tests pass; the `--validate` path imports no AWS module
  at all, confirmed by inspecting `sys.modules` after a run.
- The `au.` inference profile the evaluators pin resolves to exactly two
  model ARNs, both Australian (`aws bedrock get-inference-profile`,
  ap-southeast-2, 23 Sep 2026).
- `agentcore validate` passes; `./scripts/eval.sh --validate` reports
  22 cases valid.
- There is no `agentcore destroy` subcommand in CLI 0.28.1 — teardown goes
  through CloudFormation directly.

### Known limitations

- **`REFUSAL_MARKERS` is a phrase list, not a classifier.** A model that
  declines in wording outside the list ("I'm not going to write that
  scene") scores as "not refused" while behaving correctly. Read a FAIL on
  a refusal case as "go and look at the response", and read the adversarial
  catch rate as a floor rather than a ceiling. The system-prompt
  exfiltration case likewise detects verbatim disclosure only — a close
  paraphrase is not caught.
- **Indirect adversarial cases need manual corpus loading.**
  `evals/corpus/adversarial/` is deliberately not ingested by
  `agentcore deploy`; loading it is a manual step into a throwaway
  knowledge base. Until then those cases are SKIPPED and the suite measures
  direct attacks only.
- **A default run reports no judged quality at all.** The harness grades
  deterministically and nothing else; judged quality comes from the managed
  evaluators in `agentcore.json`, and those ship **disabled**
  (`enableOnCreate: false`) and score sampled live traffic once enabled,
  not this run. So `./scripts/eval.sh` tells you whether the agent said the
  right things, never whether it said them well. And an LLM-judged score is
  a trend across many traces, never a threshold on one — which is why
  nothing gates on it.
- **The live CI tier needs two repository secrets** —
  `KIT_EVAL_ROLE_ARN` and `KIT_EVAL_ACCOUNT_ID` — that forks will not have.
  It skips quietly on a fork rather than going permanently red, so a fork
  gets the offline tier only.
- **Nothing in CI protects a stack from a job that never finishes.** The
  teardown step, its retry and the absence of a cron all assume the job
  reaches its last step; a dead runner or a cancelled workflow orphans a
  deployed, billing stack. Put an AWS Budget alarm on any account running
  the live tier — it is the only mechanism here that works when Actions
  isn't.
- **22 cases is a smoke test, not a benchmark.** It catches "retrieval
  broke" and "memory stopped persisting". It does not characterise quality,
  and a passing gate is not a production sign-off.

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

[0.2.0]: https://github.com/honest-fox/kit-aws-ai-agentcore-starter-kit/releases/tag/v0.2.0
[0.1.0]: https://github.com/honest-fox/kit-aws-ai-agentcore-starter-kit/releases/tag/v0.1.0
