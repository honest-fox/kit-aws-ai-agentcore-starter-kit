"""LLM-as-a-judge quality scoring on Bedrock.

Judge scores are reported as a trend and never gate CI. A judge outage
degrades a case to "unscored" - the deterministic verdict still stands and
still counts, so the gate never depends on model availability.

The instructions and scales below are the source text for the custom
evaluators in agentcore/agentcore.json, so the offline and online layers
score against the same words.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

SCALE_1_5 = [
    (1, "Unacceptable"),
    (2, "Poor"),
    (3, "Acceptable"),
    (4, "Good"),
    (5, "Excellent"),
]

CRITERIA = {
    "groundedness": {
        "instructions": (
            "You are evaluating whether an AI assistant's answer is grounded in "
            "the Kookaburra Coffee Co. knowledge base it retrieves from. Score "
            "high when every factual claim could plausibly have come from a "
            "product catalogue, policy or FAQ document. Score low when the "
            "answer invents specifics, contradicts itself, or answers a "
            "company-specific question from general knowledge."
        ),
        "scale": SCALE_1_5,
    },
    "helpfulness": {
        "instructions": (
            "You are evaluating whether an AI assistant's answer is useful and "
            "direct. Score high when it answers the question asked, concisely "
            "and without hedging. Score low when it is evasive, padded, or "
            "answers a different question."
        ),
        "scale": SCALE_1_5,
    },
}

_PROMPT = """{instructions}

Rating scale:
{scale}

User question:
{question}

Assistant answer:
{answer}

Respond with JSON only, no prose, in exactly this shape:
{{"score": <integer 1-5>, "rationale": "<one sentence>"}}"""


@dataclass(frozen=True)
class JudgeScore:
    criterion: str
    score: float | None
    rationale: str


class NullJudge:
    """Used by --no-judge. Keeps the runner free of conditionals."""

    def score(self, criterion: str, question: str, answer: str) -> JudgeScore:
        return JudgeScore(criterion, None, "judge disabled")


class BedrockJudge:
    def __init__(self, model_id: str, client):
        self._model_id = model_id
        self._client = client

    def score(self, criterion: str, question: str, answer: str) -> JudgeScore:
        if criterion not in CRITERIA:
            raise ValueError(f"unknown judge criterion: {criterion!r}")
        spec = CRITERIA[criterion]
        scale = "\n".join(f"{n}: {label}" for n, label in spec["scale"])
        prompt = _PROMPT.format(
            instructions=spec["instructions"], scale=scale,
            question=question, answer=answer,
        )
        try:
            resp = self._client.invoke_model(
                modelId=self._model_id,
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 256,
                    "temperature": 0,
                    "messages": [{"role": "user", "content": prompt}],
                }),
            )
            envelope = json.loads(resp["body"].read())
            text = envelope["content"][0]["text"]
            parsed = json.loads(text)
            if not isinstance(parsed, dict):
                raise ValueError("judge did not return an object")
            score = float(parsed["score"])
            score = max(1.0, min(5.0, score))
            return JudgeScore(criterion, score, str(parsed.get("rationale", "")))
        except Exception as exc:  # noqa: BLE001 - degrade, never fail the run
            return JudgeScore(criterion, None, f"judge unavailable: {exc}")
