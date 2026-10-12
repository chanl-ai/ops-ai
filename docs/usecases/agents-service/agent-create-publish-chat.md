# Create, edit, publish an agent and chat with it

Status: current. Id: `uc-018`. Service: `agents-service`. Layers: api, ui.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA :8181 | `make db-up` |
| Free use-case ports | agents :8790, models :8792 (ISOLATED=1 adds 1000) |

The script starts its own agents service on the scripted model and models-service with its seeded scripted aliases;
no model key is needed. Publish requests are approved
as they are made because `registry_auto_approve` is on in dev.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | `POST /v1/agents` with name, role and model `bank-standard` (a models-service alias) | 201; `availability` is `not_published` |
| 2 | `POST /chat/threads` for that agent | Refused: a draft is not live |
| 3 | `PATCH /v1/agents/{id}` with instructions and `toolIds: [lookup_account]` | Version 2, `publishedVersion` still null |
| 4 | `POST /v1/agents/{id}/test` asking for account CHQ-2219 | The turn calls `lookup_account` and reports model `bank-standard` |
| 4a | A second agent naming `no-such-alias`, then its publish request | 422 `unknown_model_alias` |
| 5 | `POST /v1/agents/{id}/publish-requests` for version 2 | 201; an `agent_publish` review, status `approved` |
| 6 | `GET /v1/graphs` | Lists `agent:<id>` |
| 7 | A chat thread and message on the agent | Streams a `lookup_account` call and the reply |
| 8 | `POST /v1/threads` on `agent:<id>` and run it | The reply comes back in the thread state |
| 9 | `DELETE /v1/agents/{id}`, then a thread on its graph | 204, then 400 |

In the console (ui layer), with Agents, Workflows and Cases pointed at the scripted agents service:

| # | Step | Expected |
|---|---|---|
| 1 | `/agents`, New agent, name and role | `POST /v1/agents` 201, `not_published`; the agent page opens |
| 2 | `POST /v1/threads` on `agent:<id>` | Refused: a draft has no graph |
| 2a | Grant tools: tick `lookup_account`, save as v2 | The picker lists exactly `GET /v1/tools`; `PATCH /v1/agents/{id}` returns v2 with `toolIds: [lookup_account]` |
| 3 | Request publish with a note | An `agent_publish` review, `approved`; the header drops Request publish |
| 4 | `/workflows`, Start run, pick the agent by name, a message | A thread on `agent:<id>`; the console reports the finished run and stays out of Cases, which leaves agent runs out |
| 5 | `GET /v1/threads/{id}/state` | The message and the agent's reply |

The run's reply, "Here is what I found.", comes only after `lookup_account` returns; without the grant the scripted
model answers "I could not find that."

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-018-api.py` | passing |
| ui | `agents-service/scripts/test-uc-018-ui.mjs` | passing |

## Non-vacuous check

`chat with the unpublished agent is refused` pairs with `chat answered after reading the account`: the same chat call
fails before the publish and succeeds after it, so the success is the publish's doing. With the lifespan's registry
load removed, the published agent is missing from the graph list and the script fails. At the ui layer, `a thread on
the draft agent is refused` pairs with `the run is a thread on agent:<id>` after the console's publish.
