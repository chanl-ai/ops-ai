# Workflows as agent tools

Status: in code 2026-10-11 (child threads, agent-step reviews); uc-020 in progress. How an agent in a
conversation starts a published workflow and gets its result, so a person can chat with the workflows. Parent
page: [runtime.md](runtime.md).

## The shape

| Step | What happens |
|---|---|
| Offer | An agent whose tool list names `workflow:<id>` is offered a tool `workflow__<id>` while that registry workflow is published. Its input schema is the definition's input, the email its nodes read (`sender`, `subject`, `body`, `attachments`) |
| Call | The kernel calls it like any tool. Its access class is `workflow`, which the kernel does not gate: the workflow's own review steps are the gate |
| Start | The call finds or creates a child thread on the workflow's graph, keyed by the tool call's idempotency key, with `parent_thread_id` set to the agent's thread and the parent run id in the child's metadata. It runs under the child's own lease, pinned to the published version |
| Finish | A child that ends returns its final status and outputs as the tool result, and the agent answers from it in the same turn |
| Pause | A child that stops at a review returns a handle (`threadId`, `status: waiting_review`). The agent's turn ends with that answer; the child's review appears in Cases and Reviews and is decided there like any workflow review |

## Rules

| Rule | Why |
|---|---|
| Only published workflows, only when granted | An unpublished, paused or deleted workflow is not offered, and a call to one is refused with the registry's reason |
| The child's key is the tool call's key | A turn retried after a crash finds the same child instead of starting a second one |
| The child is its own thread | Its leases, fencing, approval tokens, SLA timers and decide path are unchanged; the parent holds a reference, not its state |
| No result is invented for a paused child | The parent turn reports the handle; the outcome arrives through the child's own thread |
| A gated write inside a workflow's agent step is a review | The step stops at an `approval` review of that exact call (the agent wrapper's payload), shown in Cases and Reviews; decide resumes the agent and the step continues to its targets. A parent agent gets the review handle |
| The graph layer does not import the API | The tool reaches the API through a `WorkflowRunner` port on `GraphDeps`, implemented in the agents service |

## Open

Telling the parent conversation when a paused child later finishes (a follow-up message, or an event on the
team stream) is not built; today the person reads the child in Cases.
