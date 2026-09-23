# Kit evaluation harness

Scores a deployed Kit agent against a golden set built on the sample
Kookaburra Coffee corpus.

    ./scripts/eval.sh              # full suite against your deployed stack
    ./scripts/eval.sh --validate   # offline: check datasets, no AWS needed
    ./scripts/eval.sh --no-judge   # deterministic assertions only

Two grading tiers. Deterministic assertions are free, instant and
reproducible, and they are the only thing CI gates on. The LLM judge adds a
quality score that is reported as a trend, never gated — an LLM-judged gate
is non-reproducible and teaches you to ignore it.

See `docs/evaluation.md` for the full guide.
