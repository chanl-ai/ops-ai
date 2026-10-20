# Tool lifecycle

Status: current design, 2026-10-14. It describes the whole path a tool takes, from connecting a system to showing
its calls, and marks each step built, broken or not built. It was written from the c-048 live walk on the shared
stack, and card c-048 builds it. Service facts live in [tools-service](../services/tools-service/overview.md), pauses
in [human in the loop](human-in-the-loop.md), and tokens in [identity and tenancy](identity-and-tenancy.md). This page
links to them and does not repeat them.

## The path

```
connect → import or create → edit → security review → publish
        → workflow access → grant to an agent → call → approve a write → show the call
```

Every step happens in the console as a named person. No step needs a direct API call, a fixture or a seed edit.

| Step | Who | Today | Target |
|---|---|---|---|
| Connect: egress host and range | Admin | Built (Egress page) | Unchanged |
| Connect: credential | Builder | Built (Secrets page) | Unchanged |
| Connect: connection record | Builder | Console mock; import makes you pick one | Removed as a separate record. A module's endpoint plus its secret headers are its connection. The Connections page lists modules by endpoint from the registry |
| Import | Builder | Built for OpenAPI and MCP. Every operation comes in as Write. A spec with no auth imports silently | Access is pre-set from the method (GET is Read, everything else is Write; HEAD is skipped because it answers no body), and the builder confirms each one in the dialog. A spec with no security scheme shows a warning naming the missing header. Each operation's example response becomes its stub |
| Create, edit, delete | Builder | Built (c-027: call shape, transform, timeout; staged until publish) | Unchanged |
| Access classes | Builder | Read, Write and "Moves money" | **Read and Write only.** How many approvers a write needs is set on the operation (see "Write approval"), not implied by a class |
| Security review | Owner requests, Security decides | Built (c-040) | Unchanged |
| Try an operation | Module owner | Refused (`no_approval`) unless a workflow holds an approval | The maintainers tries any operation of their own module without a workflow approval. Reads run for real. Writes answer from the stub |
| Workflow access | Workflow owner requests, the module's team decides | Requests work. Approve is disabled for everyone, because "is this mine" compares against a fixed seed name | The decision compares the signed-in person with the requester. Anyone on the module's team except the requester decides |
| Grant to an agent | Builder | Built (c-048 G1): the picker lists published operations from the registry | A grant whose operation is no longer offered shows as stale and can be removed. Saving drops it instead of answering 400 |
| Call: read | Agent | Built: runs through `/v1/calls` on the real model | Unchanged |
| Call: write | Agent | Drafts an approval card. On the shared stack the approved call is refused (the token is not accepted) | The approved call runs once, with the token bound to its input |
| Approve a write | Person | Only in the chat widget; never listed in Reviews | Listed in Reviews and decidable there or in the chat. The operation's approval policy applies |
| Show the call | Operator | Module activity is real. Activity > Tool calls is console mock | Tool calls reads `/v1/executions`: who asked, which agent, which run, the approval, the decision, and the failure with its side |

## Write approval

The money class is replaced by a policy on each write operation. It is set at import or edit, and like any change
to the call shape it goes through security review.

| Field | Values | Default |
|---|---|---|
| `approvers` | 1 or 2 distinct people | 1 |
| `approverTeam` | A team id | The module's owning team |
| `selfApproval` | Whether the person whose chat drafted the call may approve it | Off. Dev may turn it on (`OPS_ALLOW_SELF_APPROVAL_IN_CHAT`) |

The gateway and OPA read these fields from the registry, never from the caller. The two-approver rule that "Moves
money" carried today becomes `approvers: 2`.

## Reviews holds every decision

| Item | Raised by | Decided by |
|---|---|---|
| Security review of a module | Module owner | Security team |
| Workflow access to a module | Workflow owner | Module's team, not the requester |
| Write approval, from a workflow run or a chat | The agent's call | The operation's `approverTeam`, under its policy |
| Agent or workflow publish | Builder | Another publisher (dev auto-approval is off on walk stacks) |

The chat widget and the Reviews row decide the same review through the same decide call.

## Decisions

| Decision | Why |
|---|---|
| Access is Read or Write; approval needs are a per-operation policy | Most workflows here are back office, so a money class assumed customer-facing flows. How strict a write is belongs to the operation, not a fixed class |
| Access is pre-set from the HTTP method and confirmed by the builder | Every operation as Write made a builder untick every read. Confirmation keeps the old safeguard that a name proves nothing |
| No separate connection record | The module already holds the endpoint and secret headers. A second record was a mock with no service behind it |
| The maintainers can try a module without a workflow approval | Testing your own module is not a workflow's call, and writes stay on the stub |
| Chat approvals appear in Reviews | A second approver should not need the requester to send them a chat link |
| Adding a `{{SECRET}}` header is a major change and goes to Security | A new secret widens what the module can reach; only Security reviews that |
| Self-approval is off outside dev | One person placing and approving a hold is no review. Dev keeps it on so a single builder can walk the path |

## Not in this design

Dev stack setup and seeding, agent-page features shown before they work, and the audit log and Access pages each have
their own card.
