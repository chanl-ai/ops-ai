# Chat turn with citation

Status: current. Id: `uc-001`. Service: `agents-service`. Layers: api.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA :8181 | `make db-up` |
| Free use-case ports | agents :8790, tools :8791, console :3018 (ISOLATED=1 adds 1000) |

The script starts its own services on the scripted model; no model key is needed.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Create a chat thread for `ag_fraud` on `kb_people` (`POST /chat/threads`) | 201; the thread has no messages |
| 2 | Send "What is the daily wire limit for a personal account?" (`POST /chat/threads/{id}/messages`, event stream) | Frames start with `start` and end with `done`; a `citations` frame names `doc_wire_limits` as [1]; the text carries $25,000 and the [1] marker |
| 3 | Read the thread (`GET /chat/threads/{id}`) | User then assistant message; the stored reply keeps the citation and records the scripted model |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-001-api.py` | passing |

## Non-vacuous check

`citation [1] points at doc_wire_limits`: only a retrieval hit on the seed knowledge base produces that document id. Seen failing by pointing the thread at a knowledge base without that document.
