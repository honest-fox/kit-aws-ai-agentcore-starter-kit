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

# Deliberately region-pinned rather than a cross-region inference profile.
# AgentCore's built-in and default LLM-as-judge evaluators use cross-region
# inference, which would widen the inference boundary Kit advertises. See
# docs/evaluation.md.
_JUDGE_MODELS = {
    "ap-southeast-2": "anthropic.claude-sonnet-4-5-20250929-v1:0",
    "us-west-2": "anthropic.claude-sonnet-4-5-20250929-v1:0",
    "us-east-1": "anthropic.claude-sonnet-4-5-20250929-v1:0",
}

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
    for key, value in outputs.items():
        if needle.lower() in key.lower():
            return value
    return None


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
    override = os.environ.get("KIT_JUDGE_MODEL_ID")
    if override:
        return override
    if region not in _JUDGE_MODELS:
        raise ValueError(
            f"no region-pinned judge model configured for {region}. "
            "Set KIT_JUDGE_MODEL_ID explicitly, or run with --no-judge.")
    return _JUDGE_MODELS[region]


def threshold() -> float:
    return float(os.environ.get("KIT_EVAL_THRESHOLD", DEFAULT_THRESHOLD))


def stack_name() -> str:
    return os.environ.get("KIT_EVAL_STACK", DEFAULT_STACK)


def region() -> str:
    return os.environ.get("AWS_REGION", DEFAULT_REGION)
