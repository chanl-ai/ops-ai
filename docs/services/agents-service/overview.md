# Agents service

Status: current, 2026-10-16. Prototype: chat and graphs work on seed data; see "What differs from the specs".

The agents service owns agents, workflows, their versions, chat and the runs that execute them
(`docs/architecture/service-map.md`). Today it serves the console's chat API: agents, threads, replies streamed over
SSE from a Pydantic AI agent loop (spec 15), gated writes that stop for approval and continue once approved, and
citations from a keyword passage store. The tools an agent may hold are tools-service's published operations: `GET
/v1/tools`, the grant check and every run read them from tools-service (`activities/tool_directory.py`), and every
call, read or write, runs through its gateway's `/v1/calls` (c-048 G1). The stack's seeded agents, granted seeded
operations, are in `services/agents-service/seed/chat_agents.json`; passages and the fixture tools the unit tests
run on stay in `services/agents-service/tests/fixtures/seed/`.

## Code

| Module | Role |
|---|---|
| `src/ops_agents/api` | FastAPI app, routers (chat, graphs, reviews, timers), chat turns, leases and sweeper, timers, metering, journal |
| `src/ops_agents/graphs` | LangGraph graphs `agent_wrapper`, `simple_workflow`, `complex_workflow`; JSON definitions, versions, SLA settings |
| `src/ops_agents/activities` | Tool, knowledge and gateway calls the graphs and the kernel make; seed catalogue loader |
| `packages/ops_agent_kernel/present.py` | The built-in `present(shape, data, hint?)` tool every turn offers (c-055 T021): the model returns a comparison table as `rows`, a figure as `metric`, a record or a series, and the turn emits it as a widget part with no tool result behind it. The chat shows only the part, never a tool card for it; a malformed part is refused as a tool error |
| `migrations/` | Alembic history 0001 onward. It still holds the tools service's and review tables until migrations split per service |
| `tests/` | API, unit, checkpointer, gateway and timer tests; `tests/fixtures/` is the only place fixture data lives |
| `experiments/` | Experiment scripts; their write-ups are in `experiments/` next to this page |

Libraries it uses: `packages/ops_agent_kernel`, `packages/ops_checkpointer`, `packages/ops_service_kit`,
`packages/contracts`.

## Graphs on four calls

Chat agents and workflows also run as LangGraph graphs on threads, through four calls that mirror LangGraph Server.
State is saved after every node by the checkpointer, so a pause survives a restart.

| Call | Does |
|---|---|
| `POST /v1/threads` `{graph, metadata}` | Creates a thread for `agent_wrapper`, `simple_workflow` or `complex_workflow` |
| `POST /v1/threads/{id}/runs/stream` `{input}` or `{resume}` | Runs or resumes; SSE of `{event, runId, seq, node?, data?}`; a repeated `runId` replays |
| `GET /v1/threads/{id}/state` | Values, next nodes, pending interrupt |
| `GET /v1/threads?graph=` | Lists threads |

## Settings

| Setting | Env | Default |
|---|---|---|
| Database | `OPS_DATABASE_URL` | `postgresql+asyncpg://ops:ops@localhost:5477/ops_runtime` |
| Port | `OPS_PORT` | `8700` |
| Model | `OPS_MODEL_ALIAS` | `gpt-5.5` (a `claude-*` alias selects Anthropic) |
| Model key | `OPENAI_API_KEY`, or `ANTHROPIC_API_KEY` for a `claude-*` alias | none |
| Tool gateway | `OPS_GATEWAY_URL` | none: tools then run in process from the fixture catalogue (unit tests only); the stack sets tools-service |
| Seed directory | `OPS_SEED_DIR` | `services/agents-service/seed/` in dev; unset outside dev, so production starts empty. Tests name `tests/fixtures/seed/` |
| Seeded agents | `OPS_AGENTS_SEED_FILE` | `chat_agents.json` in the seed directory |

Values carry the `OPS_` prefix because a shared secret store may already define `DATABASE_URL` for another
service. Without a model key the service starts, `/health` reports the missing key and sending a message returns 503.

## Proofs

| Task | Command (from `services/agents-service`) |
|---|---|
| End-to-end chat against the running service | `uv run python scripts/prove-chat.py` |
| Three graphs through the four calls, plus a kill-and-resume | `uv run python scripts/prove-graphs.py` (needs a model key) |
| Regenerate `docs/architecture/dependencies.md` | `make sbom` |

Real model calls are capped at 10 per experiment unless more are approved; everything else runs on the
scripted model in `tests/conftest.py`.

## Cases and Reviews facade

The console's Cases runs and Reviews read runtime threads through `ops_agents/api/hitl_facade.py`, on the console's
own paths, so `NEXT_PUBLIC_OPS_CASES_API_URL` points those two areas here while the rest stays on the mock. Rows are
built server-side from each thread's state, run journal, SLA timers and decisions. These routes are a stand-in: they
move into the `ops_hitl` package, which agents-service will host.

| Route | Does |
|---|---|
| `GET /runs?view&workflowId&state&queue&parent&search&page&pageSize` | Workflow threads as `RunRow`s with view counts and facets; chat threads excluded; `parent` lists one thread's child cases |
| `GET /runs/{id}` | One `RunRow` with its node steps for the run sheet, its `parentThreadId`, and `children` with each child's current outcome |
| `GET /reviews?view&…`, `GET /reviews/{id}` | Paused review steps and recorded decisions as `Review`s. A case review's title is the case subject; `amount` is the proposed call's amount; `options` declares each option's call, editable inputs and whether it asks a step-up; `calls` and `error` carry the case's proposals and the last failed call; `slaMinutes` is null when the step set no SLA. A row paused before declarations existed stores option names; they are resolved against the thread's pinned version (the declaration belongs to the workflow version, not the row), and a name the version no longer declares lists the review with `optionsError` and refuses that decision, never a 500 |
| `POST /reviews/{id}/decision` | Records the decision (keyed by the interrupt id), then resumes the thread under a run id derived from it. A failed resume leaves the decision standing and a repeat retries it once. A step with options takes `decision: <option>` and `inputs`, validated against the option's declaration, and is recorded as approved with `option`. A step-up token is needed when the chosen call's policy asks for one (`stepUp`, which two approvers imply); `returned` is refused |
| `POST /reviews/bulk-decision`, `POST /reviews/assign` | Bulk decide per id; assignment reports every id skipped until `ops_hitl` owns it |

Building a row reads each thread's state and journal, so a list costs a few queries per thread. That is fine at
demo volume and is the first thing to replace with stored columns.

## A case assembled for its page

`GET /v1/cases/{id}` (c-291, `api/case_page.py`, `store/case_links.py`) returns the case assembled for the case page,
so the console joins nothing. It keeps every key the route returned before (`fields` as a name-to-value map, `events`,
the clocks as seconds left) and adds:

| Key | What it holds | Read from |
|---|---|---|
| `caseType` | The case type and version the case was opened with | `cases.type_id`, `type_version` |
| `typedFields` | Each field with label, type, display text and raw value, in the case type's order, then any value the type does not declare in the order it was set | `case_fields.py`: the extraction field types plus `file` and `link`; money and numbers grouped, dates as ISO |
| `owner`, `team`, `customer` | Names, not ids; the customer links the case list filtered to them | platform-service people and team names |
| `sla` | Each clock's state (running, met, breached, paused), due time, seconds left and when it was met | the case row |
| `waiting`, `nextAction` | The Human Tasks the case's runs wait on, each linking its task page; the first is the next action | review views of the case's runs, at most 10 |
| `actions` | A Human Task that would call a tool is a drafted action, with its status and approvals; it is decided on its task page | the same review views |
| `links` | Its runs with their workflow names, the files their input named, the emails that started them, and cases linked to it or open for the same customer in its team (5 at most), each with an `allHrefs` entry | one query per list |
| `workflow` | The workflow whose run opened the case | the opening run |
| `activity` | The five newest lines of Activity filtered to the case, with the actor's name, and its total | `GET /v1/activity?case=` (c-341) |
| `permissions` | `assign`, `changeStatus`, `close`, `note`, each from `can()` | the caller's roles in the case's team |

A case reads in the same number of queries whatever it holds (`tests/api/test_case_page.py`, 1 run against 30). Not
yet: `edited` is false for every field, since case values are written only by workflow steps; files carry no type,
size or scan result, which the viewer link shows.

Case types (`/v1/case-types`, `store/case_types.py`) are versioned records like task types, on the same store
(`store/typed_records.py`). Both are kept per team, keyed (tenant, team, id) since c-507: each team holds its own copy
of the seeded ones in `seed/task_types.json` and `seed/case_types.json`, made on the team's first read, and creates,
saves and publishes its own with `workflows.create`, `edit` and `publish`; no team reads another team's types. An
Open case step names one with `caseType`; the case pins its newest published version, and a type with none takes the
error port (`case_type_unknown`). uc-251 runs it end to end.

## Activity

`GET /v1/activity` (c-201, `api/routers/activity.py`, `store/activity.py`) lists everything that happened as one
paged list, newest first: one SQL union over the tables that record each kind, so the console neither merges lists
nor counts rows itself. Filters: `kind`, `status` and `source` (`type:id`) repeat; `team` is the selected team, `all`
for every team the caller is in, or one of them; `since` and `until` bound `at`. `facets.kind` and `facets.status`
count under the other filters, which is what a page's "View activity (n)" button reads. `case` (c-341) keeps one
case's rows: its own entries, and every row about a run or chat it links (the run, the email that started it, decisions
on its Human Tasks, its tool calls), in the case's team only; another team's case is 404.

| Kind | Read from | status | Read where |
|---|---|---|---|
| `workflow_run` | `engine_runs` | queued, running: running; waiting; succeeded: done; failed, cancelled: failed | workflows.view |
| `agent_run` | `graph_threads` not a chat, not a child thread | busy: running; interrupted: waiting; error: failed; else done | agents.view |
| `chat` | `graph_threads` with `meta.chat` | as agent_run | chat.view: one's own while chatThreadsOwnerOnly is on |
| `email` | `trigger_events` | started: done; duplicate, filtered, daily_cap, cursor_reset: skipped | workflows.view |
| `decision` | `engine_work` resume rows, `review_decisions` | done; `outcome` is the decision | reviews.view |
| `case` | `case_events` with their case: opened, a run or chat added, a note, a field changed, a case linked (a `decision` entry is left out, since the decision is its own row) | done; `outcome` is the entry's kind | cases.view |
| `tool_call` | `thread_events` tool_end (chats, agent runs); `engine_steps` whose node type calls the tool gateway (one row per attempt) | ok: done; gated: waiting; running; else failed | as the chat or agent run it is in; workflows.view for a workflow's |
| `system_workflow` | `service_events` system_workflow.updated and update_available, with the update's publish request (c-317) | updated and approved: done; in review (pending, returned): waiting; rejected: skipped; update_available (a team's own version kept): waiting. `outcome` is the request's status now, or update_available; `ref` is the review while it waits, else the workflow | workflows.view in any team asked about: a shipped system workflow belongs to no team, so `teamId` is null |
| `reminder` | `service_events` task.reminder (c-277), with the run | waiting while the run still waits, else done; `outcome` is reminded; the title names the step and the hours it had waited; `ref` is the review | reviews.view |

Each row is `{id, kind, title, status, outcome, teamId, source {type, id, name}, actor {kind, id, name}, at, ref {kind,
id}}`. A channel source is the record's id: an email's mailbox (`mbx_…`, the address when the record is gone) and a
widget chat's deployment (`wd_…`); a console chat's source is its agent. A person's `actor.name` is their display name from platform-service (`GET /v1/people-names`, read once a minute); an
API key's (`key:<id>`) is its label (`GET /v1/api-key-summaries`). Workflow steps journaled before agents migration 0057 carry no node type and are not listed as tool calls.

When a mailbox refuses the stored read position (tools-service's key changed, or the cursor predates sealing), the
trigger starts reading again from now and adds a `cursor_reset` row, "Mail since the last read was skipped", to the
workflow's trigger list and to Activity. Mail that arrived between the last read and the reset is not read; a person
has to look in the mailbox for it. Test:
`tests/engine/test_email_trigger_graph.py::test_a_refused_cursor_starts_a_fresh_delta_instead_of_failing_every_poll`.

## Channels

`GET /v1/channels` (c-245, `api/routers/channel_list.py`, `store/channel_list.py`) lists each way work reaches an
agent or workflow, under the id of the record that holds it, with what it serves, a health dot and its traffic.

| Type | Record | Serves | Health | Traffic counted from |
|---|---|---|---|---|
| `email` | mailbox `mbx_…` | the live workflows whose Email received trigger names it | warn when not read for 5 minutes | `trigger_events` |
| `chat` | widget deployment `wd_…` | its agent, pinned or Latest | error with no allowed websites | `graph_threads.deployment_id` |
| `api` | platform-service API key `key_…` (c-246) | the key's target, or none | error when disabled or expired, warn when expiring in under 14 days or not scoped | runs whose `created_by` and threads whose `meta.startedBy` is `key:<id>` |

`PATCH /v1/channels/{id}` is the one route that renames, pauses or resumes a channel, or changes a chat channel's
allowed websites or what it serves (a version, or Latest); `POST /v1/channels/{id}/retire` retires a chat channel, and
a retired one answers 409 `widget_retired` to any change. `POST /v1/channels` with `type: chat` connects a chat channel
(the agent pinned at its published version, on exact origins) and answers 201 with its row. `GET /v1/channels` takes
`agentId` (the channels serving that agent) and `includeRetired` (retired chat channels too, health `idle`, "Retired");
a chat row carries `embed` with the agent, the version it answers from, its origins, when it retired and its active
mint keys, and its conversations are `activity7d` and `lastActivityAt` (c-339). `POST` and `GET /v1/widget-deployments`
are deprecated aliases until the console's adapter moves; mint keys, server sessions and preview sessions stay there.

API rows come from platform-service's `GET /v1/api-key-summaries` on every list; a revoked key is not listed, and a
key changes in Settings, so `canEdit` is false and a PATCH answers 409. A scoped key starts only its target: a live run
of that workflow (on its pinned version, when it pins one) or a thread on that agent, else 403 `key_target`
(`auth.require_key_reaches`). The target comes from introspection only. A scoped key still reads what its team reads.

## Service events

`POST /v1/events` (c-258, `api/routers/service_events.py`, `api/service_events.py`, `store/service_events.py`) is how
one service makes something happen without calling another: a service token with `events:emit` reports `{name, key,
teamId, actor?, payload}`, and the tenant's handler for the event runs on that team with the payload as input. Run key
`<name>:<key>`: a repeat returns the run, a repeat after it failed starts attempt n (`<name>:<key>:n`). With `actor`,
the run's `created_by` is that person and `engine_runs.started_via` the event, so rules on who started a run read the
person and startedBy shows `via` the event. The handlers are ordinary workflows shipped in `seed/event_workflows.json`
(tool_access_request, system_extract, file_deleted_purge): each is published to a tenant, live and owned by no team,
on its first event, and from then on it is edited and published through review under the shared-workflow rule (an
admin, or whoever saved it) and run by hand by anyone who may run workflows. The handler is found by its workflow id
and must belong to no team, so a team's workflow with the same trigger, or one saved under the same id, never fires.
The approval token's `system` claim is true for a handler's runs, and tools-service applies a tool access decision
only from tool_access_request's. A service reports only the events it owns in the catalogue
(`EVENT_OWNERS`, 403 `event_not_owned`), and the event's team is the one its token names (403 `team_mismatch`).
Services write their events through `ops_store.outbox` in the same transaction as the change, and its relay delivers
them at least once.

## Deciding and combining in a workflow

`ops.flow.switch` (c-259) has one named way out per case, each a rule set in If's language (`eq`, `gt`, `contains`,
`exists`, `empty` over any mapping); the first case whose rules hold wins and `otherwise` takes the rest. A way it does
not name cannot be wired, and a name used twice fails the definition's checks. `ops.data.combine` merges the same
fields from named sources: each field takes the first source (in `fields[].from` order, else the sources' order) with a
non-empty value, `sources` says which, and every field the sources disagree on is listed in `conflicts` with each
value; text compares without case or spacing and numbers as numbers (1,200.00 is 1200). The Email received trigger also
stores the email's text as `email-body.txt` (purpose `email_body`) and passes it as `bodyFile`, so a body-only email is
read through Extract from file like an attachment. uc-226 runs all of it on one workflow. When no case holds,
`otherwise` carries `tried`: each case's rule with the value it read, so a run page shows why none matched.

## Branches and the Join

A step's way out may connect to several steps, which then run together: a fork. `ops.flow.join` (c-278) is where they
meet. It has the one input every step has, taking a connection from each branch, and goes on once with
`{<step id>: <that step's output>}` for each step connected to it; a step that took another way out or never ran is
null. The compiler adds a Join as a LangGraph deferred node (`node_types.py` `deferred`, `compiler.py`), so it runs
once, when no other step of the run can still run: it waits for every branch that will arrive and never for one an If
or Switch sent elsewhere, and it also waits for unrelated branches of the same run. Without a Join, a step where two
branches meet runs once per branch; `definition.advise` warns of it (`fork_without_join`) on validate and save, and a
Join reached by fewer than two steps fails validation (`join_needs_branches`). Tests: `ops_engine/tests/test_join.py`;
uc-400.

## Step output shapes

Each step declares its output by the port it leaves by, before the workflow has run (c-353): `ops_engine/shapes.py`
builds a JSON Schema per port from the type (Email received, Open case, End), the step's settings (a request's
`inputSchema`, Set's values, an agent's `outputSchema`, an AI step's answer schema) or a lookup (Extract's document type
fields; a tool's response schema, which tools-service keeps from an OpenAPI import, else infers from the example
response). A closed shape (`additionalProperties: false`) lists every key; an open one lets more arrive.
`GET /v1/workflows/definitions/{id}/versions/{version}/shapes` serves them per saved version (`api/step_shapes.py`), and
validate and save warn `unknown_output_field` where a mapping reads a field a step's closed shapes never output.
`ops_engine/tests/test_output_shapes.py` runs every built type's executor on fake ports and holds what it writes to its
declared shape; uc-401.

## Run workflow waiting for its children

`ops.action.workflow` with `wait` on (c-263) pauses the parent until every child it started has ended, then leaves by
`done` with `{workflowId, count, children: [{index, runId, outcome, output}], counts}` in item order; a failed child is
a row with its outcome and the parent goes on. `batchSize` starts that many at once and the next as one ends.
`timeoutHours` adds a `timeout` port, taken with the children that ended collected and the rest named (`waiting` run
ids, `notStarted`). A child output over 64 KB is left out and named by its run id. The step's attempt stays `waiting`
while paused and is reused on resume (`compiler.py` `_wait_for_children`); `RunStore.settle_parents` queues a resume
keyed by the child that ended, the worker takes it only for the step the parent waits at, and the timeout is keyed
delayed work. `RunPort.children` reads the children in one query by run key prefix. The node type view adds
`outputsUnless` (`started` goes when `wait` is on); `"*"` in `optionalOutputs` means any value set. Tests:
`ops_engine/tests/test_wait_for_children.py`, `tests/engine/test_parent_wakes_on_children.py`; uc-402.

## Wait and reminders

`ops.flow.wait` (c-277) pauses a run for `seconds`, or with `mode: until` until an ISO date or date and time read from
an earlier step (a date alone is midnight UTC, no offset is UTC), then goes on by `out` with `{seconds}` or `{until}`.
A date already past goes on at once without pausing; a value that is not a date leaves by `error`, a port only until
mode has, with `{error, code: not_a_date, value}`. The pause is an interrupt carrying `wakeAfterSeconds`; the worker
queues one delayed `timeout` row keyed by run, step and iteration at the first pause (`worker.py` `_waiting`), the same
wake-up Run workflow's `timeoutHours` uses, so no worker is held and a restart loses nothing.

A Human review with `remindEveryHours` queues `remind` work keyed by run, step, iteration and count, timed from the
review's `openedAt`. When it falls due and the run still waits at that review (the same interrupt id), the worker
records a `reminded` run event and the host reports `task.reminder` (`api/service_events.py` `reminders`, through
`deliver`, which `emit` also uses) with the run, workflow, step, title, count and hours waited, then queues the next;
it never resumes the graph. A decided review takes no reminder and queues none. What a reminder does next is a
workflow a team adds for the event; none is shipped, so it is recorded unhandled. Activity lists each as `reminder`.
Tests: `tests/engine/test_wait_and_reminders.py`; uc-403.

## Archiving a workflow

`POST /v1/workflows/definitions/{id}/archive` and `/restore` (c-274, `api/routers/engine.py`) set and clear `archived_at`
on every version of the workflow. An archived workflow starts no run, live, test or as a child: `RunStore.create`
refuses it under the same lock a pause takes (409 `workflow_archived`). The mailbox listener and the channel list read
live versions only when not archived, so a trigger no longer serves it. Both workflow lists leave it out unless
`status=archived` is asked for, and their status facet still counts it. Runs already started keep going, and its
versions and runs are kept; restoring brings back the version that served it, live or paused. Who may delete the
workflow (`workflows.delete`) may archive it. Tests: `tests/api/test_workflow_archive.py`; uc-252.

## A run's status

A run's status says what happened, read from where it ended and from the runs it started:

| Status | When |
|---|---|
| queued, running | Not started yet, or a step is under way |
| waiting | A step waits on a person (`waiting` names it), or its own steps reached an End while a run it started waits on a person (`waiting` is empty) |
| running, with an outcome | Its own steps reached an End while a run it started is still going |
| succeeded | It reached an End and every run it started has ended |
| failed | It reached an End whose `result` is `failed` (`error` names that End), or a step failed past its retries; runs it started keep going on their own |
| cancelled | Someone cancelled it |

An End's `result` (`succeeded` by default) is the builder's to set: an End for what went wrong is `failed`, whatever its
outcome is named. A parent settles when its last unfinished run ends, decided or cancelled
(`RunStore.settle_parents`), and up the chain to its own parent. Tests:
`tests/engine/test_start_workflow.py::test_a_parent_waits_while_a_run_it_started_waits_on_a_person_and_succeeds_when_the_last_ends`
and `::test_an_end_marked_failed_fails_the_run_and_names_where_it_ended`; uc-249 #5 to #7.
A parent's unfinished runs are found by two lookups on `(tenant_id, created_by, status)`, one for a run waiting on a
person and one for a run under way, so a parent that started hundreds of runs is not reread in full on each change
(migration 0066). The runs list reads one team's runs through `(tenant_id, team_id, created_at)` and, filtered by status,
`(tenant_id, team_id, status, created_at)`. Tests: `tests/engine/test_runs_list_indexes.py`, which asks PostgreSQL for
the list query's plan. A court order notice read below the floor goes to Check the read in the court order read workflow
(`Read one levy document`) and, approved, reaches its case
per debtor through the read's records: a read of several records has no single read's fields for the check to edit
(`tests/engine/test_levy_definitions.py::test_a_doubtful_levy_notice_checked_by_a_person_still_starts_a_levy_case_per_debtor`, c-313).

## Testing an agent and its replies

| Part | Detail |
|---|---|
| Test thread | `POST /chat/threads` with `test: true` runs the agent's newest version, draft included; with `testVersion` a saved version instead, which is how the test panel's Compare asks two versions one question (c-284, c-286). Test threads are left out of counts and memory. |
| Reply usage | Each reply in a thread carries `usage`: model calls, tokens, cost and seconds, joined from the model call records and the run's start and finish (c-286). |
| Who may decide | A review step's `requestedBy` names who asked for a decision when the run's starter did not (an event a service reported); they decide only while `requesterMayDecide` allows, as the starter does (tick 29). |
| Task assist | A typed task's assist is recorded pending at the pause and written beside it by its own prompt port, gated by `taskAssist` alone (c-302); a stopping worker waits for it. |

## Microsoft 365 mailboxes

A mailbox with `provider: graph` (c-228) holds the team's own app registration: `graphTenantId`, `graphClientId`, and
`passwordSecret`, the name of the Secrets-page secret with the client secret; saving one without all three is 422
`mailbox_incomplete`. The app needs the Mail.Read and Mail.Send application permissions with an admin's consent, scoped to
the one mailbox with an application access policy
(<https://learn.microsoft.com/en-us/graph/auth-limit-mailbox-access>). The trigger reads it through tools-service like
an IMAP mailbox (Graph's delta link is the cursor, its JSON items are parsed here), and `sender: graph` replies as the
mailbox through Graph. The deployment-wide `OPS_GRAPH_*` settings stay for the operator's demo mailbox; a record's own
registration is what a team's mailbox uses.

## What differs from the specs

| Spec | Here |
|---|---|
| 14 R10–R15 sessions and turns under `/v1/chat/sessions` | The console's thread routes (`/chat/*`, also under `/v1/chat/*`) |
| 07 CD-11 AI SDK UI message stream | The console's `ChatStreamEvent` frames, which map one to one |
| 15 §5 resume stream after approval | The approval request runs the continuation and stores it as a new message; the console re-fetches |
| 13 step-up token verified | Any non-empty token is accepted and recorded on the interrupt |
| c-057 `levy-hold` as a child run started by the Hold decision | The hold runs as the `place_hold` step of the `levy-case` thread itself: the approval token is bound to the thread it was minted on (`tools-service/policy/gateway.rego`), so a child run could not present it. The `levy-intake` definition opens one `levy-case` child per matched customer instead |
| 07 CD-7 no self-approval | Not enforced: the dev auth mode has one user |
| 17 §2 schema `runtime` | Tables in `public`, so the API tests run on SQLite |
| 17 §4 generated `ops_contracts` | Hand-written models mirroring `apps/console/src/lib/types/chat.ts` |
