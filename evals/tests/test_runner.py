from harness.runner import run_case, run_all, actor_id_for
from harness.datasets import Case, Turn
from harness.invoke import FakeTransport, AgentStreamError


def case(case_id="c1", turns=None, settle=0):
    return Case(id=case_id, suite="s", tags=[], settle_seconds=settle,
                turns=turns or [Turn("q", False,
                                     [{"type": "contains_all", "values": ["ok"]}])])


def test_passing_case_is_marked_pass():
    r = run_case(case(), FakeTransport(["ok"]), "run1", sleep=lambda s: None)
    assert r.status == "PASS"


def test_failing_assertion_is_marked_fail_not_error():
    r = run_case(case(), FakeTransport(["nope"]), "run1", sleep=lambda s: None)
    assert r.status == "FAIL"
    assert r.error is None


def test_transport_failure_after_retries_is_error_not_fail():
    t = FakeTransport([RuntimeError("boom"), RuntimeError("boom"), RuntimeError("boom")])
    r = run_case(case(), t, "run1", retries=3, sleep=lambda s: None)
    assert r.status == "ERROR"
    assert "boom" in r.error


def test_a_mid_stream_agent_error_is_classified_as_error():
    t = FakeTransport([AgentStreamError("ThrottlingException")] * 3)
    r = run_case(case(), t, "run1", retries=3, sleep=lambda s: None)
    assert r.status == "ERROR"
    assert "Throttling" in r.error


def test_transport_failure_is_retried_and_can_recover():
    t = FakeTransport([RuntimeError("transient"), "ok"])
    r = run_case(case(), t, "run1", retries=3, sleep=lambda s: None)
    assert r.status == "PASS"
    assert len(t.calls) == 2


def test_actor_id_is_stable_per_case_and_unique_across_cases():
    a = actor_id_for("case-one", "run1")
    assert a == actor_id_for("case-one", "run1")
    assert a != actor_id_for("case-two", "run1")


def test_actor_id_uses_only_characters_the_agent_accepts():
    allowed = set(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.:@")
    generated = actor_id_for("case with spaces/and!punct", "run1")
    assert set(generated) <= allowed
    assert len(generated) <= 128


def test_all_turns_share_one_session_unless_new_session_is_set():
    turns = [
        Turn("first", False, []),
        Turn("second", False, [{"type": "contains_all", "values": ["ok"]}]),
    ]
    t = FakeTransport(["x", "ok"])
    run_case(case(turns=turns), t, "run1", sleep=lambda s: None)
    assert t.calls[0]["session_id"] == t.calls[1]["session_id"]


def test_new_session_turn_gets_a_different_session_but_the_same_actor():
    turns = [
        Turn("first", False, []),
        Turn("second", True, [{"type": "contains_all", "values": ["ok"]}]),
    ]
    t = FakeTransport(["x", "ok"])
    run_case(case(turns=turns), t, "run1", sleep=lambda s: None)
    assert t.calls[0]["session_id"] != t.calls[1]["session_id"]
    assert t.calls[0]["actor_id"] == t.calls[1]["actor_id"]


def test_settle_seconds_is_slept_before_a_new_session_turn():
    slept = []
    turns = [
        Turn("first", False, []),
        Turn("second", True, [{"type": "contains_all", "values": ["ok"]}]),
    ]
    run_case(case(turns=turns, settle=90), FakeTransport(["x", "ok"]),
             "run1", sleep=slept.append)
    assert 90 in slept


def test_run_all_returns_one_result_per_case():
    results = run_all([case("a"), case("b")], FakeTransport(["ok", "ok"]),
                      "run1", sleep=lambda s: None)
    assert [r.case_id for r in results] == ["a", "b"]

def test_verdicts_are_kept_when_a_later_turn_errors():
    turns = [
        Turn("first", False, [{"type": "contains_all", "values": ["ok"]}]),
        Turn("second", False, [{"type": "contains_all", "values": ["ok"]}]),
    ]
    t = FakeTransport(["ok"] + [RuntimeError("boom")] * 3)
    r = run_case(case(turns=turns), t, "run1", retries=3,
                 sleep=lambda s: None)
    assert r.status == "ERROR"
    assert len(r.assertions) == 1     # turn 1's evidence survives


def test_fake_transport_exhaustion_is_not_swallowed_as_an_error_status():
    # The guard exists to fail loudly on an off-by-one in the runner.
    import pytest
    with pytest.raises(AssertionError, match="exhausted"):
        run_case(case(), FakeTransport([]), "run1",
                 sleep=lambda s: None)
