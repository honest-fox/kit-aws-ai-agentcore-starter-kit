from pathlib import Path

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


def test_judge_uses_the_australian_geography_profile_in_sydney():
    # Verified live: au.* resolves to ap-southeast-2 + ap-southeast-4 only,
    # so it satisfies "inference stays in Australia".
    assert judge_model_id("ap-southeast-2").startswith("au.")
    assert judge_model_id("ap-southeast-4").startswith("au.")


def test_judge_never_falls_back_to_global_silently():
    # global.* routes outside the geography Kit advertises.
    with pytest.raises(ValueError, match="routes outside the geography"):
        judge_model_id("sa-east-1")


def test_judge_model_is_a_different_generation_from_the_agent_default():
    # A judge scoring its own model's output has self-preference bias.
    from harness.config import JUDGE_MODEL_NAME
    assert "sonnet-4-5" in JUDGE_MODEL_NAME


def test_env_override_wins_so_global_can_be_opted_into(monkeypatch):
    monkeypatch.setenv("KIT_JUDGE_MODEL_ID", "global.anthropic.whatever")
    assert judge_model_id("sa-east-1") == "global.anthropic.whatever"


def test_geography_logic_matches_the_agents_own(monkeypatch):
    """The harness duplicates app/kit/model/load.py. Catch any drift."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app" / "kit"))
    monkeypatch.setitem(sys.modules, "strands.models.bedrock", None)
    from harness.config import _geography_prefix as harness_prefix
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_agent_load",
        Path(__file__).resolve().parents[2] / "app" / "kit" / "model" / "load.py")
    # Import the function without importing strands: read and exec just it.
    source = spec.origin
    ns = {}
    text = Path(source).read_text()
    start = text.index("def _geography_prefix")
    end = text.index("def default_model_id")
    exec(text[start:end], ns)
    agent_prefix = ns["_geography_prefix"]
    for r in ("ap-southeast-2", "ap-southeast-4", "us-west-2", "us-east-1",
              "eu-west-1", "sa-east-1", "ap-northeast-1"):
        assert harness_prefix(r) == agent_prefix(r), r


def test_find_refuses_to_guess_between_ambiguous_outputs():
    # Real CDK keys: the L3 construct emits an aggregate alongside the
    # per-memory output, and describe_stacks guarantees no ordering.
    cfn = FakeCfn({
        "ApplicationAgentKitRuntimeArnOutput2F2A5C0D": "arn:x:runtime/kit",
        "ApplicationMemoryKitMemoryIdOutput4310CF3E": "mem-correct",
        "ApplicationMemoryIds538D889E": "mem-a,mem-b",
    })
    assert resolve_target("s", "r", cfn).memory_id == "mem-correct"


def test_find_raises_when_two_explicit_outputs_collide():
    cfn = FakeCfn({
        "KitRuntimeArnOutput": "arn:x:runtime/kit",
        "AnotherMemoryIdOutput": "mem-a",
        "YetMoreMemoryIdOutput": "mem-b",
    })
    with pytest.raises(ValueError, match="ambiguous stack output"):
        resolve_target("s", "r", cfn)


def test_default_stack_matches_the_deployment_guide():
    assert DEFAULT_STACK == "AgentCore-kit-default"
