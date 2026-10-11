# Kit evaluation harness

Scores a deployed Kit agent against a golden set built on the sample
Kookaburra Coffee corpus.

    ./scripts/eval.sh              # full suite against your deployed stack
    ./scripts/eval.sh --validate   # offline: check datasets, no AWS needed
    ./scripts/eval.sh --dry-run    # list the cases that would run

Deterministic assertions only. They are free, instant and reproducible, and
they are the only thing CI gates on — an LLM-judged gate is
non-reproducible and teaches you to ignore it. Judged quality is scored by
the managed evaluators declared in `agentcore/agentcore.json`, not here.

See `docs/evaluation.md` for the full guide.
