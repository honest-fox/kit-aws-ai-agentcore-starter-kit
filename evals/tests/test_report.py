from harness.report import CaseResult, summarise, render_markdown, render_json
from harness.graders.deterministic import Verdict


def result(case_id, suite, status, latency=100.0, judge=None, error=None):
    return CaseResult(
        case_id=case_id, suite=suite, status=status,
        assertions=[Verdict(status == "PASS", "detail")],
        judge_scores=judge or {}, latency_ms=latency, error=error,
    )


def test_pass_rate_excludes_errors_from_the_denominator():
    results = [
        result("a", "retrieval", "PASS"),
        result("b", "retrieval", "FAIL"),
        result("c", "retrieval", "ERROR", error="timeout"),
    ]
    s = summarise(results)
    assert s["passed"] == 1
    assert s["failed"] == 1
    assert s["errored"] == 1
    assert s["pass_rate"] == 0.5


def test_pass_rate_is_none_when_everything_errored():
    s = summarise([result("a", "x", "ERROR", error="boom")])
    assert s["pass_rate"] is None


def test_markdown_reports_errors_in_their_own_column():
    md = render_markdown(
        [result("a", "retrieval", "ERROR", error="timeout")],
        {"model_id": "au.test", "region": "ap-southeast-2", "git_sha": "abc123"},
    )
    assert "ERROR" in md
    assert "timeout" in md
    assert "au.test" in md


def test_markdown_includes_judge_scores_when_present():
    md = render_markdown(
        [result("a", "retrieval", "PASS", judge={"groundedness": 4.5})],
        {"model_id": "m", "region": "r", "git_sha": "s"},
    )
    assert "4.5" in md


def test_json_round_trips_the_summary_and_cases():
    payload = render_json(
        [result("a", "retrieval", "PASS")],
        {"model_id": "m", "region": "r", "git_sha": "s"},
    )
    assert payload["summary"]["passed"] == 1
    assert payload["cases"][0]["case_id"] == "a"
    assert payload["meta"]["model_id"] == "m"
