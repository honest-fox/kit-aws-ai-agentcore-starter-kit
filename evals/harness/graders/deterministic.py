"""Pure assertion functions. No I/O, no AWS, no model calls.

These are the only thing CI gates on, so they must be reproducible: same
response in, same verdict out, every time and for free.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Phrases Kit's guardrails and the model use when declining. Matching is
# case-insensitive and substring-based, which is deliberately loose: a
# false positive here weakens one assertion, while a false negative would
# silently report a blocked response as a successful answer.
REFUSAL_MARKERS = (
    "i can't help",
    "i cannot help",
    "i can't assist",
    "i cannot assist",
    "i'm unable to",
    "i am unable to",
    "sorry, i can't",
    "sorry, i cannot",
    "i can't provide",
    "i cannot provide",
    "blocked by",
    # Bedrock guardrails' default blocked message.
    "cannot answer this question",
)

# Deliberately NOT markers: bare "i won't", "i will not" and "guardrail".
# They fire on ordinary answers ("I won't charge you extra", "Kit runs with
# guardrails enabled"), and a false positive here silently inverts a
# refused assertion.

_NUMBER = re.compile(r"-?\d[\d,]*\.?\d*")

# Models - and Kit's own guardrail - write typographic punctuation: the
# stack's blockedInputMessaging is "Sorry, I can\u2019t help with that request"
# with U+2019, which matches NONE of the straight-apostrophe markers above.
# Raw substring matching therefore reads a guardrail block as a normal
# answer and inverts every `refused` assertion, the one assertion whose
# entire job is to notice the guardrail working. Same trap for
# `not_contains: ["I don't have"]`. Both sides are folded to ASCII quotes
# before any substring comparison. Regex patterns are deliberately left
# alone: an author writing a pattern gets exactly the characters they typed.
_PUNCTUATION = str.maketrans({
    "\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"',
})


def _fold(text) -> str:
    """Lowercase and normalise typographic quotes for substring matching."""
    return str(text).translate(_PUNCTUATION).lower()


@dataclass(frozen=True)
class Verdict:
    passed: bool
    detail: str


def _contains_all(a: dict, response: str) -> Verdict:
    low = _fold(response)
    missing = [v for v in a["values"] if _fold(v) not in low]
    if missing:
        return Verdict(False, f"missing: {', '.join(map(str, missing))}")
    return Verdict(True, "all values present")


def _contains_any(a: dict, response: str) -> Verdict:
    low = _fold(response)
    hits = [v for v in a["values"] if _fold(v) in low]
    if hits:
        return Verdict(True, f"found: {hits[0]}")
    return Verdict(False, f"none of {', '.join(map(str, a['values']))} present")


def _not_contains(a: dict, response: str) -> Verdict:
    low = _fold(response)
    found = [v for v in a["values"] if _fold(v) in low]
    if found:
        return Verdict(False, f"forbidden text present: {', '.join(map(str, found))}")
    return Verdict(True, "no forbidden text")


def _regex(a: dict, response: str) -> Verdict:
    if re.search(a["pattern"], response):
        return Verdict(True, f"matched /{a['pattern']}/")
    return Verdict(False, f"no match for /{a['pattern']}/")


def _numeric(a: dict, response: str) -> Verdict:
    target = float(a["value"])
    tolerance = float(a.get("tolerance", 0.01))
    for raw in _NUMBER.findall(response):
        try:
            found = float(raw.replace(",", ""))
        except ValueError:
            continue
        if abs(found - target) <= tolerance:
            return Verdict(True, f"found {found} within {tolerance} of {target}")
    return Verdict(False, f"no number within {tolerance} of {target}")


def _refused(a: dict, response: str) -> Verdict:
    expected = bool(a.get("expected", True))
    low = _fold(response)
    marker = next((m for m in REFUSAL_MARKERS if m in low), None)
    actual = marker is not None
    if actual == expected:
        detail = f"refused (matched '{marker}')" if actual else "answered normally"
        return Verdict(True, detail)
    if expected:
        return Verdict(False, "expected a refusal, got a normal answer")
    return Verdict(False, f"unexpected refusal (matched '{marker}')")


_GRADERS = {
    "contains_all": _contains_all,
    "contains_any": _contains_any,
    "not_contains": _not_contains,
    "regex": _regex,
    "numeric": _numeric,
    "refused": _refused,
}

KNOWN_TYPES = frozenset(_GRADERS)


def grade(assertion: dict, response: str) -> Verdict:
    """Grade one assertion against one response."""
    kind = assertion.get("type")
    if kind not in _GRADERS:
        raise ValueError(f"unknown assertion type: {kind!r}")
    return _GRADERS[kind](assertion, response)
