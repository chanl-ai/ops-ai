# A run outlives a killed worker and redrives from its failed step

Status: current. Id: `uc-757`. Service: `agents-service`. Layers: api.

Short title: A run outlives a killed worker and redrives from its failed step

## Story

As a builder, I want a workflow run to finish when the process running it is killed in the middle of a step, and to
send a stopped run on from the step that failed, so that no customer gets a note twice and no model call is paid twice.

## People

| Person | Role | Does what |
|---|---|---|
| Priya Shah | Admin of Operations | Turns AI steps on for the team |
| A builder in Operations | Builder | Publishes the workflow, starts its runs and redrives the one that stopped |

## In this example

In this example we will publish a workflow that writes a note on a customer's record, summarises the call with a model
and writes the summary as a second note. We will kill the worker by SIGKILL while the second note is being written,
start a new worker, and check that the run finishes with one model call and two writes. Then we will stop
let a second run's workers die on its summary until it is marked Stuck, and redrive it with a healthy worker. It assumes the
core bank fake holds a note write open while its author reads `slow:<seconds>:`. The model is the fake OpenAI, never a
real one.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A run whose worker is killed in the middle of a write is finished by the next worker | api | 1, 2 | 2 |
| S2 | Across the kill, the model answers each call once and the system gets each write once | api | 3 | 3 |
| S3 | A run whose worker keeps dying is marked Stuck and can be redriven | api | 4 | 4 |
| S4 | Redrive goes on from the failed step and writes no note again | api | 5 | 5 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Start a run, then SIGKILL its worker (the Python process under `uv run`) while the summary note is being written | The worker is gone, the run is still running and the note step's row is still running |
| 2 | Start a replacement worker | The run succeeds with outcome `filed`, and its page shows the note step left by `ok` |
| 3 | Read the model call log and the gateway's executions for the run | One model call; two note writes, one for each note step |
| 4 | Start a second run and seven workers that each SIGKILL themselves after its summary step (`OPS_ENGINE_FAULT_KILL_AFTER_NODE`), then one that reconciles | The run is Stuck with Redrive offered (`canRedrive`), and its first note reached the bank once |
| 5 | Start a healthy worker and redrive the run (`POST /v1/runs/{id}/redrive`) | The run ends `filed`; each note step has one attempt, the bank got two writes and the model one call |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-757-api.py` | works |

## Non-vacuous check

Step 3. With the engine's settling of a dangling write by its key removed (the `last.status in ("running", "error")`
branch of the step wrapper in `packages/ops_engine/src/ops_engine/compiler.py`), the replacement worker sends the held
write again under a new key, the bank gets a third note, and step 3 fails. Step 1 fails unless the kill lands while the
write is in flight, so a run that finished before the kill cannot pass.

## Not covered

A chat reply cut off mid-reply is not in this use case. The process that runs a reply is the agents API the person is
connected to (`services/agents-service/src/ops_agents/api/chat_turns.py`), so the kill would have to stop the API.
A worker taking over a reply is proved by `services/agents-service/tests/engine/test_chat_turns.py`.
