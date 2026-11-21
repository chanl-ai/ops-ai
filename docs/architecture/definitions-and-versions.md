# Definitions and versions

Status: current, written 2026-10-10 from the experiment ledger, links updated 2026-10-16; every decision is an option until it is confirmed.

The definition format and portability are in [ADR-0003](decisions/workflow-definition-format.md); the node catalogue
in [workflow nodes](../design/workflows/workflow-nodes.md) §3; edit classes, registry and release in
[agents and workflows](../console/agents-and-workflows.md) and [aDR-0012 Assurance: governance and testing as one system](decisions/assurance.md).

## Lifecycle

| Stage | What happens | Call | In code |
|---|---|---|---|
| Draft | Nodes, edges and review policies saved as JSON on every change | `PUT /v1/workflows/{id}/draft` | No |
| Validate | Checked against the node catalogue: unknown node, missing edge, unpublished agent pinned, a side effect before its approval node, invalid SLA durations | `POST …/validate` | `validate()` runs inside publish |
| Test | Runs the draft once with a sample input; pauses auto-approved; returns the node sequence and output | `POST …/test` | No |
| Publish | Compiles an engine-neutral plan with a digest, pins every agent, tool and review policy, runs the suite, opens a review | `POST …/publish` | `POST /v1/graphs/{name}/versions` validates and stores a version with no suite and no review |
| Pointer | Moves `wf_d@production` to a version; rollback is the same call; only new threads see it | `POST …/pointer` | No: a new thread takes the version it names, or the latest |
| Thread pin | The thread stores version and digest at creation and keeps them until it ends | `POST /v1/threads` | Yes |
| Migrate | Moves a waiting thread to another version, explicitly | `POST /v1/threads/{id}/migrate` | Yes, with a node-name check |

An agent follows the same path: publish compiles a one-node plan (`ag_x@7`), and deployments name its pointer.

### A workflow's working copy

The workflow editor (`/build/workflows/definitions/<id>`) edits a working copy, not a version. Each change saves the
copy a second later with the server's checks, failing ones included (`PUT /v1/workflows/definitions/{id}/working-copy`,
`engine_working_copies`, agents migration 0121), and makes no version. Publishing is one call
(`POST …/publish-requests` with `baseVersion` and `baseDigest`): it refuses on every blocker before anything is made,
then makes the next version from the copy and opens its publish request; the team's publish policy lets a change of
step positions alone go live with no review (`publish_policy.is_major`). The copy is removed only once the request is
open. No route makes a version from the copy without publishing it.

| Rule | Where |
|---|---|
| A save names the copy it was made on (`saveBase` of the view: the copy, or the newest version without one) and is refused with 409 `stale_base` otherwise, naming who saved first | `DefinitionStore.put_working_copy` compares under a row lock in the write's transaction, reading the copy through `team_visible` (the table is `TEAM_OWNED`); the answer is `refuse_stale` (`store/agent_registry.py`), as for agents and skills |
| A copy made on an older version than the newest (a version saved since through `POST …/definitions`, the SDK or CLI `workflows save`) is outdated: its saves and its publish are refused with 409 `stale_base` naming that version. The view returns it as `outdatedCopy` with who saved the newer version and when, never hiding it; the editor says so, names whose copy it is, holds autosave and lets the person open the copy read-only until they choose to start from the newer version. A save on the newest version by someone other than the copy's author is refused with 409 `stale_base` naming the copy and its author, unless it names that copy (`replacesDigest`, the `digest` of `outdatedCopy`), which is how the editor's start-over replaces it | `DefinitionStore.put_working_copy`, `engine.py` `definition_view`, `_publish_copy`; the definition page |
| What stops a publish is one list, `engine_lifecycle.blockers`, read through `engine.py` `_publishable`: a publish request already open (409 `review_open`), a copy equal to a stored version that is live or paused (409 `not_a_draft`), error checks, AI steps while the team has them off, an email trigger on a mailbox the publisher may not watch, accounts the team does not have, and a document type that cannot be pinned. The publish right and a stale base are refused before it. The preview lists all of them and the publish refuses on the first before any version is made; the policy reads that open the request (publishReview and the review deadline, `engine_lifecycle.policy_reads`) are made before the version too, so a failed read leaves the versions and the copy as they were and the same publish can be sent again, so the dialog never shows fewer problems than the publish refuses on; Publish and Send for review stay disabled while one is listed | `engine_lifecycle.blockers`, `engine.py` `_publishable`, `_publish_copy`, `publish_preview`; `publish-state.ts` |
| An autosave locks the newest version row only, a few columns, and the copy; a publish locks every row of the workflow and also takes the autosave's own newest-row statement, because on SQL Server a lock read through another index does not block it. Every lock goes through `ops_store.dialect.locked` (FOR UPDATE on PostgreSQL, UPDLOCK and ROWLOCK on SQL Server). After the wait SQL Server reads the new version and refuses the save as stale; PostgreSQL writes it on the version it waited on, so it shows as an outdated copy. `test_stale_saves.py` holds a real publish and an older row's lock in a second session on both databases | `DefinitionStore.put_working_copy`, `publish`, `go_live`, `delete_draft` |
| A refused workflow save is never sent again, even after the person's own save from another tab: the canvas is one field, so a resend would replace that tab's whole canvas. The page says who saved and offers Reload. Agents resend their own (field-merged) saves | `use-working-copy.ts`; `lib/save-base.ts` for agents |
| Publish waits while a change on screen is unsaved, so the version and its preview are made from what is on screen | `lifecycle.tsx`, the definition page's `saving` |
| A copy equal to an older, superseded version (a restore) publishes as a new draft version; the copy is removed only after the version is stored. A save that waited on the publish's lock ends differently on each database: PostgreSQL writes it on the version it waited on, kept as an outdated copy behind the new version, and SQL Server refuses it as stale, so the editor reloads and saves again. Either way no acknowledged save is lost. One definition may sit at several versions (agents migration 0122) | `DefinitionStore.publish(reopen=True)`, `rebase_working_copy` |
| The publish preview decides on the copy as its version will store it (parsed, defaults filled), as the publish does | `engine.py` `publish_preview` |
| Who may save: `workflows.edit`; who may publish: `workflows.publish`, both through `can()`. The view's working copy and `GET …/diff` need `workflows.view`; the rest of the view does not check it yet | `engine_lifecycle.require_rights`, `engine.py` `definition_view`, `diff_definitions` |
| What changed between two versions, the live one or the copy, every setting old and new | `ops_engine/diff.py`; `GET …/diff?from=&to=`; the reviewer's change list reads the same diff |

## The pin

| Rule | Detail |
|---|---|
| Digest | SHA-256 of the canonical definition JSON without the version number; a digest names one definition forever, so the compile cache needs no invalidation |
| Rebuild per run | Every run, resume and state read compiles the thread's pinned version from stored JSON and refuses if the stored digest no longer matches the thread's |
| New threads | Start on the version the pointer names |
| Old versions stay alive | A version stays compiled in each process while any thread pins it. Retiring it means waiting until no thread pins it, or migrating those threads |
| Stable names | Node names and state keys are part of the contract between versions: keep node names stable and add state keys rather than renaming |

A pinned skill is copied onto the agent version with everything a turn needs: its text, guardrail lines, the inputs
it asks for and, for a skill with steps, the steps, exits, results, not-when line and success checks
(`services/agents-service/src/ops_agents/api/skills.py`, `snapshot`). A pin saved before steps existed has none of
those keys and loads as text, as it did. An agent version also stores its `brief`, `promptMode` and `patterns` when it
has them; a version without them is served from `instructions` unchanged.

## Template copies

A team's agent, skill, workflow, case type or task type made from a plugin's template is an ordinary record with its
own versions; its `template_copies` row names the template and keeps the base the copy was last merged against
(ADR-0018, [decisions/template-copy-updates.md](decisions/template-copy-updates.md)).

| Rule | Detail |
|---|---|
| An update is one save | Taken through the kind's own save, so a published version, or a draft a publish request names, never changes; an open draft nobody asked to publish is merged into |
| Field by field | Kept where only the team edited, taken where only the template changed, a choice where both did, kept as the team's by default (`ops_service_kit.template_merge`) |
| The base never moves on a save | Only an install or an update writes it, and it is the template's body, never the merged result, so a conflict kept as the team's is asked about again only when the template changes that field again |
| Detach | The copy becomes the team's own and is offered no update |
| Case and task types | A copy takes an id of its own (`ct_…`, `tt_…`), since types are keyed by team and id and two packs may ship the same id; it is made and saved through the type's own create and draft routes, starts as draft version 1, and merges each case field or task action by its key |
| Document types | documents-service keeps the same link (`documents_template_copies`) and compares each extracted field by its key; a type has no draft, so a taken update is the type's next version at once (`appliesNow`), and versions a workflow pinned keep reading as they were |

## What happens without the pin

From [pause-survives-graph-change](../services/agents-service/experiments/pause-survives-graph-change.md): a thread
paused on v1 was resumed directly on v2 (a node added after `draft`, `grade` renamed) and on v3 (`human` renamed).

| Resumed on | LangGraph's behaviour | Effect on the case |
|---|---|---|
| v2, paused node still exists | No error | The case finished on a graph it did not start on, with nothing recording the switch |
| v3, paused node renamed | No error; the thread reads as finished (`next=()`, no pending interrupt) | The decision was never applied and no reply was sent; the case ended with `status=None` |

Pinning is therefore required. Only edits downstream of the pause, or to the paused node itself, change a resume;
edits upstream never do. A test of the pin must assert where each node ran (the `node@vN` provenance tag), because a
test whose edits sit upstream of the pause passes with or without the pin.

## Migrate

| Rule | Detail |
|---|---|
| When | Only while the thread waits on an interrupt (409 `not_waiting` otherwise) |
| Check today | Every node the thread waits in must exist under the same name in the target (409 `node_missing`) |
| Gap | A name check passes even when the target changed what the waiting node does or what follows it. A migration review must diff the definitions from the waiting node onward |
| Code graphs | `agent_wrapper`, `simple_workflow` and `complex_workflow` are code with no versions; migrate refuses them |

## Definition format today

`{name, version, entry, nodes[{id, kind, config}], edges[{source, target}]}` with node kinds `agent`, `extract`,
`collect`, `draft`, `grade`, `condition`, `human`, `tool`, `end`. A `human` node's config carries its SLA settings
([human-in-the-loop.md](human-in-the-loop.md)). The catalogue in spec 16 has fifteen kinds; the gap between the two
is closed when the first real workflows are drawn against it ([delivery.md](delivery.md)).

## Pausing an agent

Pausing drains, it does not cut. A turn already under way finishes on the definition it started with, including a
turn paused at an approval that is decided after the pause; the catalogue keeps a paused agent's definition aside
for that, and its `agent:<id>` graph stays compiled though `GET /v1/graphs` stops listing it. New work is refused at
once with 409 `agent_paused` and a reason: a new message in an open conversation, a new conversation, a new turn on
the shared wrapper or the agent's graph, and a new thread on `agent:<id>`. Resuming serves the published version
again. A deleted agent refuses new threads with 400 (uc-018).

## Routing

A `condition` node chooses its next node by `rule`:

| Rule | Config | Chooses |
|---|---|---|
| `score_gate` | `threshold`, `max_attempts`, `pass`, `fail` | `pass` once the grade reaches the threshold or attempts run out |
| `decision` | `approved`, `rejected` | By the last review decision |
| `route` | `routes: [{when: {field, op, value}, to}]`, `default` | The first route whose `when` holds, else `default` |
| `option` | `<option>: <node>` per option, `default` | By the option the review was decided with (a `human` step with `options`, e.g. a court order case's `hold` and `flag`) |
| `outcome` | `ok`, `failed` | `failed` when the last tool call failed (`tool_error` set, e.g. the bank's 422 on a hold), else `ok` |

A `when` compares one state field: `eq`, `ne`, `in` (a list), and `lt`, `le`, `gt`, `ge` on numbers. Fields are the
scalar state fields plus `email.sender`, `email.subject`, `email.body` and `decision.decision`
(`definition.ROUTE_FIELDS`). A field with no value yet matches nothing, so the next route or the default is taken.

Intake from a notice adds three node kinds: `extract_records` (`schema`) reads the email and its attachments'
text layers into typed records (`records`, `record_count`); `match` (`search`, `customer`, `account`,
`min_address_chars`) runs once per record, fanned out by Send, and names a customer a match only when the name matches
and the address (a substring of at least `min_address_chars`) or the whole last four of the SSN matches, a name alone
being a `candidate` for a person to read; `open_cases` (`workflow`) starts one child thread per match through the
workflow runner, with the record, customer and accounts as its state, and lists them in `children`; with records but no
match it ends `candidates_only`, never `cases_opened`. Tool inputs are renamed to each operation's own input names
(`arguments_for`: `customerId` reaches an import of `/customers/{customer_id}` as `customer_id`). A `human` step
with `options` (names, or `{name, editable: [graph input names]}`) is decided with one of them (`POST
/reviews/{id}/decision` with `decision: <option>` and `inputs`): the interrupt declares, for every option, its call
and the inputs a reviewer may set, taken from the operation's own input schema (name as the operation spells it,
type, required, bounds) with the proposed value as the default, and decide refuses an input the declaration does
not name or type. The decision is recorded as `approved` with the option beside it (`option` on the review and on
the resume), so Reviews keeps its statuses; the token is minted for the chosen call alone, which the next `tool`
node runs on the same thread: the gateway's policy binds a token to the thread it was minted on, so the hold is
placed on the case thread itself, not on a child run. A finished child writes its outcome to the parent's meta,
into the parent's checkpoint (`values.children`, under the parent's lease, as the node it finished at) and as a
`child_finished` event; `GET /v1/threads/{id}/state` and `GET /runs/{id}` read the meta over the values, and
`GET /runs?parent=<id>` lists one thread's children.

Publishing rejects what could fail at run time: an unknown field or operator, an ordered comparison on a non-number,
a target that is not a node, and a missing `default`. Requiring the default means some route always matches. In the
console a branch or router with several outgoing edges compiles to a `route` condition: `data.routes` maps each edge's
handle to its `when`, and `data.defaultRoute` names the default handle (`workflow_registry._route_condition`).

## Costs

| Item | Measured |
|---|---|
| Compile, no cache | 2.64 ms median for v1, 2.91 ms for v2, over 50 compiles |
| Cache hit, including parsing and hashing the stored JSON | 0.056 ms |
| Storage | One row per version in `graph_versions`; `version` and `digest` columns on `graph_threads` |
| Memory | One compiled graph per pinned version per process |
