# Workflow interpreter

Status: not started. No code exists yet.

| Item | Detail |
|---|---|
| Purpose | Runs one Temporal workflow type that walks any compiled execution plan. Holds the node-type implementations (`nodes/`), the activity workers per risk tier, and the agent-block host (`agent_host/`) that runs existing Python agents. |
| Owns | No tables of its own. Temporal holds run history; run journal rows and payloads go through the control plane and the object store. |
| Depends on | Temporal, the data gateway, the AI gateway, the control plane, `services/shared`. |
| Specs | `docs/specs/01-agent-builder.md` 4.6, 5.6, 5.7; ADR-0001, ADR-0003 |

The service map, standards and security boundaries that apply to every service are in
`docs/backend/overview.md`.
