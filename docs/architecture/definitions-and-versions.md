# Definitions and versions

Status: current, written 2026-10-10 from the experiment ledger; every decision is an option until the owner confirms it.

The definition format and portability are in [ADR-0003](decisions/workflow-definition-format.md); the node catalogue
in [interpreter-and-nodes](../specs/interpreter-and-nodes.md) §3; edit classes, registry and release in
[agent-builder](../specs/agent-builder.md) and [evals-and-release](../specs/evals-and-release.md).

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

## The pin

| Rule | Detail |
|---|---|
| Digest | SHA-256 of the canonical definition JSON without the version number; a digest names one definition forever, so the compile cache needs no invalidation |
| Rebuild per run | Every run, resume and state read compiles the thread's pinned version from stored JSON and refuses if the stored digest no longer matches the thread's |
| New threads | Start on the version the pointer names |
| Old versions stay alive | A version stays compiled in each process while any thread pins it. Retiring it means waiting until no thread pins it, or migrating those threads |
| Stable names | Node names and state keys are part of the contract between versions: keep node names stable and add state keys rather than renaming |

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

A `when` compares one state field: `eq`, `ne`, `in` (a list), and `lt`, `le`, `gt`, `ge` on numbers. Fields are the
scalar state fields plus `email.sender`, `email.subject`, `email.body` and `decision.decision`
(`definition.ROUTE_FIELDS`). A field with no value yet matches nothing, so the next route or the default is taken.

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
