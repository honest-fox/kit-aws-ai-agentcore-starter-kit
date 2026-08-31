import os

from strands.models.bedrock import BedrockModel

# au.* inference profiles keep inference within Australian regions — Kit's
# data-residency default. Override via KIT_MODEL_ID (e.g. a global.* profile
# or another region geography) without rebuilding the image.
DEFAULT_MODEL_ID = "au.anthropic.claude-sonnet-5"


def load_model() -> BedrockModel:
    """Get Bedrock model client using IAM credentials.

    Applies the Kit guardrail when the deployment provides one
    (KIT_GUARDRAIL_ID / KIT_GUARDRAIL_VERSION are injected by the CDK stack).
    Set KIT_GUARDRAIL_ID to an empty string to disable without a stack change.
    """
    kwargs = {"model_id": os.environ.get("KIT_MODEL_ID", DEFAULT_MODEL_ID)}
    guardrail_id = os.environ.get("KIT_GUARDRAIL_ID")
    if guardrail_id:
        kwargs["guardrail_id"] = guardrail_id
        kwargs["guardrail_version"] = os.environ.get("KIT_GUARDRAIL_VERSION", "DRAFT")
    return BedrockModel(**kwargs)
