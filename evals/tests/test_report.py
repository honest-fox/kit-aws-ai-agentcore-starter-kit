from harness.report import (
    CaseResult, summarise, render_markdown, render_json,
    adversarial_summary, split_suites,
)
from harness.graders.deterministic import Verdict


def result(case_id, suite, status, latency=100.0, error=None):
    return CaseResult(
        case_id=case_id, suite=suite, status=status,
        assertions=[Verdict(status == "PASS", "detail")],
        latency_ms=latency, error=error,
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



def test_json_round_trips_the_summary_and_cases():
    payload = render_json(
        [result("a", "retrieval", "PASS")],
        {"model_id": "m", "region": "r", "git_sha": "s"},
    )
    assert payload["summary"]["passed"] == 1
    assert payload["cases"][0]["case_id"] == "a"
    assert payload["meta"]["model_id"] == "m"


def test_percentiles_use_nearest_rank_so_small_samples_are_honest():
    # With 17 cases the 95th percentile genuinely is the slowest one.
    results = [result(f"c{i}", "s", "PASS", latency=float(i)) for i in range(1, 18)]
    s = summarise(results)
    assert s["p95_latency_ms"] == 17.0
    assert s["p50_latency_ms"] == 9.0


def test_p95_does_not_overshoot_at_multiples_of_twenty():
    # int(n*0.95) lands on an integer at n=100 and floors one rank too high.
    results = [result(f"c{i}", "s", "PASS", latency=float(i)) for i in range(1, 101)]
    assert summarise(results)["p95_latency_ms"] == 95.0


def test_a_pipe_in_a_failure_detail_cannot_break_the_table():
    # Reachable: a regex pattern with an alternation lands in the detail.
    r = CaseResult(
        case_id="a", suite="s", status="FAIL",
        assertions=[Verdict(False, r"no match for /(?i)\b(5|five)[\s-]?year/")],
    )
    md = render_markdown([r], {"model_id": "m", "region": "r", "git_sha": "s"})
    row = next(line for line in md.splitlines() if line.startswith("| `a`"))
    assert row.count("|") - row.count("\\|") == 6   # 5 columns, 6 delimiters


def test_latency_excludes_errored_cases_from_the_sample():
    results = [
        result("a", "s", "PASS", latency=10.0),
        result("b", "s", "ERROR", latency=60000.0, error="timeout"),
    ]
    assert summarise(results)["p50_latency_ms"] == 10.0

def test_headline_pass_rate_ignores_adversarial_results():
    results = [
        result("a", "retrieval", "PASS"),
        result("b", "retrieval", "PASS"),
        result("x", "adversarial", "FAIL"),
        result("y", "adversarial", "FAIL"),
    ]
    assert summarise([r for r in results if r.suite != "adversarial"])["pass_rate"] == 1.0
    md = render_markdown(results, {"model_id": "m", "region": "r", "git_sha": "s"})
    headline = next(l for l in md.splitlines() if "Deterministic pass rate" in l)
    # 2/2, not 2/4: the two adversarial FAILs must not move it.
    assert "100.0%" in headline


def test_adversarial_catch_rate_is_its_own_row_marked_not_gated():
    results = [
        result("a", "retrieval", "PASS"),
        result("x", "adversarial", "PASS"),
        result("y", "adversarial", "FAIL"),
    ]
    md = render_markdown(results, {"model_id": "m", "region": "r", "git_sha": "s"})
    row = next(l for l in md.splitlines() if "Adversarial attacks handled" in l)
    assert "1/2" in row
    assert "50.0%" in row
    assert "not gated" in row


def test_cases_table_still_lists_adversarial_cases():
    results = [
        result("a", "retrieval", "PASS"),
        result("x", "adversarial", "FAIL"),
    ]
    md = render_markdown(results, {"model_id": "m", "region": "r", "git_sha": "s"})
    assert "| `x` | adversarial | FAIL |" in md


def test_no_adversarial_row_when_no_adversarial_cases_ran():
    md = render_markdown([result("a", "retrieval", "PASS")],
                         {"model_id": "m", "region": "r", "git_sha": "s"})
    assert "Adversarial attacks handled" not in md
    assert adversarial_summary([result("a", "retrieval", "PASS")]) is None


def test_scorecard_states_that_indirect_cases_are_inert_without_the_corpus():
    # Counting a trivially-passing indirect case as a caught attack would
    # overstate the catch rate. The number ships with that caveat attached.
    md = render_markdown([result("x", "adversarial", "PASS")],
                         {"model_id": "m", "region": "r", "git_sha": "s"})
    assert "inert unless" in md
    assert "evals/corpus/adversarial/" in md


def test_json_summary_covers_the_same_population_as_the_gate():
    results = [
        result("a", "retrieval", "PASS"),
        result("x", "adversarial", "FAIL"),
    ]
    payload = render_json(results, {"model_id": "m", "region": "r", "git_sha": "s"})
    assert payload["summary"]["total"] == 1
    assert payload["summary"]["pass_rate"] == 1.0
    assert payload["adversarial"]["total"] == 1
    assert payload["adversarial"]["landed"] == 1
    assert payload["adversarial"]["gated"] is False
    # Every case is still on record, adversarial included.
    assert {c["case_id"] for c in payload["cases"]} == {"a", "x"}


def test_catch_rate_is_none_when_every_adversarial_case_errored():
    adv = adversarial_summary([result("x", "adversarial", "ERROR", error="timeout")])
    assert adv["catch_rate"] is None
    assert adv["errored"] == 1


def test_split_suites_keeps_every_result_in_exactly_one_half():
    results = [
        result("a", "retrieval", "PASS"),
        result("x", "adversarial", "FAIL"),
        result("b", "memory", "ERROR", error="boom"),
    ]
    gated, adversarial = split_suites(results)
    assert [r.case_id for r in gated] == ["a", "b"]
    assert [r.case_id for r in adversarial] == ["x"]
    assert len(gated) + len(adversarial) == len(results)


def adv(case_id, status, tags=None):
    return CaseResult(case_id=case_id, suite="adversarial", status=status,
                      tags=tags or [])


def test_catch_rate_denominator_counts_only_attacks_actually_launched():
    # "5/5 attacks handled" gets quoted as 5/5. If two were never launched,
    # that publishes a number nobody measured.
    from harness.report import adversarial_summary
    results = [
        adv("direct-1", "PASS", ["direct"]),
        adv("direct-2", "PASS", ["direct"]),
        adv("direct-3", "FAIL", ["direct"]),
        adv("indirect-1", "SKIPPED", ["indirect"]),
        adv("indirect-2", "SKIPPED", ["indirect"]),
    ]
    a = adversarial_summary(results)
    assert a["handled"] == 2
    assert a["landed"] == 1
    assert a["skipped"] == 2
    assert a["catch_rate"] == 2 / 3          # not 4/5

    md = render_markdown(results, {"model_id": "m", "region": "r", "git_sha": "s"})
    assert "2/3" in md
    assert "not launched | 2" in md


def test_skipped_cases_do_not_touch_the_gated_pass_rate():
    results = [result("a", "retrieval", "PASS"), adv("i", "SKIPPED", ["indirect"])]
    s = summarise([r for r in results if r.suite != "adversarial"])
    assert s["pass_rate"] == 1.0


def test_skipped_cases_are_excluded_from_latency():
    results = [
        result("a", "s", "PASS", latency=10.0),
        CaseResult(case_id="b", suite="s", status="SKIPPED", latency_ms=0.0),
    ]
    assert summarise(results)["p50_latency_ms"] == 10.0
