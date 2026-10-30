# A guardrail has its own page and an agent pins one of its versions

Status: current. Id: `uc-104`. Service: `console`. Layers: ui. Card: an earlier change.

A guardrail opens on its own page, like an agent: its rule is edited there and saved as a new draft version, published
from the header, and every version is listed with its state and note. An agent pins any published version from its
Guardrails section, and the pin links back to the guardrail's page. Design:
[agent builder](../../console/agents-and-workflows.md).

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA :8181 | `make db-up` |

The script creates its guardrail (v1 published) and an agent through agents-service; dev auto-approve publishes at once.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Click the guardrail's row on Guardrails | `/guardrails/<id>` opens |
| 2 | Change the message, note "Points to an adviser", Save, then Publish | PATCH 200, publish 201 |
| 3 | Open Versions | v2 "Live for new pins" with the note; v1 Published |
| 4 | On the agent, pin the guardrail, choose v1, save the agent | The agent's pins hold `<id>@1`; the pin's name links to `/guardrails/<id>` |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-104-ui.mjs` | passing |

## Non-vacuous check

Step 4 reads the agent back from agents-service: without the version picker the new pin takes the published v2 and the
check fails.
