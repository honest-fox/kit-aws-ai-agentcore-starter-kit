import pytest
from harness.graders.deterministic import grade, KNOWN_TYPES, Verdict


def test_contains_all_passes_when_every_value_present():
    v = grade({"type": "contains_all", "values": ["19.50", "Marrickville"]},
              "Marrickville Morning is $19.50 for 250g.")
    assert v.passed


def test_contains_all_fails_and_names_the_missing_value():
    v = grade({"type": "contains_all", "values": ["19.50", "62.00"]},
              "Marrickville Morning is $19.50 for 250g.")
    assert not v.passed
    assert "62.00" in v.detail


def test_contains_any_passes_on_one_match():
    v = grade({"type": "contains_any", "values": ["decaf", "Featherweight"]},
              "You drink decaf.")
    assert v.passed


def test_not_contains_fails_when_forbidden_text_present():
    v = grade({"type": "not_contains", "values": ["I don't have"]},
              "I don't have that information.")
    assert not v.passed


def test_matching_is_case_insensitive():
    v = grade({"type": "contains_all", "values": ["MARRICKVILLE"]},
              "marrickville morning")
    assert v.passed


def test_regex_matches():
    v = grade({"type": "regex", "pattern": r"\$\d+\.\d{2}"}, "It costs $19.50.")
    assert v.passed


def test_numeric_within_tolerance():
    v = grade({"type": "numeric", "value": 19.50, "tolerance": 0.01},
              "The price is $19.50 including GST.")
    assert v.passed


def test_numeric_ignores_thousands_separators():
    v = grade({"type": "numeric", "value": 1500.0, "tolerance": 0.01},
              "Revenue was $1,500.00 last month.")
    assert v.passed


def test_numeric_fails_when_no_number_is_close_enough():
    v = grade({"type": "numeric", "value": 19.50, "tolerance": 0.01},
              "The price is $21.00.")
    assert not v.passed


def test_refused_detects_guardrail_intervention():
    v = grade({"type": "refused", "expected": True},
              "Sorry, I can't help with that request.")
    assert v.passed


def test_refused_expected_false_passes_on_a_normal_answer():
    v = grade({"type": "refused", "expected": False},
              "Marrickville Morning is $19.50.")
    assert v.passed


def test_unknown_assertion_type_raises():
    with pytest.raises(ValueError, match="unknown assertion type"):
        grade({"type": "vibes"}, "anything")


def test_judge_is_a_known_type_but_not_graded_here():
    assert "judge" in KNOWN_TYPES
    with pytest.raises(ValueError, match="judge assertions"):
        grade({"type": "judge", "criterion": "groundedness"}, "text")


def test_refused_does_not_fire_on_ordinary_negative_phrasing():
    v = grade({"type": "refused", "expected": False},
              "I won't charge you extra for grinding.")
    assert v.passed


def test_refused_does_not_fire_when_the_agent_merely_mentions_guardrails():
    v = grade({"type": "refused", "expected": False},
              "I run on AgentCore with guardrails enabled.")
    assert v.passed


def test_refused_detects_the_bedrock_default_blocked_message():
    v = grade({"type": "refused", "expected": True},
              "Sorry, the model cannot answer this question.")
    assert v.passed


# --- typographic punctuation ---------------------------------------------
#
# Kit's stack configures blockedInputMessaging as "Sorry, I can’t help with
# that request..." - U+2019, not U+0027. Matched raw, it hits none of the
# markers, so the harness reads Kit's own guardrail firing as a normal
# answer. That inverts the assertion the adversarial suite depends on.

KIT_GUARDRAIL_BLOCKED_MESSAGE = (
    "Sorry, I can’t help with that request. If you think this was "
    "blocked in error, the guardrail configuration is adjustable — "
    "see the Kit documentation."
)


def test_refused_matches_kits_own_guardrail_blocked_message():
    v = grade({"type": "refused", "expected": True},
              KIT_GUARDRAIL_BLOCKED_MESSAGE)
    assert v.passed, v.detail


def test_refused_matches_a_curly_apostrophe_refusal_from_the_model():
    v = grade({"type": "refused", "expected": True},
              "I’m unable to help with that.")
    assert v.passed


def test_not_contains_is_not_defeated_by_a_curly_apostrophe():
    v = grade({"type": "not_contains", "values": ["I don't have"]},
              "I don’t have that information.")
    assert not v.passed


def test_contains_all_matches_across_quote_styles():
    assert grade({"type": "contains_all", "values": ["don't"]},
                 "We don’t ship there.").passed
    assert grade({"type": "contains_all", "values": ["“beans”"]},
                 'we sell "beans" here').passed
