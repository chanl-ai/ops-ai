# Shared libraries

Status: not started. No code exists yet.

| Item | Detail |
|---|---|
| Purpose | Code every service imports: Python models generated from `packages/contracts`, validated settings loading, structured logging and OpenTelemetry setup, run-context and identity types, and clients for the two gateways and the control plane. |
| Owns | None. |
| Depends on | `packages/contracts`. |
| Specs | `docs/backend/overview.md` sections 3 and 6 |

The service map, standards and security boundaries that apply to every service are in
`docs/backend/overview.md`.
