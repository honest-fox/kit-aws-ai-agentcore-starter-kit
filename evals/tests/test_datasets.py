import pytest
from harness.datasets import Case, Turn, load_suite, validate


def write(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(body)
    return p


def test_single_turn_case_normalises_to_one_turn(tmp_path):
    p = write(tmp_path, "retrieval.yaml", """
- id: price-check
  prompt: "How much?"
  grade:
    - { type: contains_all, values: ["19.50"] }
""")
    cases = load_suite(p)
    assert len(cases) == 1
    assert cases[0].id == "price-check"
    assert cases[0].suite == "retrieval"
    assert len(cases[0].turns) == 1
    assert cases[0].turns[0].prompt == "How much?"
    assert cases[0].turns[0].new_session is False


def test_multi_turn_case_preserves_new_session_flag(tmp_path):
    p = write(tmp_path, "memory.yaml", """
- id: recall
  settle_seconds: 90
  turns:
    - prompt: "Remember I drink decaf."
    - prompt: "What do I drink?"
      new_session: true
      grade:
        - { type: contains_any, values: ["decaf"] }
""")
    cases = load_suite(p)
    assert cases[0].settle_seconds == 90
    assert cases[0].turns[0].new_session is False
    assert cases[0].turns[0].grade == []
    assert cases[0].turns[1].new_session is True


def test_validate_rejects_duplicate_ids():
    cases = [
        Case(id="dup", suite="a", turns=[Turn("x", False, [])], tags=[], settle_seconds=0),
        Case(id="dup", suite="b", turns=[Turn("y", False, [])], tags=[], settle_seconds=0),
    ]
    errors = validate(cases)
    assert any("duplicate case id: dup" in e for e in errors)


def test_validate_rejects_unknown_assertion_type():
    cases = [Case(id="c", suite="a", tags=[], settle_seconds=0,
                  turns=[Turn("x", False, [{"type": "vibes"}])])]
    errors = validate(cases)
    assert any("unknown assertion type" in e for e in errors)


def test_validate_rejects_a_case_with_no_assertions_anywhere():
    cases = [Case(id="c", suite="a", tags=[], settle_seconds=0,
                  turns=[Turn("x", False, [])])]
    errors = validate(cases)
    assert any("no assertions" in e for e in errors)


def test_validate_rejects_an_assertion_missing_its_required_key():
    cases = [Case(id="c", suite="a", tags=[], settle_seconds=0,
                  turns=[Turn("x", False, [{"type": "contains_all"}])])]
    errors = validate(cases)
    assert any("needs 'values'" in e for e in errors)


def test_validate_rejects_an_invalid_regex_pattern():
    cases = [Case(id="c", suite="a", tags=[], settle_seconds=0,
                  turns=[Turn("x", False, [{"type": "regex", "pattern": "([unclosed"}])])]
    errors = validate(cases)
    assert any("invalid regex" in e for e in errors)


def test_validate_accepts_a_well_formed_case():
    cases = [Case(id="c", suite="a", tags=["x"], settle_seconds=0,
                  turns=[Turn("x", False, [{"type": "contains_all", "values": ["a"]}])])]
    assert validate(cases) == []


def test_load_suite_rejects_a_case_without_an_id(tmp_path):
    p = write(tmp_path, "bad.yaml", """
- prompt: "no id here"
  grade:
    - { type: contains_all, values: ["a"] }
""")
    with pytest.raises(ValueError, match="missing 'id'"):
        load_suite(p)


# Malformed datasets must name the file and case, not raise a bare KeyError.
# Editing these YAML files is the main way anyone extends the eval suite.

def test_case_with_neither_prompt_nor_turns_names_the_case(tmp_path):
    p = write(tmp_path, "bad.yaml", """
- id: empty-case
  tags: [x]
""")
    with pytest.raises(ValueError, match="empty-case: case needs either 'prompt' or 'turns'"):
        load_suite(p)


def test_turn_missing_prompt_names_the_turn(tmp_path):
    p = write(tmp_path, "bad.yaml", """
- id: bad-turn
  turns:
    - prompt: "fine"
    - new_session: true
""")
    with pytest.raises(ValueError, match=r"bad-turn turn 1: turn missing 'prompt'"):
        load_suite(p)


def test_top_level_mapping_is_rejected_with_a_readable_message(tmp_path):
    p = write(tmp_path, "bad.yaml", """
id: not-a-list
prompt: "oops"
""")
    with pytest.raises(ValueError, match="must contain a list of cases"):
        load_suite(p)


def test_grade_written_as_a_mapping_is_rejected(tmp_path):
    p = write(tmp_path, "bad.yaml", """
- id: bad-grade
  prompt: "hi"
  grade:
    type: contains_all
    values: ["a"]
""")
    with pytest.raises(ValueError, match="'grade' must be a list"):
        load_suite(p)


def test_non_numeric_settle_seconds_names_the_case(tmp_path):
    p = write(tmp_path, "bad.yaml", """
- id: bad-settle
  settle_seconds: soon
  prompt: "hi"
  grade:
    - { type: contains_all, values: ["a"] }
""")
    with pytest.raises(ValueError, match="bad-settle: 'settle_seconds' must be a whole number"):
        load_suite(p)


def test_validate_rejects_a_judge_only_case():
    # all([]) is True, so a case with no deterministic assertions is marked
    # PASS unconditionally and silently inflates the CI gate.
    cases = [Case(id="judge-only", suite="a", tags=[], settle_seconds=0,
                  turns=[Turn("x", False,
                              [{"type": "judge", "criterion": "groundedness"}])])]
    errors = validate(cases)
    assert any("no deterministic assertions" in e for e in errors)


def test_validate_rejects_an_unknown_judge_criterion():
    # A typo passes CI clean, then aborts the live run partway through -
    # after the invocations have already been paid for.
    cases = [Case(id="typo", suite="a", tags=[], settle_seconds=0,
                  turns=[Turn("x", False, [
                      {"type": "contains_all", "values": ["a"]},
                      {"type": "judge", "criterion": "groundedess"}])])]
    errors = validate(cases)
    assert any("unknown judge criterion" in e for e in errors)


def test_the_shipped_golden_set_satisfies_both_rules():
    from harness.datasets import load_all
    from pathlib import Path
    cases = load_all(Path(__file__).resolve().parents[1] / "datasets")
    assert validate(cases) == []
