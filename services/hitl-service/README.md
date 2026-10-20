# hitl-service (stub folder)

Status: stub folder, 2026-10-16. There is no hitl-service. Reviews, Cases and work items move into the planned
`ops_hitl` package, which agents-service hosts; today the Reviews router and approval-token minting live in
`services/agents-service`.

`ops_hitl` will hold Cases, queues, SLA display, the Reviews queue, decisions and the approval tokens people issue
(ADR-0005). It records SLA outcomes the runner decides from the pinned plan, and resumes runs after a decision.

Design: `docs/architecture/service-map.md`; `.codeloop/wiki/concepts/reviews-and-cases.md`. Specs:
`.codeloop/wiki/concepts/agent-builder.md`, `.codeloop/wiki/concepts/assurance-evals-and-release.md`.
