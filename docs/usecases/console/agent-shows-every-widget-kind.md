# The agent shows every generic widget kind in a chat

Status: current. Id: `uc-132`. Service: `agents-service` and `console`. Layers: ui.

Chat widgets are generic kinds, the same in any industry: a stat, table, chart, timeline, status tracker, entity card,
comparison, checklist, form, confirmation, document passage, quote, plan, chain of thought, appointment picker,
receipt and contact card. The agent shows one with `present {kind, data}`; the kernel checks the data against the
kind's JSON schema and fills it through the template binder, and the chat draws it with the console's one renderer set.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA :8181 | `make db-up` |
| Free use-case ports | agents, platform-service and console (ISOLATED=1 adds 1000) |

The agents service runs on the scripted model: "call present {json}" makes it call `present` with that JSON. Each
kind's data is the first sample in `apps/console/src/lib/widgets/kind-samples.json`, the gallery's own samples.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James makes and publishes an agent and starts a chat | 201s |
| 2 | One message per kind: "call present {kind, data}" for all 17 | Each turn answers 200 |
| 3 | A tracker whose step state is not one the schema allows | The turn answers, and no widget is drawn for it |
| 4 | James opens the chat | Each of the 17 kinds is drawn once, with its sample's text, and nothing else is; no page errors |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-132-ui.mjs` | passing |
