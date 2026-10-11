import pytest
from harness.invoke import (
    AgentStreamError, FakeTransport, Response, parse_sse_stream, new_session_id)


def test_parse_sse_stream_concatenates_text_deltas():
    lines = [
        b'data: {"event": {"contentBlockDelta": {"delta": {"text": "Hello "}}}}',
        b'data: {"event": {"contentBlockDelta": {"delta": {"text": "world"}}}}',
    ]
    assert parse_sse_stream(lines) == "Hello world"


def test_parse_sse_stream_ignores_non_data_and_malformed_lines():
    lines = [
        b'', b':heartbeat',
        b'data: not-json',
        b'data: {"event": {"contentBlockDelta": {"delta": {"text": "ok"}}}}',
        b'data: {"event": {"messageStop": {}}}',
    ]
    assert parse_sse_stream(lines) == "ok"


def test_session_ids_meet_the_33_character_minimum():
    sid = new_session_id("run1", "short-case")
    assert len(sid) >= 33


def test_session_ids_carry_the_turn_index():
    # Asserting inequality alone passes even if turn_index were dropped,
    # because every id carries random entropy.
    assert "-t0-" in new_session_id("r", "c", 0)
    assert "-t7-" in new_session_id("r", "c", 7)


def test_session_ids_are_unique_even_for_long_case_ids():
    # A deterministic id means a retry reuses its session, and AgentCore
    # Memory restores the failed attempt's history into the retry.
    long_case = "tools-retrieval-preferred-over-general-knowledge"
    assert new_session_id("run1", long_case) != new_session_id("run1", long_case)


def test_truncation_preserves_the_discriminators_not_the_case_id():
    sid = new_session_id("r" * 40, "c" * 80, 3)
    assert len(sid) <= 96
    assert "-t3-" in sid


def test_fake_transport_records_calls_and_returns_scripted_replies():
    t = FakeTransport(["first", "second"])
    r1 = t.send("p1", "s1", "a1")
    r2 = t.send("p2", "s2", "a1")
    assert isinstance(r1, Response)
    assert r1.text == "first"
    assert r2.text == "second"
    assert t.calls[0]["prompt"] == "p1"
    assert t.calls[1]["session_id"] == "s2"


def test_fake_transport_can_raise_to_simulate_infrastructure_failure():
    t = FakeTransport([RuntimeError("throttled")])
    with pytest.raises(RuntimeError, match="throttled"):
        t.send("p", "s", "a")


def test_a_mid_stream_error_event_raises_instead_of_yielding_empty_text():
    # bedrock_agentcore emits failures as a data: line after HTTP 200.
    # Parsed naively this returns "", and the harness scores an
    # infrastructure failure as a content FAIL.
    lines = [b'data: {"error": "ThrottlingException", "error_type": "ClientError", "message": "An error occurred during streaming"}']
    with pytest.raises(AgentStreamError, match="ClientError"):
        parse_sse_stream(lines)


def test_normal_events_are_not_mistaken_for_errors():
    lines = [b'data: {"event": {"contentBlockDelta": {"delta": {"text": "no error here"}}}}']
    assert parse_sse_stream(lines) == "no error here"


def test_fake_transport_raises_when_replies_run_out():
    t = FakeTransport(["only one"])
    t.send("p", "s", "a")
    with pytest.raises(AssertionError, match="exhausted"):
        t.send("p", "s", "a")
