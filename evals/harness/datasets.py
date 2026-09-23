"""Load YAML golden-set cases into typed objects and validate them.

Validation runs offline in CI so a malformed dataset fails on a pull
request rather than halfway through a live run that costs money.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .graders.deterministic import KNOWN_TYPES

# Missing keys would otherwise raise KeyError mid-run, after the invocation
# has already been paid for. Catch them offline instead.
REQUIRED_KEYS = {
    "contains_all": ("values",),
    "contains_any": ("values",),
    "not_contains": ("values",),
    "regex": ("pattern",),
    "numeric": ("value",),
    "judge": ("criterion",),
}


@dataclass(frozen=True)
class Turn:
    prompt: str
    new_session: bool = False
    grade: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class Case:
    id: str
    suite: str
    turns: list[Turn]
    tags: list[str] = field(default_factory=list)
    settle_seconds: int = 0


def _parse_turn(raw: dict) -> Turn:
    return Turn(
        prompt=raw["prompt"],
        new_session=bool(raw.get("new_session", False)),
        grade=list(raw.get("grade", [])),
    )


def load_suite(path: Path | str) -> list[Case]:
    """Load one YAML file. The file stem becomes the suite name."""
    path = Path(path)
    raw_cases = yaml.safe_load(path.read_text()) or []
    cases: list[Case] = []
    for raw in raw_cases:
        if "id" not in raw:
            raise ValueError(f"{path.name}: case missing 'id'")
        if "turns" in raw:
            turns = [_parse_turn(t) for t in raw["turns"]]
        else:
            turns = [Turn(prompt=raw["prompt"], grade=list(raw.get("grade", [])))]
        cases.append(Case(
            id=raw["id"],
            suite=path.stem,
            turns=turns,
            tags=list(raw.get("tags", [])),
            settle_seconds=int(raw.get("settle_seconds", 0)),
        ))
    return cases


def load_all(directory: Path | str) -> list[Case]:
    """Load every .yaml file in a directory, sorted for stable ordering."""
    directory = Path(directory)
    cases: list[Case] = []
    for path in sorted(directory.glob("*.yaml")):
        cases.extend(load_suite(path))
    return cases


def validate(cases: list[Case]) -> list[str]:
    """Return a list of human-readable problems. Empty means valid."""
    errors: list[str] = []
    seen: set[str] = set()
    for case in cases:
        if case.id in seen:
            errors.append(f"duplicate case id: {case.id}")
        seen.add(case.id)

        assertion_count = 0
        for i, turn in enumerate(case.turns):
            assertion_count += len(turn.grade)
            for assertion in turn.grade:
                kind = assertion.get("type")
                if kind not in KNOWN_TYPES:
                    errors.append(
                        f"{case.id} turn {i}: unknown assertion type: {kind!r}")
                    continue
                for key in REQUIRED_KEYS.get(kind, ()):
                    if key not in assertion:
                        errors.append(
                            f"{case.id} turn {i}: {kind} assertion needs '{key}'")
                if kind == "regex" and "pattern" in assertion:
                    try:
                        re.compile(assertion["pattern"])
                    except re.error as exc:
                        errors.append(
                            f"{case.id} turn {i}: invalid regex: {exc}")
        if assertion_count == 0:
            errors.append(f"{case.id}: no assertions on any turn")
    return errors
