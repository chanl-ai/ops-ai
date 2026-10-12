# Simple workflow through the four thread calls

Status: current. Id: `uc-003`. Service: `agents-service`. Layers: api, ui.

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

In the console (ui layer), with Cases runs pointed at the scripted agents service:

| # | Step | Expected |
|---|---|---|
| 1 | `/workflows`, Start run, open Workflow | The options are `GET /v1/graphs` less graphs that take an agent id |
| 1a | Pick Product question, submit with no question | Inline "Question is required."; no call sent |
| 2 | Type the wire-limit question, Start run | `POST /v1/threads` 201 on `simple_workflow`, then `runs/stream` 200 |
| 3 | The console opens `/cases?run=<threadId>` | Run sheet lists Classify before Answer |
| 4 | Cases, Done today | The row for that thread, subject the question, state Done |
| 5 | `GET /v1/threads/{id}/state` | Answer with $25,000 citing `doc_wire_limits` |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-003-api.py` | passing |
| ui | `agents-service/scripts/test-uc-003-ui.mjs` | passing |

## Non-vacuous check

`answer cites doc_wire_limits`: the citation comes from retrieval inside the run, so a graph that skipped the answer node or lost its state fails it.

At the ui layer, `the run streamed (200)` and the checks after it: with the console's start call skipping `runs/stream`, the script stopped after 3 PASS lines and failed. The empty-question refusal pairs with the 201 that follows it. `the picker offers the service graphs that take no agent` failed with the console's graph list hard-coded to one workflow.
