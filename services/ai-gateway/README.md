# Key-and-budget service (AI gateway front)

Status: not started. No code exists yet.

| Item | Detail |
|---|---|
| Purpose | Sits in front of Portkey's open-source gateway and holds every model key. Owns model aliases, per-workflow and per-purpose keys and budgets, metadata logging, failover rules and discovery of unregistered agents from traffic. Generates Portkey configuration from the registry. |
| Owns | PostgreSQL (aliases, budgets, usage); provider keys in the secret store. |
| Depends on | Portkey gateway, model providers, the control plane (registry), `services/shared`. |
| Specs | `docs/specs/03-data-and-ai-gateways.md` 4.8, 5.8–5.10; ADR-0008 |

The service map, standards and security boundaries that apply to every service are in
`docs/backend/overview.md`.
