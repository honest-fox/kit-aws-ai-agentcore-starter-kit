import os

from strands.models.bedrock import BedrockModel

# Kit defaults to geography-scoped inference profiles so model traffic stays
# in the deployment's geography: au.* in Australian regions (Kit's
# first-class home), us.* / eu.* in those geographies, and global.* where no
# scoped profile is available (verified: apac.* profiles lag behind current
# models). Override everything with KIT_MODEL_ID — no rebuild needed.
DEFAULT_MODEL_NAME = "anthropic.claude-sonnet-5"


def _geography_prefix(region: str) -> str:
    if region in ("ap-southeast-2", "ap-southeast-4"):
        return "au"
    if region.startswith("us-"):
        return "us"
    if region.startswith("eu-"):
        return "eu"
    return "global"


def default_model_id() -> str:
    region = os.environ.get("AWS_REGION", "ap-southeast-2")
    return f"{_geography_prefix(region)}.{DEFAULT_MODEL_NAME}"


def load_model() -> BedrockModel:
    """Get Bedrock model client using IAM credentials.

    Applies the Kit guardrail when the deployment provides one
    (KIT_GUARDRAIL_ID / KIT_GUARDRAIL_VERSION are injected by the CDK stack).
    Set KIT_GUARDRAIL_ID to an empty string to disable without a stack change.
    """
    kwargs = {"model_id": os.environ.get("KIT_MODEL_ID") or default_model_id()}
    guardrail_id = os.environ.get("KIT_GUARDRAIL_ID")
    if guardrail_id:
        kwargs["guardrail_id"] = guardrail_id
        kwargs["guardrail_version"] = os.environ.get("KIT_GUARDRAIL_VERSION", "DRAFT")
    return BedrockModel(**kwargs)
