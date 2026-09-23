"""Render results to markdown and JSON. Pure — no I/O beyond returning text.

ERROR is kept strictly separate from FAIL everywhere. A case that could not
be invoked says nothing about agent quality, and letting infrastructure
flakiness move the pass rate would make the gate untrustworthy.
"""
from __future__ import annotations

import statistics
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
        "p50_latency_ms": statistics.median(latencies) if latencies else None,
        "p95_latency_ms": (
            sorted(latencies)[int(len(latencies) * 0.95)] if len(latencies) >= 20
            else (max(latencies) if latencies else None)
        ),
    }


def _fmt_rate(rate: float | None) -> str:
    return "n/a" if rate is None else f"{rate * 100:.1f}%"


def _fmt_ms(ms: float | None) -> str:
    return "n/a" if ms is None else f"{ms:.0f}ms"


def render_markdown(results: list[CaseResult], meta: dict) -> str:
    s = summarise(results)
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
        f"| Deterministic pass rate | **{_fmt_rate(s['pass_rate'])}** |",
        f"| Passed | {s['passed']} |",
        f"| Failed | {s['failed']} |",
        f"| Errored (not counted in pass rate) | {s['errored']} |",
        f"| Latency p50 | {_fmt_ms(s['p50_latency_ms'])} |",
        f"| Latency p95 | {_fmt_ms(s['p95_latency_ms'])} |",
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
            f"{_fmt_ms(r.latency_ms)} | {judge} | {detail} |"
        )
    lines.append("")
    lines.append(
        "> Judge scores and adversarial catch rates are reported, never gated. "
        "Only the deterministic pass rate gates CI."
    )
    lines.append("")
    return "\n".join(lines)


def render_json(results: list[CaseResult], meta: dict) -> dict:
    return {
        "meta": {**meta, "generated_at": datetime.now(timezone.utc).isoformat()},
        "summary": summarise(results),
        "cases": [
            {**asdict(r), "assertions": [asdict(v) for v in r.assertions]}
            for r in results
        ],
    }
