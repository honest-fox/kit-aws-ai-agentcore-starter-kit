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


# Set from observed performance, not aspiration. Two live runs on
# 2026-09-24: 94.1% (one brittle assertion, since fixed) then 100% on 17
# gated cases. 0.94 leaves exactly one case of headroom, so a single flaky
# turn reports without breaking the build - a gate that breaks on any
# single flake is a gate people switch off. Two or more failures, or an
# error rate over DEFAULT_MAX_ERROR_RATE, still fail.
DEFAULT_THRESHOLD = 0.94


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
