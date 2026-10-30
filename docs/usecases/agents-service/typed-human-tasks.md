# A builder copies a task type and an API caller opens typed Human Tasks

Status: current. Id: `uc-254`. Service: `agents-service`. Layers: api, ui. Card: an earlier change.

A Human Task's screen comes from a task type: a versioned record of params, regions and actions. Five general types
are seeded and read-only; a team copies one to change it. A workflow review step or `POST /v1/tasks` names a type and
passes its params; the task keeps the version it opened on. An API task runs as the `api_task` system workflow, so it
is decided in Human Tasks like any other, and the caller reads the decision from `GET /v1/tasks/{id}`.

## Preconditions

| Needs | How |
|---|---|
| The agents service and a workflow worker on the use case database | harness `agents()` and `engine_worker()` |
| A caller and a reviewer | dev users lee@ and m.okafor@harborpine.example in team_all |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | List the task types; save over write_approval | The five general types are listed; the save is 409 `seed_read_only` |
| 2 | Copy write_approval as vendor_bank_change with its own question; publish v1 | 201 draft v1, then published |
| 3 | Post a task of vendor_bank_change with no version and no write | 201 on v1 with a `/reviews/` URL and one warning (`call`) |
| 4 | Publish a v2 with another question; open the task | It still shows v1's question, its facts, no empty write region, Make the change and Decline with their consequences |
| 5 | Post a task whose facts are a string | 422 `invalid_task_params` naming facts |
| 6 | The reviewer declines it in Human Tasks; the caller reads the task | action `reject`, the reason, and the reviewer as decider |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-254-api.py` | `ISOLATED=1 make usecase-test UC=uc-254 LAYER=api` |
| ui | `agents-service/scripts/test-uc-254-ui.mjs` | passing (2026-10-28): Human Tasks asks the pinned version's question with its facts and actions; Priya declines it and the caller reads it back |
