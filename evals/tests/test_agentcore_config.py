"""Pins agentcore.json's declarative evaluators to the offline harness.

The online layer scores real user traffic with the same words the offline
judge uses. `agentcore validate` (CLI 0.28.1) checks names and cross-resource
references but not instruction text or placeholders, so everything the
service requires of an instruction string is asserted here instead.
"""
import json
import re
from pathlib import Path

import pytest

from harness.graders.judge import UNTRUSTED_CLAUSE

CONFIG = Path(__file__).resolve().parents[2] / "agentcore" / "agentcore.json"

NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,47}$")

# Required and optional placeholders per evaluator level, per the service.
PLACEHOLDERS = {
    "SESSION": ({"context"}, {"available_tools"}),
    "TRACE": ({"context"}, {"assistant_turn", "available_tools"}),
    "TOOL_CALL": ({"context"}, {"tool_turn", "available_tools"}),
}


def load():
    return json.loads(CONFIG.read_text())


def evaluators():
    return load()["evaluators"]


def judges():
    return [(e["name"], e["level"], e["config"]["llmAsAJudge"])
            for e in evaluators() if "llmAsAJudge" in e["config"]]


def test_evaluators_are_present():
    assert evaluators(), "agentcore.json declares no evaluators"


@pytest.mark.parametrize("name,level,cfg", judges(), ids=[j[0] for j in judges()])
def test_instructions_carry_the_untrusted_clause(name, level, cfg):
    """The drift guard.

    The clause exists because this text ships to the online layer, where the
    inputs are real user traffic. An edit to judge.py must not silently leave
    the deployed evaluators unprotected against injected instructions.
    """
    assert UNTRUSTED_CLAUSE in cfg["instructions"], (
        f"evaluator {name} is missing the untrusted-data clause from judge.py")


@pytest.mark.parametrize("name,level,cfg", judges(), ids=[j[0] for j in judges()])
def test_instructions_use_only_placeholders_valid_for_the_level(name, level, cfg):
    required, optional = PLACEHOLDERS[level]
    found = set(re.findall(r"\{(\w+)\}", cfg["instructions"]))
    assert required <= found, (
        f"evaluator {name} ({level}) is missing required {required - found}")
    assert found <= required | optional, (
        f"evaluator {name} ({level}) uses placeholders invalid for its level: "
        f"{found - (required | optional)}")


@pytest.mark.parametrize("name,level,cfg", judges(), ids=[j[0] for j in judges()])
def test_model_is_geography_scoped(name, level, cfg):
    """au.* keeps inference in Australia; global.* does not."""
    assert not cfg["model"].startswith("global."), (
        f"evaluator {name} uses a global inference profile: {cfg['model']}")


def test_evaluator_names_are_cloudformation_safe():
    for e in evaluators():
        assert NAME_RE.match(e["name"]), f"invalid evaluator name: {e['name']}"


def test_levels_are_known():
    for e in evaluators():
        assert e["level"] in PLACEHOLDERS, f"{e['name']}: bad level {e['level']}"


def test_online_evals_never_enable_themselves_on_create():
    """Deploying Kit must never start incurring evaluation spend."""
    configs = load()["onlineEvalConfigs"]
    assert configs, "agentcore.json declares no online eval configs"
    for c in configs:
        assert c.get("enableOnCreate") is False, (
            f"online eval {c['name']} would start billing on deploy")


def test_online_eval_sampling_rate_is_a_sane_percentage():
    for c in load()["onlineEvalConfigs"]:
        rate = c["samplingRate"]
        assert 0.01 <= rate <= 100, f"{c['name']}: samplingRate out of range"
        assert rate <= 25, f"{c['name']}: samplingRate {rate}% is a cost risk"


def test_online_evals_reference_declared_evaluators():
    declared = {e["name"] for e in evaluators()}
    for c in load()["onlineEvalConfigs"]:
        for ref in c.get("evaluators", []):
            assert ref in declared, f"{c['name']} references unknown {ref}"


def test_groundedness_instructions_are_verbatim_from_the_harness():
    """judge.py promises the offline and online layers score against the
    same words. Pinning only the untrusted clause would not catch a
    reworded criterion body, which is the more likely drift."""
    import json
    from pathlib import Path
    from harness.graders.judge import CRITERIA, UNTRUSTED_CLAUSE

    config = json.loads(
        (Path(__file__).resolve().parents[2] / "agentcore" / "agentcore.json").read_text())
    deployed = next(e for e in config["evaluators"] if e["name"] == "KitGroundedness")
    expected = (CRITERIA["groundedness"]["instructions"] + UNTRUSTED_CLAUSE
                + " Context: {context}. Response to evaluate: {assistant_turn}")
    assert deployed["config"]["llmAsAJudge"]["instructions"] == expected
