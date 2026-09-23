# Adversarial corpus — do not load into your production knowledge base

These documents contain deliberate prompt-injection payloads. They exist to
measure whether Kit's guardrails catch instructions smuggled in through
retrieved content — the exposure described in `docs/security.md`.

They are **not** part of `sample-data/` and are not ingested by a normal
`agentcore deploy`. Load them only into a throwaway knowledge base, and only
when you are running the adversarial suite deliberately. See
`docs/evaluation.md` for the opt-in procedure.
