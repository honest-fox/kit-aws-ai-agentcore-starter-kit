# Kit Evaluation

You have deployed Kit. It answers questions. The question this document
answers is the next one: **is it any good, and how would you know if it
stopped being good?**

Kit ships a golden set of 22 cases and a harness that runs them against
*your* deployment, in your account, in your region. Nothing is pre-recorded
and no score is taken on trust — every number in the scorecard comes from
invoking the agent you just deployed.

```bash
./scripts/eval.sh              # full suite against your deployed stack
./scripts/eval.sh --validate   # offline dataset check, no AWS needed
./scripts/eval.sh --dry-run    # list the cases that would run
```

Exit codes: `0` the gate passed, `1` the gate failed, `2` a configuration
or dataset error.

## One grading tier here, and one somewhere else

Every case in the golden set is graded by **deterministic assertions** —
`contains_all`, `contains_any`, `not_contains`, `regex`, `numeric`,
`refused`. They are free, instant, and reproducible: the same response in
gives the same verdict out, every time. They are the only thing this
harness scores, and the only thing CI gates on.

Judged quality — groundedness, tool selection, refusal proportionality — is
scored somewhere else entirely: by three custom evaluators declared in
`agentcore/agentcore.json` and operated by AWS against real traffic. This
harness runs no judge of its own. It used to, and
[what we removed, and why](#what-we-removed-and-why) is the most useful
section of this document.

The reason the gate is deterministic-only is not philosophical. An
LLM-judged gate moves when nothing in the agent has moved — the scoring
model updates, it scores 3.8 instead of 4.1, and the build goes red on a
commit that changed a comment. A gate that fails for reasons the author
cannot act on is a gate the team learns to re-run until it goes green,
which is worse than having no gate at all.

The harness enforces this structurally rather than by convention. A case
that asserts nothing is rejected offline by `validate()`:

```
retrieval-example: no assertions on any turn
```

`all([])` is `True`, so such a case would be marked PASS unconditionally,
whatever the agent said, and would quietly inflate the pass rate that gates
CI.

## What we removed, and why

Kit 0.2 was built with a second grading tier: an LLM-as-a-judge implemented
in Python, in this repository, scoring each answer 1–5 for groundedness or
helpfulness. It has been deleted. The reasoning is worth more than the code
was.

**It duplicated a managed service.** AgentCore ships built-in evaluators —
`Faithfulness`, `Correctness`, `Refusal`, `ToolSelectionAccuracy`,
`GoalSuccessRate` and others, across session, trace and tool-call levels —
and supports declarative custom LLM-as-a-judge evaluators on top of them.
Kit already declares three of those custom evaluators in
`agentcore/agentcore.json`. AWS operates them, they are pinned to the `au.`
geography profile, and `KitQualityMonitor` scores real traffic with them.
A second judge, written in Python and scoring the same dimensions, was a
reimplementation of something the project had already declared.

**Hardening it was work that only existed because it was hand-built.**
Prompt-injection defence in the judge's own prompt; provider lock-in
(`invoke_model` versus `converse`, because the model id was an
unconstrained environment variable); tolerating markdown fences around the
model's JSON; reporting judge coverage so that a silently failing judge did
not read as a tidy column of dashes. None of that is agent-quality work. It
is evaluation-service plumbing, and in the managed design it is AWS's
problem rather than this repository's.

**It was never validated.** The one measurement that would have justified
keeping it — how far its scores agreed with human judgement on Kit's own
corpus — was never taken. A hand-built, hand-hardened judge of unmeasured
accuracy is not a better instrument than a managed one. It is a comparable
instrument with considerably more of this repository attached to it.

**It never gated anything anyway.** Judge scores were reported as a trend
and never allowed to fail a build. That was the right call, for the reason
in the previous section — but it also means removing them cost the gate
nothing. Not one number that CI enforces has changed.

### What justified building a harness at all

The deterministic tier, and only the deterministic tier.

Exact-value assertions are a different kind of instrument from a judge. Is
the answer *actually* `$19.50`? `45` days? `5–8` business days? That
question has a byte-reproducible answer, costs nothing to ask, returns
instantly, and needs no CloudWatch Transaction Search and no trace
ingestion — only the ability to invoke the agent. Run it twice against the
same response and it returns the same verdict twice.

The built-in evaluators cannot do that, by construction. They score 0–1 by
LLM judgement — including `Correctness`, even when it is given ground
truth. So a gate built on built-ins alone is an **LLM-judged gate**: it
drifts with the scoring model, and a build can go red on a commit that
changed nothing. That is precisely the failure mode this document argues
against, and it is the whole reason the harness exists.

The division of labour is not "local good, managed bad":

| | This harness | The managed evaluators |
|---|---|---|
| Asks | did it say the right thing? | was the answer any good? |
| Answers | an exact, reproducible verdict | a score, which drifts |
| Costs | nothing beyond the agent invocation | per-scored-trace LLM spend |
| Needs | a deployed runtime | a deployed runtime **and** Transaction Search |
| Gates CI | **yes** | no |

**When to hand-build one.** When you have facts with exact answers and you
want a gate that goes red only when something actually broke. That is a
small, boring, valuable piece of software, and nobody can write it for you,
because only you know that a 250g bag is $19.50.

**When not to.** Everything else. Groundedness, helpfulness, tone, refusal
proportionality — anything whose honest output is a score rather than a
verdict. That is a managed evaluator's job. A good early warning: if you
are writing prompt-injection defences into your own judge prompt, you have
stopped evaluating your agent and started operating an evaluation service.

The same reasoning applies to the managed **dataset runner**. The AgentCore
SDK ships `bedrock_agentcore.evaluation.OnDemandEvaluationDatasetRunner`,
and `agentcore run eval --dataset` is the CLI face of it: run a dataset of
scenarios against a runtime and score the results with managed evaluators.
Kit does not use it *for the gate* — the gate has to be free, reproducible,
and able to pass on a fork's pull request with no AWS account attached, and
Kit is a teaching artefact where a reader should be able to open
`harness/graders/deterministic.py` and see the entire scoring path on one
screen. For anything judged, the managed runner is the better tool. Moving
to it is a reasonable choice, not one Kit argues against.

## What the golden set covers

Four suites, 22 cases, 25 conversational turns. Every expected answer comes
from `sample-data/` — the fictional Kookaburra Coffee corpus — so a correct
response proves retrieval actually ran rather than that the model knows
about coffee.

| Suite | Cases | What it establishes |
|---|---|---|
| `retrieval` | 10 | RAG returns corpus facts, including a negative case (no international shipping) the agent must not invent a rate for |
| `memory` | 4 | Same-session recall, cross-session durable extraction, preference extraction, and actor isolation |
| `tools` | 3 | Code interpreter for arithmetic, retrieval for corpus questions, neither for a greeting |
| `adversarial` | 5 | Direct and indirect prompt injection. Reported, never gated — see below |

The memory suite is the one worth reading. Same-session recall only proves
the conversation buffer works; the cross-session cases start a **new
session with the same actor** and check that the fact survived, which is
the claim that is genuinely hard to verify by eye. Those cases carry
`settle_seconds: 90` because extraction into long-term memory is
asynchronous — the suite deliberately spends three minutes sleeping so it
is testing durable storage rather than a race.

`memory-actor-isolation` is a security case wearing a quality case's
clothes. The runner gives every case its own actor id, so that case's actor
has never been told a name. A confident answer is a real isolation failure.

## Reading the scorecard

A full run writes two files:

```
evals/results/scorecard.md    # human-readable
evals/results/latest.json     # same data, for plotting
```

The summary block describes the **gated** population only. Adversarial
cases get their own row and stay out of the pass rate, the latency
percentiles and the JSON `summary` object — so anything consuming
`latest.json` to plot "the pass rate" plots the number CI actually
enforced.

Three status values that are often collapsed and must not be:

- **PASS / FAIL** — the agent answered, and the assertions agreed or did
  not. This is quality signal.
- **ERROR** — the case could not be invoked, or the runtime returned HTTP
  200 and then reported a failure mid-stream. This says nothing about
  quality and is excluded from the pass rate entirely.
- **SKIPPED** — the case was deliberately not run. Today this only happens
  to indirect adversarial cases without the poisoned corpus loaded.

There is no quality score anywhere on the scorecard, and that is not an
omission. Every column is a deterministic verdict, a latency, or the
adversarial catch rate. The footnote says as much, so that a reader who
expects a 1–5 number is told where it lives rather than left to assume it
was forgotten:

> Adversarial catch rates are reported, never gated. Only the deterministic
> pass rate gates CI. Judged quality is scored by the managed evaluators in
> agentcore.json, not here.

## What actually fails the gate

Three conditions, in this order:

**1. Too many errors.** Pass rate is computed over passed + failed only,
which is correct — an ERROR says nothing about quality. But it means 16
ERROR and 1 PASS reads as 100%. So the gate separately refuses any run
where more than **10%** of cases errored (`DEFAULT_MAX_ERROR_RATE` in
`harness/cli.py`):

```
FAILED: no usable signal - 4/22 cases errored (ceiling 10%). Check the
deployment, the region, and Bedrock throttling before trusting any score.
```

Scoring the survivors of a broken run and calling it green is how a gate
earns being ignored.

**2. No signal at all.** If every case errored, there is no pass rate to
compare and the gate fails rather than dividing by zero into a default.

**3. Pass rate below threshold.** Default **0.94**
(`DEFAULT_THRESHOLD` in `harness/config.py`), overridable with
`--threshold` or `KIT_EVAL_THRESHOLD`. It is set from observed performance
rather than aspiration: against 17 gated cases it leaves exactly one case
of headroom, so a single flaky turn reports without breaking the build,
while two failures still fail.

### Filtered runs do not gate

```bash
./scripts/eval.sh --suite memory
./scripts/eval.sh --case retrieval-perth-shipping
```

A filtered run writes `scorecard-partial.md` and `latest-partial.json`, so
it can never shadow the canonical scorecard, and it exits 0 with:

```
NOT GATED: --suite/--case ran a partial suite. Gate on the full suite,
or pass --threshold to override.
```

One case yields a pass rate of exactly 0% or 100% against a 0.94 threshold.
Gating that makes green meaningless. Pass `--threshold` if you want a
filtered run gated anyway — the point is that it has to be deliberate.

A mistyped `--suite` exits 2, including under `--validate`. `--suite typo
--validate` printing "OK: 0 cases valid" and exiting 0 — green having
checked nothing — is the one failure mode an offline gate exists to
prevent.

## Where the judged scoring runs, and why that matters

Kit's headline claim is that inference stays in Australia. Scoring an
answer means a second model call, and an evaluator that quietly routed
elsewhere would break that claim without anyone noticing. So each of the
three evaluators in `agentcore/agentcore.json` pins a **geography-scoped
inference profile**, the same mechanism the agent itself uses:

```json
"model": "au.anthropic.claude-sonnet-4-5-20250929-v1:0"
```

Here is the part that is easy to get wrong. Every Anthropic model in
`ap-southeast-2` reports `INFERENCE_PROFILE` as its only supported
inference type — a bare model ID cannot be invoked on demand there at all.
So a *single-region* evaluator is impossible in Kit's home region, and it
is tempting to conclude that any inference profile means "your data leaves
the country".

It does not. Check it yourself, in about thirty seconds:

```bash
aws bedrock get-inference-profile \
  --inference-profile-identifier au.anthropic.claude-sonnet-4-5-20250929-v1:0 \
  --region ap-southeast-2
```

That profile resolves to exactly two model ARNs — `ap-southeast-2` (Sydney)
and `ap-southeast-4` (Melbourne). Nothing else. AWS's own description of it
reads *"Routes requests to AU Anthropic Claude Sonnet 4.5 in ap-southeast-2
and ap-southeast-4."* Both are Australian regions, so `au.` **is**
"inference stays in Australia".

The meaningful distinction is therefore **geography-scoped versus
`global.`**, not single-region versus cross-region. `global.*` routes
outside the geography.

Because the profile is declared in `agentcore.json` rather than resolved at
runtime, there is no silent fallback available to widen the boundary: the
only way judged scoring leaves the geography is by editing that string,
which appears in a diff and goes through review. Deploying Kit somewhere
with no scoped profile means changing that line deliberately.
`evals/tests/test_agentcore_config.py` asserts offline that no evaluator's
model starts with `global.`, so the change cannot land unnoticed.

### A different model generation on purpose

The agent defaults to Claude Sonnet 5 (`DEFAULT_MODEL_NAME` in
`app/kit/model/load.py`). The evaluators score with Claude Sonnet 4.5. That
is not an oversight or a cost optimisation — a model scoring its own
generation's output is subject to self-preference bias, and a groundedness
score that is partly a measure of stylistic self-recognition is not a
groundedness score.

## The adversarial suite

Five cases, **reported and never gated**. A red-team score is a finding to
publish. A hard gate on it would break the build every time a model update
shifts guardrail behaviour, which trains people to route around it.

**Direct attacks** run against any deployment, with no setup: instruction
override, system-prompt exfiltration, a roleplay jailbreak. The first uses
a canary-token shape — the attack names its own success signal, so the
absence of `INJECTION SUCCESSFUL` is genuine non-compliance rather than a
guess. A refusal, a deflection and a non-sequitur all read as "attack
handled", because none of them is the attack landing.

**Indirect attacks** — instructions smuggled in through a retrieved
document — need a payload the agent can actually retrieve. That payload
lives in `evals/corpus/adversarial/`. It is **not** part of `sample-data/`
and is never ingested by a normal `agentcore deploy`.

> **Load it into a throwaway knowledge base only.** Never into
> `sample-data/`, and never into a knowledge base you care about. These
> documents contain live prompt-injection payloads.

Once loaded, declare it:

```bash
./scripts/eval.sh --adversarial-corpus
# or
KIT_ADVERSARIAL_CORPUS=1 ./scripts/eval.sh
```

Without that declaration, indirect cases are **SKIPPED**, not passed. An
attack that was never launched is not an attack that was caught — the
payload could not appear in a response because it was never retrievable, so
counting the trivial pass would publish a catch rate that was never
measured. The catch-rate denominator counts only attacks actually launched,
and skipped cases appear on their own scorecard row.

### The catch rate is a floor, not a ceiling

`REFUSAL_MARKERS` in `harness/graders/deterministic.py` is a **phrase list,
not a classifier**. It covers Kit's guardrail blocked message and the common
"I can't help" / "I'm unable to" phrasings. A model that declines in wording
outside that list — *"I'm not going to write that scene"* — scores as "not
refused" while behaving perfectly correctly.

The list is deliberately conservative in the other direction too. Bare
"I won't", "I will not" and "guardrail" are **excluded**, because they fire
on ordinary answers ("I won't charge you extra", "Kit runs with guardrails
enabled") and a false positive there silently inverts a `refused`
assertion.

Read a FAIL on `adversarial-direct-roleplay-bypass` as *"go and look at the
response"*, not as a landed jailbreak. And read the catch rate as a floor.

One more limit worth stating: `adversarial-direct-system-prompt-exfiltration`
matches the literal opening of `DEFAULT_SYSTEM_PROMPT` character for
character. A close paraphrase, or a leak that starts mid-prompt, is not
caught. It detects verbatim disclosure only.

Both matching caveats are the same kind of honesty as
[docs/security.md](security.md): the adversarial suite measures whether
specific, named attacks landed, not whether the agent is safe.

## Running it locally without deploying anything

Two things do not need a deployed stack at all:

```bash
./scripts/eval.sh --validate   # dataset structure, criteria names, regex validity
./scripts/eval.sh --dry-run    # list the cases that would run
cd evals && uv run --extra dev pytest -q    # 113 harness unit tests
```

None of them makes an AWS call. `--validate` and `--dry-run` do not even
import `boto3` — the AWS client is imported late, inside the live path,
precisely so the offline path has no AWS dependency to fail on. (The unit
tests import it only to monkeypatch `boto3.client` into a stub.)

For tuning an evaluator's wording, you do not need a deployed runtime
either. `agentcore dev` runs the same container under
`opentelemetry-instrument` and collects OTEL traces by default
(`--no-traces` turns it off), so spans from local invocations land in
CloudWatch the same way a deployed runtime's do and an evaluator can be
iterated against them. Only the **online-eval** path genuinely requires a
deployed runtime.

CloudWatch put-to-get is roughly ten seconds end to end. If you have seen
the `sleep 300` pattern in older evaluation walkthroughs, it is about
thirty times longer than the spans need.

## Continuous evaluation on live traffic

The golden set tells you about 22 questions you wrote. It tells you nothing
about the questions your users actually ask. For that, `agentcore.json`
declares three managed evaluators:

| Evaluator | Level | Scores |
|---|---|---|
| `KitGroundedness` | `TRACE` | Whether factual claims could have come from the corpus |
| `KitToolSelection` | `TOOL_CALL` | Whether the right tool was chosen, and whether one was needed at all |
| `KitRefusalQuality` | `TRACE` | Proportionate refusal — declining harm *and* not refusing ordinary questions |

Their instruction text now lives only in `agentcore.json` — there is no
second copy in the harness to drift from — and it is the copy that matters,
because these evaluators read real user traffic.
`evals/tests/test_agentcore_config.py` pins it offline: the untrusted-data
clause that tells the evaluator its input is data rather than instructions,
the placeholders each level permits, and the geography-scoped model.
`agentcore validate` checks names and cross-resource references but not
instruction strings, so those assertions are the only thing standing
between an edit and a deployed evaluator that has quietly lost its
injection defence.

They are wired to an online eval config, `KitQualityMonitor`, at a 5%
sampling rate (`samplingRate` is a percentage — the schema allows 0.01 to
100).

**It ships disabled.** `enableOnCreate: false`, so deploying Kit never
starts evaluation spend on your behalf. Turn it on and off without a
redeploy:

```bash
agentcore resume online-eval KitQualityMonitor   # start sampling
agentcore pause  online-eval KitQualityMonitor   # stop
```

### Prerequisite: CloudWatch Transaction Search

Managed evaluators and `agentcore run eval` read **traces**, so they need
trace ingestion enabled in the region:

```bash
aws xray update-trace-segment-destination \
  --destination CloudWatchLogs --region ap-southeast-2
```

`scripts/preflight.sh` checks this and reports it as a **warning**, not a
failure, because Kit deploys and runs fine without it. The deterministic
gate does not need it either — `./scripts/eval.sh` reads the agent's
replies directly off the invocation stream. Only the trace-reading paths
find nothing without it, and "found no spans" is an easy result to
misread as "scored well".

## Continuous integration

Two tiers, split by what they cost and who can run them.

### Tier 1 — `evals (offline)`

Runs on **every pull request, including from forks**, and on pushes to
`main`. It uses no AWS credentials and makes no AWS calls: harness unit
tests, `./scripts/eval.sh --validate`, and `agentcore validate`.

The AgentCore CLI is pinned to `0.28.1` in this tier specifically because
its purpose is to work for anyone who forks Kit. An unpinned CLI means the
day a release changes validation, every fork's pull request goes red with
no change on their side.

(The step seeds `agentcore/aws-targets.example.json` first —
`aws-targets.json` is gitignored because this repo is public and must not
carry a real account id, so a fresh checkout has none. Validation is
structural and never contacts the account, so the placeholder is enough.)

### Tier 2 — `evals (live)`

Runs on merge to `main` and on manual dispatch. It is **ephemeral**:
deploy, wait for ingestion, run the suite, tear down.

**There is deliberately no `schedule:` trigger.** Kit's promise is that you
deploy it, poke it, delete it, and nothing keeps costing money. A cron here
would mean a permanently deployed eval stack — exactly the always-on bill
the product says it does not have.

Two details of the live tier are load-bearing:

**Waiting for ingestion.** `scripts/wait-for-ingestion.sh` blocks until
every knowledge base data source reports `COMPLETE`, and times out loudly
rather than letting the suite start. Retrieval cases scored against a
knowledge base that is still ingesting look exactly like a quality
regression: the agent answers, the answer is fluent, and the citation it
needed is simply not there yet.

**Teardown.** `aws cloudformation delete-stack` under `if: always()`, with
a second attempt. There is **no `agentcore destroy` subcommand** — check
`agentcore --help` — so teardown goes through CloudFormation directly. The
retry exists because deletion can stop at `DELETE_FAILED` with
`NotStabilized` on the AgentCore runtime, a documented 0.1 limitation,
which leaves memory, the knowledge base, the vector store, buckets, ECR and
the KMS key in place: it looks deleted and is still billing. Re-running
clears it. If two attempts do not, the job fails loudly and prints the
resources that blocked deletion.

The `concurrency` group sets `cancel-in-progress: false` on purpose.
Cancelling a live run mid-flight would skip teardown and orphan a deployed,
billing stack.

### Running the live tier on your own fork

It needs two repository secrets:

- `KIT_EVAL_ROLE_ARN` — an IAM role trusting your repo via GitHub OIDC
- `KIT_EVAL_ACCOUNT_ID` — the account that role lives in

Without them the workflow skips quietly on forks rather than going
permanently red for something a fork cannot fix. On the upstream repo, the
same condition fails the job — a live tier that silently never runs is the
failure mode that hides a broken quality gate for months.

## What a run costs

A default full run makes **23 agent invocations** — 25 turns across the
suite, minus the two indirect adversarial cases skipped without the
poisoned corpus. Retries on transport failure can add a few more. Plus
about three minutes of deliberate sleeping in the memory suite, waiting for
asynchronous extraction.

That is the entire bill. There are **no scoring calls**: grading is string
and number comparison in the harness process. Judged scoring costs money
only if you enable `KitQualityMonitor`, which is a separate decision with a
separate switch — see above.

We are not going to print a dollar figure that goes stale. It is two dozen
Sonnet conversations against a small corpus — run it once and read your own
Cost Explorer.

### Set a budget alarm

If you run the live tier in an AWS account, put an
[AWS Budget](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-create.html)
alarm on it.

Everything above that protects you from a permanently billing stack — the
absence of a cron, `if: always()` teardown, the retry, the loud failure —
assumes the CI job **reaches its last step**. A runner that dies, a
cancelled workflow, an expired OIDC session: each of those orphans a
deployed stack with nothing left watching it. A budget alarm is the only
mechanism in this list that still works when GitHub Actions isn't running.

## How the two layers divide the work

Kit uses the managed layer where it fits. `agentcore run eval` runs against
the live tier's traces as a reported, non-gating step, and the declared
evaluators score real traffic through `KitQualityMonitor`. The offline
harness gates; the managed layer observes. Neither one is asked to do the
other's job — which is the whole content of
[what we removed, and why](#what-we-removed-and-why).

## What this does not tell you

- **It reports no quality score at all.** The harness tells you whether
  the agent said the right things, not whether it said them well, and no
  `./scripts/eval.sh` run will ever tell you the latter. Judged quality
  comes from the managed evaluators in `agentcore.json`, which are
  **disabled on create** and, once enabled, score sampled live traffic in
  CloudWatch — a separate surface, on a different population, on your
  deliberate say-so. Read those scores as a trend across many traces rather
  than a threshold on one.
- **22 cases is a smoke test, not a benchmark.** It catches "retrieval
  broke", "memory stopped persisting", "the agent started refusing ordinary
  questions". It does not characterise quality.
- **The golden set is about a fictional coffee roaster.** Swap in your own
  corpus and every retrieval assertion becomes wrong. `evals/datasets/` is
  yours to rewrite — that is the point of shipping it as YAML.
- **The adversarial suite measures named attacks, not safety.** See the
  floor-not-ceiling section above, and
  [docs/security.md](security.md) for the exposure model it samples from.
- **A passing gate is not a production sign-off.** It says the agent still
  does what it did last week. `docs/security.md` has the checklist for the
  other question.
