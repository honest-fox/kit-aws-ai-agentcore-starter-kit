"""Orchestrate cases: sessions, actors, retries, grading.

Transport, judge and sleep are all injected, so the whole orchestration
layer is unit-testable offline and instantly.
"""
from __future__ import annotations

import time
from typing import Callable

from .datasets import Case
from .graders.deterministic import grade
from .invoke import new_session_id
from .report import CaseResult

# Mirrors _ACTOR_ID_ALLOWED in app/kit/main.py. The agent rejects anything
# outside this set, so the harness must not generate one.
_ACTOR_ALLOWED = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.:@")
_ACTOR_MAX_LEN = 128


def actor_id_for(case_id: str, run_id: str) -> str:
    """One isolated memory namespace per case, stable within a run.

    Isolation matters: cases that shared an actor would contaminate each
    other's long-term memory, and memory-actor-isolation would fail
    spuriously, making the whole memory suite meaningless.
    """
    raw = f"eval-{run_id}-{case_id}"
    cleaned = "".join(c if c in _ACTOR_ALLOWED else "-" for c in raw)
    return cleaned[:_ACTOR_MAX_LEN]


def _send_with_retry(transport, prompt, session_id, actor_id, retries, sleep):
    last: Exception | None = None
    for attempt in range(retries):
        try:
            return transport.send(prompt, session_id, actor_id)
        except AssertionError:
            # Test-double contract violations (FakeTransport exhaustion) are
            # programming errors. Retrying and reclassifying them as ERROR
            # would hide the loud failure the guard exists to produce.
            raise
        except Exception as exc:  # noqa: BLE001 - classified as ERROR below
            last = exc
            if attempt < retries - 1:
                # Bedrock throttling windows routinely outlast 3s.
                sleep(2 * 2 ** attempt)
    raise last  # type: ignore[misc]


def run_case(
    case: Case,
    transport,
    judge,
    run_id: str,
    retries: int = 3,
    sleep: Callable[[float], None] = time.sleep,
) -> CaseResult:
    actor_id = actor_id_for(case.id, run_id)
    # Derived ONCE and reused across turns. Calling new_session_id per turn
    # would silently start a fresh session every turn and guarantee a false
    # FAIL on memory-same-session-recall.
    session_id = new_session_id(run_id, case.id, 0)
    verdicts = []
    judge_scores: dict[str, float] = {}
    judge_attempted = 0
    judge_scored = 0
    total_latency = 0.0
    history: list[str] = []

    for index, turn in enumerate(case.turns):
        if turn.new_session:
            if case.settle_seconds:
                sleep(case.settle_seconds)
            session_id = new_session_id(run_id, case.id, index)
        try:
            response = _send_with_retry(
                transport, turn.prompt, session_id, actor_id, retries, sleep)
        except AssertionError:
            # As in _send_with_retry: a test-double contract violation is a
            # programming error, not an infrastructure failure. Classifying
            # it as ERROR would bury an off-by-one in the runner itself.
            raise
        except Exception as exc:  # noqa: BLE001
            return CaseResult(
                case_id=case.id, suite=case.suite, status="ERROR",
                # Keep verdicts already gathered: ERROR is excluded from the
                # pass rate either way, and they are diagnostic evidence.
                assertions=verdicts, judge_scores=judge_scores,
                latency_ms=total_latency, error=str(exc), tags=case.tags,
                judge_attempted=judge_attempted, judge_scored=judge_scored,
            )
        total_latency += response.latency_ms

        for assertion in turn.grade:
            if assertion.get("type") == "judge":
                judge_attempted += 1
                # On a multi-turn case the grounding material lives in
                # earlier turns. Judging the last prompt in isolation would
                # score a CORRECT answer low for citing facts whose source
                # the judge cannot see - a silent corruption of the signal,
                # read later as a model regression.
                question = (
                    "\n\n".join(history + [f"User: {turn.prompt}"])
                    if len(case.turns) > 1 else turn.prompt
                )
                scored = judge.score(
                    assertion["criterion"], question, response.text)
                if scored.score is not None:
                    judge_scores[scored.criterion] = scored.score
                    judge_scored += 1
                continue
            verdicts.append(grade(assertion, response.text))

        history.append(f"User: {turn.prompt}")
        history.append(f"Assistant: {response.text}")

    status = "PASS" if all(v.passed for v in verdicts) else "FAIL"
    return CaseResult(
        case_id=case.id, suite=case.suite, status=status,
        assertions=verdicts, judge_scores=judge_scores,
        latency_ms=total_latency, error=None, tags=case.tags,
        judge_attempted=judge_attempted, judge_scored=judge_scored,
    )


def run_all(
    cases: list[Case],
    transport,
    judge,
    run_id: str,
    retries: int = 3,
    sleep: Callable[[float], None] = time.sleep,
    on_result: Callable[[CaseResult], None] | None = None,
) -> list[CaseResult]:
    results = []
    for case in cases:
        result = run_case(case, transport, judge, run_id, retries, sleep)
        if on_result:
            on_result(result)
        results.append(result)
    return results
