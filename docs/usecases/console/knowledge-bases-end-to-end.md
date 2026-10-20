# Knowledge bases work end to end from the console

Status: current. Id: `uc-096`. Service: `console`. Layers: ui.

c-094, the owner's request: a person stands up knowledge without engineering help, every step in the console on the
real stack. James creates a base, adds files and a page, watches them index, tests a question and retires the base.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| platform-service's dev seed | James Richardson (builder) on Operations; password `northfield-demo` |
| PDFs | `services/kb-service/seed/pdfs/branch-operations-manual.pdf`, and a one-page PDF with no text layer built in the script |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | New knowledge base: name, owner, description, Create | 201; the person lands on the base's page |
| 2 | Sources tab > Add source > File upload, name, Create; add the manual and the scanned PDF; Sync | the sync indexes one and fails one |
| 3 | Documents tab; then the list | the manual is Indexed; the scan shows "no text layer" in its row; the list shows 1 document and the base Degraded |
| 4 | Documents tab > Add page: title and text | 201; the page shows as Indexed |
| 5 | Playground: "What is the daily ATM withdrawal limit?" | an answer citing Branch Operations Manual by page; no search mode or control kb-service does not build is shown |
| 6 | An agent cites the base (set through agents-service); Delete it | the dialog names the agent and keeps Delete off until the name is typed; 204; the base leaves the list and is 404 |

An agent that still names a retired base answers from its other bases: `services/kb-service/tests/test_retrieval.py`
(`test_an_agent_citing_a_retired_base_still_answers_from_its_others`).

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-096-ui.mjs` | passing |
