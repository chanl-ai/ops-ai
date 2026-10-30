# Access is Read or Write in the console

Status: current. Id: `uc-052`. Service: `console`. Layers: ui.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA | `make db-up` |
| platform-service's dev seed | James Richardson, password `northfield-demo` |
| tools-service's dev seed | the seeded modules |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Open Tools, Access, Activity > Tool calls, Agents and Workflows | no page shows "Moves money" or "money movement" |
| 2 | On Tools, open the Access filter | Read and Write only |
| 3 | Open the first module: no money class shows; Add operation, open Access | Read and Write only |

How strict a write is belongs to the operation's approval policy (`approvers`, docs/architecture/tool-lifecycle.md),
not to an access class.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-052-ui.mjs` | passing |

## Non-vacuous check

Each step fails on the console before an earlier change T004, which offered "Moves money" in the filter, the access select and
the module badges.
