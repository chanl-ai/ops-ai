# Workflow node improvements: prior art

Status: research note. Three of the ten are since built in part (waits, branches with a join, waiting for child runs);
the "Ops AI now" column says which. The rest are proposals.

A bank operations builder is not a developer. They build a workflow from a form per node, and before publishing they
need to know three things: does each step get the data they think it gets, what happens when a step fails or a person
does not answer, and what changed since the last published version. The Ops AI node types cover the happy path well:
typed ports, effects classes, retry by effects class, and review options as ports
([workflow nodes](../workflows/workflow-nodes.md)). The gaps are in testing, wiring data between steps, failure routes,
waiting and parallel work. This note compares ten improvements against how other workflow products handle the same job,
ranked by impact for the least effort.

Product sources are numbered in the list at the end. "(unverified)" marks a claim from memory rather than from a page
that was opened.

| # | Improvement | What it is | Who does it and how | Ops AI now | Smallest version | Impact |
|---|---|---|---|---|---|---|
| 1 | Pin sample data, test one step | Save a step's output as fixed sample data, then run only the step being edited against it | n8n pins node output and lets you edit it to simulate edge cases [1]. Zapier and Make test per step (unverified) | Run pages show step inputs and outputs after a full run; no pinning and no single-step test | A "Use this output as sample" button on a run page step; "Test step" runs one node on its pinned inputs with writes forced to a dry run | High |
| 2 | Pick fields from earlier steps, with a live preview | A field picker listing earlier steps' outputs, and the value the field would have now | n8n expressions read earlier nodes and the editor previews the computed value [2]. Make and Zapier use a data picker (unverified) | A picker inserts an earlier step's output path, and step outputs are known before a run so a misspelt mapping is warned ([uc-401](../../usecases/agents-service/step-output-shapes.md)); no live preview | The resolved value under the field, from the pinned or last-run output of upstream steps | High |
| 3 | A failure route on every node | A node can send failures down its own port, with the error as data, instead of ending the run | Power Automate "Run after" sets what follows on failed, skipped or timed out, and scopes give try and catch [3]. n8n has an error workflow per workflow [4] and an error output per node (unverified). Make has error handler directives (unverified) | Most action and AI steps have an `error` port; Human review has a `timeout` port; there is no general "if this step fails" setting | A setting "If this step fails": stop the run (default), or continue on an `error` port carrying code and message | High |
| 4 | Wait and deadline nodes | Pause a run for a duration or until a date; escalate if a task is still open | Camunda timer events: duration, date, cycle; boundary timers either interrupt or only notify, for reminders [5]. Zapier has Delay steps (unverified) | Built: a Wait step for a duration or until a date read from a step, and Human review deadlines and reminders that never resume the run ([uc-403](../../usecases/agents-service/wait-and-reminders.md)). No Schedule trigger | A Schedule trigger with a cron field | High |
| 5 | Replay from a run | Copy a past run's data into the editor, or rerun from a failed step | n8n copies a past execution's data into the open workflow for debugging [6]. Temporal retries the failed activity, not the whole workflow [7] | Run pages show step inputs and outputs; no rerun from a step | "Rerun from this step" on a failed step: same inputs, same pinned version, a new run linked to the old one | High |
| 6 | Editable retry and non-retryable errors | Attempts, first wait, cap and a list of errors that must not retry, per node | Temporal: initial interval, backoff coefficient, maximum interval, maximum attempts, non-retryable errors [7]. Power Automate: a fixed or exponential policy per action [3] | Retry is fixed by effects class; writes get one attempt by design | Retry fields on read and model nodes only; writes stay at one attempt with a reconciliation read | Medium |
| 7 | Parallel branches and a join | Run several branches at once and continue when all (or the first) finish | Windmill "branch all" runs branches together, and each can skip on failure [8]. Power Automate parallel branches (unverified) | Built: a port connected to several steps runs them together, and a Join waits for every branch that can still arrive and exposes each branch's output by step ([uc-400](../../usecases/agents-service/branches-join.md)). No "first to finish" | "Continue when the first branch finishes" as a Join setting | Medium |
| 8 | Loop controls | Per-item failure handling, batch size and delay between items | Retool Loop runs in parallel, sequentially with a delay, or in batches (10 by default) [9]. Make iterators with aggregators (unverified) | Partly built: Start workflow runs a child per item a few at a time and, with Wait on, lists each child's outcome; a failed child never fails the parent ([uc-402](../../usecases/agents-service/wait-for-children.md)) | A delay between batches | Medium |
| 9 | Version diff in publish review | Show what changed per node between the published version and the draft | Workato recipe version history and compare (unverified). Camunda and Power Automate keep versions (unverified) | Publish through review exists and node type versions are pinned; no diff | The review page lists nodes added, removed and changed, with changed settings shown old to new | Medium |
| 10 | Saved node presets | Save a configured node (a levy-notice extract, a four-eyes review) and drop it into other workflows | n8n and Zapier have templates at workflow level; node-level reuse is rare (unverified). Power Automate has child flows and scopes [3] | Start workflow reuses whole workflows; no node-level reuse | "Save as preset" on a node, listed in the add-step menu for the team; a preset is a copy, not a link | Low |

## Notes on the ranking

Items 1 to 3 change what a builder can see and do in the editor with small server changes, because the run page already
stores step inputs and outputs. Items 4 and 7 add node types and runner behaviour, so they cost more; both are since
built. Item 6 stays narrow on purpose, because a second send of a payment or a notice is worse than a failure.

## Sources

Opened and read:

1. n8n data pinning: <https://docs.n8n.io/data/data-pinning/>
2. n8n expressions: <https://docs.n8n.io/code/expressions/>
3. Power Automate error handling (Run after, scopes, retry policy): <https://learn.microsoft.com/en-us/power-automate/guidance/coding-guidelines/error-handling>
4. n8n error workflows: <https://docs.n8n.io/flow-logic/error-handling/> (the page covers error workflows and Stop And Error only; node-level settings are not on it)
5. Camunda timer events: <https://docs.camunda.io/docs/components/modeler/bpmn/timer-events/>
6. n8n executions: <https://docs.n8n.io/workflows/executions/>
7. Temporal retry policies: <https://docs.temporal.io/encyclopedia/retry-policies>
8. Windmill branches: <https://www.windmill.dev/docs/flows/flow_branches> (does not say how branch results are joined)
9. Retool loop block: <https://docs.retool.com/workflows/guides/blocks/loop>

Tried and not read (404, or a redirect not followed): Make error handling, the Zapier delay help article, Workato recipe
versions, UiPath queues, Camunda boundary events, Pipedream errors. Every claim about Zapier, Make, Workato, UiPath and
Pipedream above is from memory and marked unverified.
