# Import presets access per operation and asks for no connection

Status: current. Id: `uc-054`. Service: `console`. Layers: ui.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA | `make db-up` |
| platform-service's dev seed | James Richardson (builder), Priya Shah (admin); password `northfield-demo` |
| The fake bank on https | the ui harness's `tools: { bank: true }`; its `/v1/openapi-open.json` names no security scheme and has a POST |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Priya allows the bank's host and range | 201 |
| 2 | James opens Tools > Import operations and picks OpenAPI | no Connection field |
| 3 | He enters the open spec's URL and goes Next | the no-auth warning shows |
| 4 | Reads the operations | `get_account` (GET) is Read and selected; `place_hold` (POST) is Write and not selected |
| 5 | Selects `place_hold` and saves the draft | 201; the module's operations are `get_account` read and `place_hold` write |

A module's endpoint and its secret headers are how it reaches the system (docs/architecture/tool-lifecycle.md), so
import asks for no connection record.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-054-ui.mjs` | failing: step 5 waits on tools-service accepting a module with no `connectionId` (an earlier change T006) |

## Non-vacuous check

Step 2 fails on the dialog before an earlier change T007, which required a connection before Next; step 4 fails on tools-service
before T006, which imported every operation as Write.
