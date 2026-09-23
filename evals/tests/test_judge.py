import json
import pytest
from harness.graders.judge import BedrockJudge, NullJudge, CRITERIA, JudgeScore


class FakeBedrock:
    def __init__(self, payload=None, raise_with=None):
        self.payload = payload
        self.raise_with = raise_with
        self.last_kwargs = None

    def invoke_model(self, **kwargs):
        if self.raise_with:
            raise self.raise_with
        self.last_kwargs = kwargs
        body = {"content": [{"type": "text", "text": json.dumps(self.payload)}]}
        return {"body": _Body(json.dumps(body))}


class _Body:
    def __init__(self, text):
        self._text = text

    def read(self):
        return self._text.encode()


def test_judge_parses_score_and_rationale():
    judge = BedrockJudge("model-x", FakeBedrock({"score": 4, "rationale": "grounded"}))
    s = judge.score("groundedness", "What price?", "It is $19.50.")
    assert s.score == 4.0
    assert "grounded" in s.rationale


def test_judge_clamps_out_of_range_scores():
    judge = BedrockJudge("model-x", FakeBedrock({"score": 9, "rationale": "r"}))
    assert judge.score("groundedness", "q", "a").score == 5.0


def test_judge_returns_unscored_on_client_error_rather_than_raising():
    judge = BedrockJudge("model-x", FakeBedrock(raise_with=RuntimeError("throttled")))
    s = judge.score("groundedness", "q", "a")
    assert s.score is None
    assert "throttled" in s.rationale


def test_judge_returns_unscored_on_unparseable_output():
    judge = BedrockJudge("model-x", FakeBedrock("not-a-dict"))
    assert judge.score("groundedness", "q", "a").score is None


def test_unknown_criterion_raises():
    judge = BedrockJudge("model-x", FakeBedrock({"score": 3, "rationale": "r"}))
    with pytest.raises(ValueError, match="unknown judge criterion"):
        judge.score("vibes", "q", "a")


def test_null_judge_always_returns_unscored():
    s = NullJudge().score("groundedness", "q", "a")
    assert s.score is None


def test_every_criterion_has_instructions_and_a_scale():
    for name, spec in CRITERIA.items():
        assert spec["instructions"].strip()
        assert len(spec["scale"]) == 5
