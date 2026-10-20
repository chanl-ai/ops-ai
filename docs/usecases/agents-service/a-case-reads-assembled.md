# A case reads assembled

Status: passing (2026-10-19). Id: `uc-251`. Service: `agents-service`. Layers: api. Card: c-291.

A fee dispute workflow, configuration in the script and nothing in code, opens a case of the seeded `complaint` case
type and waits on a person to approve waiving the fee. One call, `GET /v1/cases/{id}`, returns the case assembled for
its page: its typed fields in the case type's order, what it waits on and the drafted action, the run and workflow
that opened it, and the dispute letter the run was given. Approved on its own task page, the case then reads the
action decided and the decision in its activity. A real worker runs it; no model call is made.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL for the isolated stack | `make db-up ISOLATED=1` |
| The run | `make usecase-test UC=uc-251 LAYER=api ISOLATED=1` |

The stack is agents-service and tools-service (the tool gateway) with a workflow worker, on the scripted model.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 0 | Save and publish the fee dispute workflow | 201, the version goes live |
| 1 | Start it for Marcus Bell's late fee, with the dispute letter's file in the input; read the case | Fields in the `complaint` type's order: complaint, category, urgency (empty), amount `35.00`; `caseType` names `complaint` |
| 2 | The same read | One waiting task, the next action pointing at it, one drafted action `pending` linking the same task |
| 3 | The same read | `links.runs` holds the run, `workflow` names Fee dispute (uc-251), `links.files` holds dispute-letter.pdf |
| 4 | Approve the task on its page (`POST /reviews/{id}/decision`), read the case again | Nothing waiting, no next action, the action `approved` |
| 5 | `GET /v1/activity?case={id}&kind=decision` | One decision; `activity.allHref` opens Activity filtered to the case |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-251-api.py` | passing |

## Non-vacuous check

With `waiting_of` in `api/case_page.py` returning nothing, step 2 fails (no waiting task, no next action) and the
unit test `tests/api/test_case_page.py::test_the_case_says_what_it_waits_on_until_the_task_is_decided` fails with it.

## What this does not cover

Whether the fee is waived after approval: the gateway's binding of `cardAccount` to the case is the tool's own check,
covered by tools-service. The case page in the console is c-292.
