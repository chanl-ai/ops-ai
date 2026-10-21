# Banker demo stage scripts

Status: demo scripts; steps marked "pending" wait on the task named. Fake bank, fake mailbox and the scripted model stand in for the outside world; nothing inside the services is special-cased for the demo. Two stories: the court order notice (c-057) and the two knowledge agents (c-058).

## Court order notice from the mailbox to a held account


### Before the room

| Step | Command or check | Expect |
|---|---|---|
| 1 | `make up AUTH=platform` from the repo root; models-service and the fake OpenAI per `docs/services/models-service/overview.md`; the fake bank from `services/tools-service/scripts` | every row of `make health` ok, including kb :8740 |
| 2 | `.env`: `OPS_EGRESS_RESOLVE` names the laptop's current private address for `api.bank.test`; `POST /v1/egress/ranges` holds that `/32` | the bank module's test call succeeds on the Tools page |
| 3 | `uv run python scripts/reimport_bank_module.py --as j.richardson@harborpine.example --decide-as n.petrov@harborpine.example` in `services/tools-service` | prints the operations it added and the hold's approval |
| 4 | Keep the laptop on one network from here on | the address in step 2 stays valid |

### On stage

| Step | Who | Do | What appears |
|---|---|---|---|
| 1 | Presenter | `uv run python scripts/send_levy_email.py --key-suffix <today>` in `services/agents-service` | the sent line; within a few seconds the worker starts one court order intake run (c-212: court orders run on the workflow runner, not the v1 thread flow the rest of this script describes) |
| 2 | Maya | Cases | one intake run and one case per matched debtor: Marcus Bell, Priya Natarajan; Jordan Whitfield listed as unmatched on the intake run |
| 3 | Maya | open a case | the notice's persons as rows, the customer and accounts as a record, the child cases; the run trace shows the loop over three records |
| 4 | Maya | Reviews, open Priya's case, Hold, keep the amount from the notice, confirm | the step-up dialog (pending c-055 T022), then the hold placed in the bank with its id on the case |
| 5 | Maya | Reviews, open Marcus's case, Flag | a note on the customer; the case closes |
| 6 | Maya | back on the intake run | both outcomes listed (pending c-057 T012) |
| 7 | Anyone | Activity | every bank call behind the run, with who, when and the approval |
| 8 | Presenter | drop the same notice again with the same suffix | nothing opens: the trigger takes it for a redelivery |

### If something goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| Matching finds nobody | the bank module lacks `customers.search` or the egress address moved | step 2 and 3 of "before the room" |
| Hold answers 422 on the case | amount over the available balance | decide again with a smaller amount; nothing retried |
| Approve ends at "supports email and password only" | step-up seam not deployed | c-055 T022 |

## Two agents answering from department knowledge bases


### Before the room

| Step | Command or check | Expect |
|---|---|---|
| 1 | `uv run python scripts/seed_demo_knowledge.py --as j.richardson@harborpine.example --agents http://127.0.0.1:8700` in `services/kb-service` | Retail products (owner James) and Branch operations (owner Nadia) indexed; ag_advisor and ag_policy wired |
| 2 | Knowledge bases page as James | both bases listed with their documents and page counts |
| 3 | Model: the connection `openai-local` points at the real provider for the day (`PUT /v1/models/providers/openai-local`), from a network that reaches it | a test question in chat answers in prose, not "heard:" |

### On stage

| Step | Who | Ask | What appears |
|---|---|---|---|
| 1 | James, Advisor's helper | What does Priya Natarajan have with us? | her record as fields, her accounts as a table |
| 2 | James | Compare Savings Plus and Money Market for her | a cited answer, product sheet page 4; the comparison as a table (pending c-055 T021) |
| 3 | Maya, Branch policy | What is the wire fee for a business account? | the answer with a citation into the fee schedule, page 1; click it, the passage opens |
| 4 | Maya | What is the ATM withdrawal limit? / How do I place a stop payment? | each cited into the operations manual, page 2 and 3; the limits table as rows (pending c-055 T021) |
| 5 | Maya | Can a customer prepay a mortgage without penalty? | "That is not in the knowledge base." with no citation |
| 6 | Nadia | Knowledge bases, Fee schedule source, upload fee-schedule v2, sync | the document shows the new version; Changes lists the row with before and after |
| 7 | Maya | the wire fee question again | the citation names the new version |

### If something goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| An answer with no citation on a covered question | the passage scored under the floor (0.5) | ask with the document's own words; the seed records each demo question's score |
| "knowledge was unavailable" | kb-service down or not configured for agents | `make health`; `OPS_KB_URL` on agents |
| Every answer reads "… heard: …" | the scripted model is still bound | step 3 of "before the room" |
