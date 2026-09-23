from harness.cli import build_parser, gate
from harness.report import CaseResult


def r(status, suite="s"):
    return CaseResult(case_id="c", suite=suite, status=status)


def test_validate_flag_parses():
    assert build_parser().parse_args(["--validate"]).validate is True


def test_defaults_enable_the_judge():
    assert build_parser().parse_args([]).no_judge is False


def test_suite_and_case_filters_parse():
    args = build_parser().parse_args(["--suite", "retrieval", "--case", "abc"])
    assert args.suite == "retrieval"
    assert args.case == "abc"


def test_gate_passes_when_rate_meets_threshold():
    assert gate([r("PASS"), r("PASS"), r("FAIL")], threshold=0.6) == 0


def test_gate_fails_when_rate_is_below_threshold():
    assert gate([r("PASS"), r("FAIL")], threshold=0.9) == 1


def test_gate_fails_loudly_when_every_case_errored():
    assert gate([r("ERROR"), r("ERROR")], threshold=0.9) == 1


# --- exit codes -----------------------------------------------------------
#
# The contract in the module docstring is 0 pass / 1 gate failed / 2
# configuration or validation error. A path that violates it is worse than
# a crash: CI reads exit 0 as "the agent is fine".

VALID_CASE = """
- id: only-case
  suite: s
  prompt: hello
  grade:
    - type: contains_all
      values: [hi]
"""


def _datasets(tmp_path, monkeypatch, text):
    from harness import cli
    (tmp_path / "datasets").mkdir()
    (tmp_path / "datasets" / "s.yaml").write_text(text)
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    return cli


def test_structurally_broken_dataset_exits_2_not_1(tmp_path, monkeypatch):
    # A mapping where a list belongs raises out of load_all before
    # validate() sees it. A traceback and exit 1 would read as "quality gate
    # failed" - blaming the agent for the author's YAML.
    cli = _datasets(tmp_path, monkeypatch, "not: a list\n")
    assert cli.main(["--validate"]) == 2


def test_filter_matching_nothing_exits_2_when_validating(tmp_path, monkeypatch):
    # "OK: 0 cases valid" on exit 0 is the worst possible answer: a typo in
    # a CI suite name checks nothing and reports success.
    cli = _datasets(tmp_path, monkeypatch, VALID_CASE)
    assert cli.main(["--suite", "typo", "--validate"]) == 2


def test_filter_matching_nothing_exits_2_when_dry_running(tmp_path, monkeypatch):
    cli = _datasets(tmp_path, monkeypatch, VALID_CASE)
    assert cli.main(["--case", "nonexistent", "--dry-run"]) == 2


def test_validate_still_passes_when_cases_match(tmp_path, monkeypatch):
    cli = _datasets(tmp_path, monkeypatch, VALID_CASE)
    assert cli.main(["--validate"]) == 0
    assert cli.main(["--suite", "s", "--dry-run"]) == 0
