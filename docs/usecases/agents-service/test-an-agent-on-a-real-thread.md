# A builder tests an agent on a real chat thread the server marks test

Status: passing. Id: `uc-247`. Service: `agents-service`. Layers: api, ui. Card: an earlier change; ui layer an earlier change.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | James asks in the agent's test panel, and the thread it starts is marked test | ui | 1 | 1 |
| S2 | Ravi, a viewer, asks too and is told the test could not start | ui | 2 | 2 |
| S3 | The question and its reply show in the test panel | ui | 3 | 3 |
| S4 | His conversations list his chat and leave the test out | ui | 4 | 4 |
| S5 | The same through the API, with the agent's tasks counting the chat and not the test | api | 1-5 | 5 |

A test of an agent is a chat thread like any other, started with `test: true`: the same thread API, the same
streamed reply, each message on the agent's newest version, draft included. The server grants the mark only to
someone who may test the agent (agents.edit) and stores it; a test is left out of the conversations list, the
agent's tasks in the last day and memory.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| platform-service and agents-service with platform sign-in | `people_stack()` |
| James Richardson (builder) and Ravi Menon (viewer) of team_ops | the platform dev seed |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James starts a thread on Branch Concierge with `test: true` | 201, the thread is marked test |
| 2 | Ravi asks for the same | 403; Ravi has no test threads |
| 3 | James asks a question in his test | The reply streams and ends `done` |
| 4 | James starts a chat too and lists his threads | The list shows the chat; `test=true` lists the test, marked |
| 5 | Read the agent's tasks in the last day | Up by one: the chat, not the test |

The draft-versus-published check (a test runs the newest draft, re-read on every message) and the memory check need
a model that answers from its instructions, so they are in `services/agents-service/tests/api/test_test_threads.py`.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-247-api.py` | passing, `ISOLATED=1 make usecase-test UC=uc-247 LAYER=api` (2026-10-18) |
| ui | `agents-service/scripts/test-uc-247-ui.mjs` | passing: the agent page's test panel, Conversations, and a viewer refused |
