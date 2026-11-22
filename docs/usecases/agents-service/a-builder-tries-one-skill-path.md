# A builder tries one path of a skill, and no write runs until they confirm

Status: current. Id: `uc-762`. Service: `agents-service`. Layers: api.

A builder on a skill page (or a workflow step's sheet) opens Try, picks one path of the skill's `if`s and the account
to try it on, and runs it. Each tool step on the path comes with the values it would send and a sample result: the
tool's last answer in one of the team's live runs, else a skeleton of its output schema. Reads run for real. Every
write is shown first as a plan (what it would send, to which system, on which account) and is sent only when the
builder confirms with the same values; on a live account the plan says so. Nothing is saved as a version or counted as
a run. Paths and samples come from `GET /v1/try-targets` (agents-service); each try is `POST /v1/tool-modules/tries`
(tools-service), on the gateway's one dry-run seam (`GatewayCalls.call(plan_only=True)`).

## Preconditions

| Needs | How |
|---|---|
| platform-service, agents-service, tools-service and the mock bank | `bank_stack()` in `lib/main_chains.py` |
| A published module with a read and a write on the mock bank | `publish_bank_module` |
| Team writes do not wait for a reviewer | the admin turns `toolWritesNeedApproval` off |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Save a skill that reads an account and, if it is open, freezes it; ask what can be tried | Two paths; the open one holds both tool steps with their access and a sample |
| 2 | Try the read | It runs against the bank |
| 3 | Try the write | A plan: POST to the account's holds, marked live; the bank receives nothing |
| 4 | Confirm with edited values | 409 `plan_stale`; nothing sent |
| 5 | Confirm, then confirm again | Sent once; the second answers with the first send's call |
| 6 | — | The skill keeps its versions; no workflow run exists |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-762-api.py` | `make usecase-test UC=uc-762 LAYER=api` |
