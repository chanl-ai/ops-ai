# HITL service (human in the loop)

Status: not started. The Reviews router and approval-token minting live in `services/agents-service` until this
service is built.

Cases, queues, SLA display, the Reviews queue, decisions and the approval tokens people issue (ADR-0005). It records
SLA outcomes the agents service decides from the pinned plan, and resumes runs after a decision.

Design: `docs/architecture/service-map.md` ("Contracts that cross services"). Specs: `docs/specs/agent-builder.md`,
`docs/specs/evals-and-release.md`.
