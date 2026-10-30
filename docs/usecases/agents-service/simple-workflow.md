# Simple workflow through the four thread calls

Status: current. Id: `uc-003`. Service: `agents-service`. Layers: api.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA :8181 | `make db-up` |
| Free use-case ports | agents :8790, tools :8791, console :3018 (ISOLATED=1 adds 1000) |

The script starts its own services on the scripted model; no model key is needed.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | `POST /v1/threads` with graph `simple_workflow` | 201 with a thread id |
| 2 | `POST /v1/threads/{id}/runs/stream` with the wire-limit question | 200; nodes `classify` then `answer` |
| 3 | `GET /v1/threads/{id}/state` | Nothing next; category `product_question`; answer with $25,000 citing `doc_wire_limits`; not a no-answer |
| 4 | `GET /v1/threads?graph=simple_workflow` | The thread is listed |

The console starts workflows only: the built-in graphs left Start run on 2026-10-19, so this use case has no ui layer.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-003-api.py` | passing |

## Non-vacuous check

`answer cites doc_wire_limits`: the citation comes from retrieval inside the run, so a graph that skipped the answer node or lost its state fails it.
