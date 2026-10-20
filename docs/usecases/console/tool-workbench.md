# A builder builds and debugs a tool operation on its full-width workbench

Status: current. Id: `uc-101`. Service: `console`. Layers: ui.

c-088, the maintainers' feedback (Tools-1): the tool side panel was too small, and its fields, secrets, mocks and transform
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
| 1 | Tools > the module > the operation's row | the row holds one link to the workbench and no `tabindex` of its own; the operation opens at `/tools/{module}/operations/{name}`, wider than 900px; the module page has no side test console |
| 2 | Edit the mock response and the transform; Run against the mock | Output is the transformed answer, Raw response the mock; the operation's mock and transform are unchanged and nothing is staged |
| 2b | Open the Run-as list | "Module owner, no case" with no leading separator |
| 3 | Type the key as the secret's test value; Test environment; Run | the bank answers (Allowed, 200); the Request tab shows `api_key=[secret]`; the key is in no response the console receives |
| 3b | After the run returns | the typed key is in no input and nowhere in the page's HTML (a controlled input writes its value into the `value` attribute) |
| 4 | A transform that reads a missing field; Run against the mock | the reason shows under the Transform field and on the result; Output is the raw answer |
| 5 | Stage changes | the PATCH carries the mock; the module lists "Mock response edited" as a minor unpublished change |
| 6 | A viewer (Ravi) opens the same operation; a builder (James) opens it too | the viewer sees a View only notice, no Stage changes or Access and approval, and every field disabled; the builder never sees View only, not while the role loads; at 390px the viewer's Run tab is enabled and opens the run panel (c-125) |
| 7 | Open the operation at 390px wide, then at 1440px | on the phone Definition and Run are tabs (Definition first) and Run is on screen after one tap; at 1440px both sit side by side and there are no tabs |

The typed value is not stored, logged or returned: `services/tools-service/tests/test_workbench_runs.py` scans every
table of the test database and the captured logs for it.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-101-ui.mjs` | passing |
