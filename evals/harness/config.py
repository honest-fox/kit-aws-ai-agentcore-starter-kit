"""Resolve the deployment under test, plus models and thresholds.

Discovery matches docs/kit-evaluation.ipynb: read the CloudFormation stack
outputs. One harness therefore serves a local dev stack and the ephemeral
CI stack with no code change.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_STACK = "AgentCore-kit-default"
DEFAULT_REGION = "ap-southeast-2"

# The judge uses a GEOGRAPHY-SCOPED inference profile, matching what the
# agent itself does. Verified live against ap-southeast-2 on 23 Sep 2026:
#
#   * Every Anthropic model in ap-southeast-2 reports INFERENCE_PROFILE as
#     its only supported inference type. A bare model ID cannot be invoked
#     on-demand there at all, so a single-region judge is impossible in
#     Kit's home region via bedrock-runtime.
#   * au.anthropic.claude-sonnet-4-5-20250929-v1:0 resolves to exactly two
#     model ARNs - ap-southeast-2 (Sydney) and ap-southeast-4 (Melbourne).
#     Nothing else. So "au." IS "inference stays in Australia".
#
# The meaningful distinction is therefore geography-scoped vs global, not
# single-region vs cross-region. global.* is refused below because it would
# widen the boundary Kit advertises without telling anyone.
#
# Deliberately a different model generation from the agent's default
# (anthropic.claude-sonnet-5): a judge scoring its own model's output is
# subject to self-preference bias.
JUDGE_MODEL_NAME = "anthropic.claude-sonnet-4-5-20250929-v1:0"


def _geography_prefix(region: str) -> str:
    """Mirrors _geography_prefix in app/kit/model/load.py.

    Duplicated rather than imported: the harness must not take a dependency
    on code packaged into the agent container. A consistency test fails if
    the two ever drift apart.
    """
    if region in ("ap-southeast-2", "ap-southeast-4"):
        return "au"
    if region.startswith("us-"):
        return "us"
    if region.startswith("eu-"):
        return "eu"
    return "global"

DEFAULT_THRESHOLD = 0.90


@dataclass(frozen=True)
class Target:
    runtime_arn: str
    region: str
    stack: str
    api_url: str | None = None
    api_key_id: str | None = None
    memory_id: str | None = None


def _find(outputs: dict, needle: str) -> str | None:
    """Find one stack output by substring, refusing to guess when ambiguous.

    The L3 construct emits aggregate back-compat outputs alongside the
    per-resource ones: "MemoryId" matches both ApplicationMemoryKitMemoryId
    Output and ApplicationMemoryIds, the latter being a comma-joined list
    across every memory. With one memory the values coincide; with two the
    aggregate is not a valid id. describe_stacks guarantees no ordering, so
    picking the first match is a coin flip. Prefer explicit CfnOutput keys,
    and raise rather than choose when still ambiguous.
    """
    matches = {k: v for k, v in outputs.items() if needle.lower() in k.lower()}
    if len(matches) > 1:
        explicit = {k: v for k, v in matches.items() if "output" in k.lower()}
        if explicit:
            matches = explicit
    if not matches:
        return None
    if len(matches) > 1:
        raise ValueError(
            f"ambiguous stack output for {needle!r}: {sorted(matches)}. "
            "Narrow the lookup rather than guessing.")
    return next(iter(matches.values()))


def resolve_target(stack: str, region: str, cfn_client) -> Target:
    """Read stack outputs into a Target. Raises if the runtime is absent."""
    described = cfn_client.describe_stacks(StackName=stack)
    outputs = {
        o["OutputKey"]: o["OutputValue"]
        for o in described["Stacks"][0].get("Outputs", [])
    }
    runtime_arn = _find(outputs, "RuntimeArn")
    if not runtime_arn:
        raise ValueError(
            f"stack {stack} has no RuntimeArn output — is Kit deployed to {region}?")
    return Target(
        runtime_arn=runtime_arn,
        region=region,
        stack=stack,
        api_url=_find(outputs, "ApiUrl"),
        api_key_id=_find(outputs, "ApiKeyId"),
        memory_id=_find(outputs, "MemoryId"),
    )


def judge_model_id(region: str) -> str:
    """The geography-scoped judge profile for a region.

    Refuses to fall back to global.* silently: that would widen the
    inference boundary Kit advertises. Set KIT_JUDGE_MODEL_ID to opt in
    deliberately, or run with --no-judge.
    """
    override = os.environ.get("KIT_JUDGE_MODEL_ID")
    if override:
        return override
    prefix = _geography_prefix(region)
    if prefix == "global":
        raise ValueError(
            f"no geography-scoped inference profile for {region}: the only "
            "option there is global.*, which routes outside the geography. "
            "Set KIT_JUDGE_MODEL_ID explicitly to accept that, or use "
            "--no-judge.")
    return f"{prefix}.{JUDGE_MODEL_NAME}"


def threshold() -> float:
    return float(os.environ.get("KIT_EVAL_THRESHOLD", DEFAULT_THRESHOLD))


def stack_name() -> str:
    return os.environ.get("KIT_EVAL_STACK", DEFAULT_STACK)


def region() -> str:
    # CI runners commonly set only AWS_DEFAULT_REGION.
    return (
        os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
        or DEFAULT_REGION
    )
