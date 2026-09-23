import pytest
from harness.config import resolve_target, judge_model_id, DEFAULT_STACK


class FakeCfn:
    def __init__(self, outputs):
        self._outputs = outputs

    def describe_stacks(self, StackName):
        return {"Stacks": [{"Outputs": [
            {"OutputKey": k, "OutputValue": v} for k, v in self._outputs.items()
        ]}]}


def test_resolve_target_reads_stack_outputs():
    cfn = FakeCfn({
        "KitRuntimeArn": "arn:aws:bedrock-agentcore:ap-southeast-2:1:runtime/kit",
        "KitApiUrl": "https://api.example/invoke",
        "KitApiKeyId": "key123",
        "MemoryKitMemoryId": "mem123",
    })
    t = resolve_target("AgentCore-kit-default", "ap-southeast-2", cfn)
    assert t.runtime_arn.endswith("runtime/kit")
    assert t.api_url == "https://api.example/invoke"
    assert t.api_key_id == "key123"
    assert t.memory_id == "mem123"
    assert t.region == "ap-southeast-2"


def test_resolve_target_tolerates_a_missing_memory_output():
    cfn = FakeCfn({"KitRuntimeArn": "arn:x:runtime/kit"})
    t = resolve_target("s", "r", cfn)
    assert t.memory_id is None


def test_resolve_target_fails_loudly_without_a_runtime_arn():
    cfn = FakeCfn({"KitApiUrl": "https://api.example/invoke"})
    with pytest.raises(ValueError, match="no RuntimeArn output"):
        resolve_target("AgentCore-kit-default", "r", cfn)


def test_judge_model_is_region_pinned_not_cross_region():
    model = judge_model_id("ap-southeast-2")
    assert not model.startswith("global.")
    assert not model.startswith("au.")


def test_default_stack_matches_the_deployment_guide():
    assert DEFAULT_STACK == "AgentCore-kit-default"
