# Words and entities

Status: current, checked against the code on 2026-11-18. Designed and not built: the plan as its own engine-neutral object, and the graph version as `act` in delegation tokens. The decided design is [workflows and agents](../design/workflows/workflows-and-agents.md).

## Glossary

| Word | Meaning | In code |
|---|---|---|
| Graph | What runs: nodes and edges. An agent is a graph with one agent node and an approval node; a workflow is a larger graph. Both compile from what a builder saves in the console | `ops_agents/graphs/`; the list is in [runtime.md](runtime.md#graphs) |
| Definition | The JSON a builder saves: `{name, version, entry, nodes[{id, kind, config}], edges[{source, target}]}`. Node kinds today: agent, extract, collect, draft, grade, condition, human, tool, end, pass, agent_turn, extract_records, match, open_cases | `graphs/definition.py` |
| Plan | What publish produces from a definition: engine-neutral JSON with a digest. Each engine builds its graph from it | Designed; today the stored definition is the plan |
| Digest | SHA-256 of the canonical definition JSON without its version number. Names one definition forever | `WorkflowDefinition.digest()` |
| Version | An immutable published definition: `(name, version, digest)` | `graph_versions` |
| Pointer | A name such as `wf_d@production` for one version. Deployments name pointers; moving the pointer is how a version goes live and how it rolls back | In code for workflows (`POST /v1/workflows/{id}/pointer`; new threads start on the pointer); deployments still name a graph, not a pointer |
| Thread | One conversation or one case. Holds the graph's saved state and is pinned to one version and digest until it ends or is migrated | `graph_threads` |
| External key | The channel's own id for a thread: `deployment id:Message-ID`, an event id, a conversation id. The same key finds the same thread | `graph_threads.external_key`, unique |
| Run | One execution of a graph on a thread, from an input or a resume until it finishes, pauses or fails. One active run per thread | `graph_runs`, kinds `input`, `resume`, `recovery`, plus `sla` and `lease` journal rows |
| Node | One step of a graph. LangGraph saves state between nodes, never inside one, so a node killed mid-way runs again from its start | LangGraph node |
| Interrupt | The graph stops and asks a person. State is saved; nothing runs while it waits. A gating interrupt carries `call = {tool, input, step}`, the exact call it gates | `langgraph.types.interrupt` |
| Resume | The person's answer goes back in and the graph continues from the interrupt. A review-owned step resumes only through `POST /reviews/{threadId}/decision`; `runs/stream` answers 409 `resume_via_review` for it, and a plain chat question resumes through `runs` | `Command(resume=...)` |
| Review | The people side of a pause: what is needed, who may decide, by when. Also used for publish requests and manual handling | Designed for the `ops_hitl` package; today `api/hitl_facade.py` serves runtime pauses as the console's Reviews, with `review_decisions` and `review_approvals` |
| Approval token | A signed token bound to `{thread, step, tool, inputHash, approvers, exp}`. Covers exactly one call | HS256 today, signed by `packages/ops_policy`; facts in [identity-and-tenancy.md](identity-and-tenancy.md#approval-and-step-up-token-facts) |
| Step-up | A re-authentication by the approver in the last 5 minutes. Authenticates the approver; approves nothing by itself | `POST /v1/auth/step-up`; verified for signature, subject and age when the operation's policy or the workspace's `stepUp` policy asks |
| Deployment | One row: a graph on a channel (`widget`, `api` or `mcp`) with its multitask default, paused flag and budget | `deployments` |
| Journal | The record of every run and step: who, which version, which node, which tool call, the outcome. Kept after checkpoints are pruned | `engine_steps` for workflow runs and `graph_runs` for threads today; designed as an append-only table |
| Checkpoint | LangGraph's saved state after a superstep | `ops_checkpoints`, `ops_checkpoint_writes` |
| Lease | The per-thread lock a run holds: owner, run id, heartbeat, expiry, generation | `thread_leases` |
| Generation | A counter on the lease that rises on every acquire or takeover and never restarts | `thread_leases.generation` |
| Fence | The highest generation a receiver has seen for a thread. A write with a lower generation is refused | `ops_checkpoint_fences`, `gateway_fences` |
| Sweeper | A background task that takes over expired leases and continues the thread from its last checkpoint | `ops_agents/api/sweeper.py` |
| Timer | A row with a due time for an SLA warn, breach or maximum wait. Fired only through `fire(thread, timer)` | `timers`, `ops_agents/api/timers.py` |
| Process principal | A non-human identity owned by a team, used as `sub` for runs nobody started in person (a mailbox, a schedule) | Designed |
| Delegation token | A short-lived token with `sub` (who the work is for) and `act` (who does it: the graph version) | Partial: acting-for tokens that platform-service signs per person and team travel as `X-Acting-For`; `act` as the graph version is designed |
| Side-effect class | `none`, `read`, `write` idempotent, `write` not idempotent, `money`. Sets retries and whether a token is needed | Access class in the tools registry: `read` or `write`; how many people approve a write is the operation's approval policy (`approvers` 1 or 2) |
| Manual handling | Where a failed or stuck run lands for a person. No run ends silently | Reached by route-to-people (built-in `manual_handling` step); from retries and the recursion limit, designed |
| Budget | Caps on a thread's model calls, tokens and cost. A spent budget pauses the thread for a person | models-service `model_budgets`, set by agents-service (`api/budgets.py`); each call in its call log |

## Entities and how they relate

| Entity | Belongs to | Has | Key rule |
|---|---|---|---|
| Agent | Team | Draft, versions | Deploys as a one-node graph; same pointer and review rules as a workflow |
| Workflow | Team | Draft, versions | A version is immutable once published |
| Version | Agent or workflow | Definition, digest, plan | Pins every agent, tool and review policy it uses |
| Pointer | Agent or workflow | One version per environment | The only call that changes which version new threads get |
| Deployment | Team | One pointer, one channel, settings | Pausing it stops new threads; open threads finish |
| Thread | Deployment (or none, for direct API use) | Version and digest, state, external key, parent thread | One active run at a time; keeps its version until it ends or is migrated |
| Run | Thread | Input or decision, events, status, owner, generation | Holds the thread's lease while it runs |
| Interrupt | Run, at one node | Payload, gated call, SLA block | Resumes once per decision |
| Review | Interrupt, publish request or manual-handling item | Needs, eligible approvers, due time, decisions | The requester decides too, unless the team turned the two-person rule on (`requesterMayDecide` off) and they are not an Admin of the team |
| Approval token | Review decision | Binding to one call's input hash | Expires in 15 minutes; any edit to the input invalidates it |
| Timer | Interrupt and round | Kind, due time, claim | Fires at most once per interrupt and round |
| Tool call | Run and step | Input hash, decision, reasons, outcome | One effect per `(thread, step, tool, inputHash)` |
| Journal row | Run | Who, version, node, call ids, outcome | Kept for the tenant's retention; never edited |

```mermaid
erDiagram
  WORKFLOW ||--o{ VERSION : publishes
  VERSION ||--o{ POINTER : "named by"
  POINTER ||--o{ DEPLOYMENT : "served by"
  DEPLOYMENT ||--o{ THREAD : starts
  VERSION ||--o{ THREAD : pins
  THREAD ||--o{ RUN : has
  THREAD ||--o| LEASE : "locked by"
  RUN ||--o{ INTERRUPT : raises
  INTERRUPT ||--o{ TIMER : arms
  INTERRUPT ||--o| REVIEW : "shown as"
  REVIEW ||--o{ APPROVAL_TOKEN : mints
  APPROVAL_TOKEN ||--|| TOOL_CALL : authorises
  RUN ||--o{ JOURNAL_ROW : records
```
