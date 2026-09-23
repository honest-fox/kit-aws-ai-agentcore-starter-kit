import pytest
from harness.invoke import FakeTransport, Response, parse_sse_stream, new_session_id


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


def test_session_ids_differ_per_turn_index():
    assert new_session_id("r", "c", 0) != new_session_id("r", "c", 1)


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
