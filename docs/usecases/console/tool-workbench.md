# A builder builds and debugs a tool operation on its full-width workbench

Status: current. Id: `uc-101`. Service: `console`. Layers: ui.

The tool side panel was too small, and its fields, secrets, mocks and transform
did not work well. An operation now opens on its own page, its definition on the left and a run on the right, and a run
tries the draft mock and transform and a secret value typed for that run before anything is staged.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| platform-service's dev seed | James Richardson (builder), Sam Adeyemi (Security admin), Nadia Petrov (approver), Ravi Menon (viewer on team_ops); password `northfield-demo` |
| The fake core bank on https | the ui harness with `tools: { bank: 'core' }`; its statement route takes its key in the query string |
| A published module | set up through the API: Sam allows the bank host, James adds `get_statement_<tag>` reading `{{STATEMENTS_API_KEY}}`, Nadia approves the review; the secret is never set for the tenant |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Tools > the module > the operation's row | the row holds one link to the tool page and no `tabindex` of its own; the operation opens at `/tools/{module}/operations/{name}`, wider than 900px; the module page has no side console |
| 2 | A mock answer is set through the API; open More › Transform, type a transform, and Run in Mock | Response is the transformed answer, Raw response the mock answer; the operation's transform is unchanged and nothing is staged |
| 2b | Retired: Run as a workflow's case belongs to the Function workbench; a REST tool runs as its owner | |
| 3 | Headers › type the key as the secret's test value; Real; Run | the bank answers (Allowed, 200); Request sent shows `api_key=[secret]`; the key is in no response the console receives |
| 3b | After the run returns | the typed key is in no input and nowhere in the page's HTML (a controlled input writes its value into the `value` attribute) |
| 4 | A transform that reads a missing field; Mock; Run | the reason shows under the Transform field and on the result; Response is the raw answer |
| 5 | Save a transform | the PATCH carries it; the module lists an unpublished change for the operation |
| 6 | A viewer (Ravi) opens the same operation; a builder (James) opens it too | the viewer sees a View only notice, no Save or Access and approval, the App field disabled and Run off with why (viewers may not run tools); the builder never sees View only |
| 7 | Open the operation at 390px wide | Run sits with the address, above the inputs, and nothing scrolls sideways |

The typed value is not stored, logged or returned: `services/tools-service/tests/test_workbench_runs.py` scans every
table of the test database and the captured logs for it.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-101-ui.mjs` | passing |

## Setup state

The test-run response the script reads goes through `required()`, so a missing or refused run stops the script as setup. Passing on 2026-11-12.
