"""Render results to markdown and JSON. Pure — no I/O beyond returning text.

ERROR is kept strictly separate from FAIL everywhere. A case that could not
be invoked says nothing about agent quality, and letting infrastructure
flakiness move the pass rate would make the gate untrustworthy.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

from .graders.deterministic import Verdict


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    suite: str
    status: str  # PASS | FAIL | ERROR
    assertions: list[Verdict] = field(default_factory=list)
    judge_scores: dict[str, float] = field(default_factory=dict)
    latency_ms: float = 0.0
    error: str | None = None
    judge_attempted: int = 0
    judge_scored: int = 0


# The one suite whose results are reported rather than gated. Kept here,
# next to the summariser, so the scorecard and cli.main() split on the same
# definition: a scorecard whose headline differed from the number CI
# enforced would be worse than no scorecard.
ADVERSARIAL_SUITE = "adversarial"


def split_suites(results: list[CaseResult]) -> tuple[list[CaseResult], list[CaseResult]]:
    """Split into (gated, adversarial). Order is preserved in both halves."""
    gated = [r for r in results if r.suite != ADVERSARIAL_SUITE]
    adversarial = [r for r in results if r.suite == ADVERSARIAL_SUITE]
    return gated, adversarial


def adversarial_summary(results: list[CaseResult]) -> dict | None:
    """Catch rate over adversarial cases only, or None if none ran.

    Named a catch *rate*, never a pass rate, because it measures something
    different: how many attacks the agent handled, on a suite where a
    regression is a finding to publish rather than a build to break.
    """
    adversarial = [r for r in results if r.suite == ADVERSARIAL_SUITE]
    if not adversarial:
        return None
    handled = sum(1 for r in adversarial if r.status == "PASS")
    landed = sum(1 for r in adversarial if r.status == "FAIL")
    errored = sum(1 for r in adversarial if r.status == "ERROR")
    graded = handled + landed
    return {
        "total": len(adversarial),
        "handled": handled,
        "landed": landed,
        "errored": errored,
        "catch_rate": (handled / graded) if graded else None,
        "gated": False,
    }


def _percentile(values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile.

    With few samples this correctly collapses toward the maximum instead of
    pretending to resolution the sample size cannot support: with 17 cases,
    the 95th percentile genuinely is the slowest one.
    """
    if not values:
        return None
    ordered = sorted(values)
    rank = math.ceil(pct * len(ordered))
    return ordered[min(max(rank - 1, 0), len(ordered) - 1)]


def _cell(text) -> str:
    """Escape pipes so a detail cannot break the markdown table.

    Reachable today: a regex assertion's pattern is interpolated into its
    failure detail, and the grinder-warranty pattern contains an
    alternation. The table would break only on failing rows - exactly the
    rows a reader opens the scorecard to read.
    """
    return str(text).replace("|", "\\|")


def summarise(results: list[CaseResult]) -> dict:
    passed = sum(1 for r in results if r.status == "PASS")
    failed = sum(1 for r in results if r.status == "FAIL")
    errored = sum(1 for r in results if r.status == "ERROR")
    graded = passed + failed
    latencies = [r.latency_ms for r in results if r.status != "ERROR"]
    return {
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "errored": errored,
        "pass_rate": (passed / graded) if graded else None,
        "p50_latency_ms": _percentile(latencies, 0.50),
        "p95_latency_ms": _percentile(latencies, 0.95),
    }


def _fmt_rate(rate: float | None) -> str:
    return "n/a" if rate is None else f"{rate * 100:.1f}%"


def _fmt_ms(ms: float | None) -> str:
    return "n/a" if ms is None else f"{ms:.0f}ms"


def _fmt_coverage(meta: dict) -> str:
    """How many judge assertions actually produced a score.

    A judge that silently returns nothing - a fence-wrapping model, a wrong
    envelope path, a throttle - renders identically to one that was never
    run: a column of dashes, CI green. Stating coverage explicitly means a
    reader can tell "scored 3.9" from "scored nothing".
    """
    attempted = meta.get("judge_attempted")
    if not attempted:
        return "not run"
    scored = meta.get("judge_scored", 0)
    note = "" if scored == attempted else "  **judge degraded**"
    return f"{scored}/{attempted} scored{note}"


def render_markdown(results: list[CaseResult], meta: dict) -> str:
    # Every row in the Summary block describes the gated population -
    # the same population cli.gate() scores and render_json() reports.
    # Adversarial cases get their own row and stay out of all of them;
    # their latency is still visible per case in the table below.
    gated, _ = split_suites(results)
    s = summarise(gated)
    adv = adversarial_summary(results)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Kit evaluation scorecard",
        "",
        f"- **Run:** {now}",
        f"- **Agent model:** `{meta.get('model_id', 'unknown')}`",
        f"- **Judge model:** `{meta.get('judge_model_id', 'not run')}`",
        f"- **Region:** `{meta.get('region', 'unknown')}`",
        f"- **Commit:** `{meta.get('git_sha', 'unknown')}`",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Deterministic pass rate (gated suites) | **{_fmt_rate(s['pass_rate'])}** |",
        f"| Passed | {s['passed']} |",
        f"| Failed | {s['failed']} |",
        f"| Errored (not counted in pass rate) | {s['errored']} |",
    ]
    if adv:
        lines += [
            f"| Adversarial attacks handled (reported, **not gated**) | "
            f"{adv['handled']}/{adv['total']} ({_fmt_rate(adv['catch_rate'])}) |",
        ]
    lines += [
        f"| Latency p50 (gated suites) | {_fmt_ms(s['p50_latency_ms'])} |",
        f"| Latency p95 (gated suites) | {_fmt_ms(s['p95_latency_ms'])} |",
        f"| Judge coverage | {_fmt_coverage(meta)} |",
        "",
        "## Cases",
        "",
        "| Case | Suite | Status | Latency | Judge | Detail |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in sorted(results, key=lambda x: (x.suite, x.case_id)):
        judge = ", ".join(f"{k} {v}" for k, v in r.judge_scores.items()) or "—"
        if r.status == "ERROR":
            detail = r.error or "unknown error"
        else:
            detail = "; ".join(v.detail for v in r.assertions if not v.passed) or "—"
        lines.append(
            f"| `{r.case_id}` | {r.suite} | {r.status} | "
            f"{_fmt_ms(r.latency_ms)} | {_cell(judge)} | {_cell(detail)} |"
        )
    lines.append("")
    lines.append(
        "> Judge scores and adversarial catch rates are reported, never gated. "
        "Only the deterministic pass rate gates CI."
    )
    if adv:
        lines.append("")
        lines.append(
            "> The adversarial catch rate counts every adversarial case that "
            "was not observably compromised. Cases tagged `indirect` are "
            "inert unless `evals/corpus/adversarial/` was deliberately "
            "loaded into the knowledge base — on a default deployment they "
            "pass because the payload was never retrievable, not because it "
            "was resisted. Read this number as a floor, and only alongside "
            "the case list."
        )
    lines.append("")
    return "\n".join(lines)


def render_json(results: list[CaseResult], meta: dict) -> dict:
    # "summary" is the gated population, matching both the markdown headline
    # and cli.gate(). Anything consuming this file to plot "the pass rate"
    # therefore plots the number CI enforced.
    gated, _ = split_suites(results)
    return {
        "meta": {**meta, "generated_at": datetime.now(timezone.utc).isoformat()},
        "summary": summarise(gated),
        "adversarial": adversarial_summary(results),
        # asdict() recurses into the nested Verdict list already.
        "cases": [asdict(r) for r in results],
    }
