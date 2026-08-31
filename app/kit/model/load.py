import os

from strands.models.bedrock import BedrockModel

# au.* inference profiles keep inference within Australian regions — Kit's
# data-residency default. Override via KIT_MODEL_ID (e.g. a global.* profile
# or another region geography) without rebuilding the image.
DEFAULT_MODEL_ID = "au.anthropic.claude-sonnet-5"


def load_model() -> BedrockModel:
    """Get Bedrock model client using IAM credentials."""
    return BedrockModel(model_id=os.environ.get("KIT_MODEL_ID", DEFAULT_MODEL_ID))
