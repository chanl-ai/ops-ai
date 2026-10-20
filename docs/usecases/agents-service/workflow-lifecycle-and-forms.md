# A builder designs a workflow in forms, publishes it through review, pauses, resumes and cancels a run

Status: current. Id: `uc-092`. Service: `agents-service`. Layers: ui. Card: c-075 (MVP M6).

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA (docker) | `make db-up` |
| Free use-case ports | the runner picks free ports and a database of its own |

The script starts its own agents-service (scripted model) with `OPS_REGISTRY_AUTO_APPROVE=false`, platform-service
for sign-in (James builds, Maya approves), tools-service as the gateway, the console, and workflow workers it starts and
stops. No model is called.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James: Workflows, New workflow, runner | A draft opens in the editor; its stage badge says Draft |
| 2 | Add each built step type from the palette | Each opens a generated form with one control per setting of its type (`ui.order`), the JSON closed under All settings |
| 3 | Add an Agent step and open its Agent field | It lists the published agents from `GET /v1/workflows/option-sources?source=agents`; the tools source answers 200 |
| 4 | In the End step's form set Outcome `refunded` and Output to the step output `$.input.amount`; Save | Version 2 is stored as a draft with those parameters |
| 5 | `POST /v1/runs` live; open Start run | 409 `not_live`; the dialog offers only a test run |
| 6 | Publish…, What changed, Request publish | A pending `WFP-` request; the badge says In review and links to it; James's own approval is refused (403); the Workflows list shows Draft and "v2 awaiting approval" |
| 7 | Maya approves `POST /reviews/{id}/decision` | 200; the editor shows Live |
| 8 | Start a worker; Start run (live) with `{"amount": 42}` | The run page shows the Result: "Ended at Done with outcome refunded" and output 42 |
| 9 | Pause and confirm; `POST /v1/runs` live; Resume and confirm | Badge Paused; 409 `workflow_paused`; badge Live again |
| 10 | Stop the worker; Start run; Cancel run and confirm; start a worker | The run page says Cancelled; the run stays cancelled with no step |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `agents-service/scripts/test-uc-092-ui.mjs` | passing |

## Non-vacuous check

`a draft is refused a live run (409 not_live) and the editor offers only a test run`. With the start rule removed from
`POST /v1/runs` (`routers/engine.py`, `if body.mode == "live"`) the start returns 202 and the check fails; the same
reversion fails `tests/engine/test_lifecycle.py::test_a_draft_starts_only_test_runs_until_a_second_person_approves_it`
(`.codeloop/evidence/075/red-api.md`).
