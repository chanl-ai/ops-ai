# Recovery and redrive

Status: current. Checked against the release's workflow engine, chat turns and event outbox.

A risk reviewer needs to know what happens to a customer's request when a process dies halfway through it: whether a
model is asked twice, whether a payment or a record change is sent twice, and who may start a stopped run again. In
Ops AI a workflow run and a chat reply are kept in the database step by step, so a replacement process continues from
the last recorded step, and a write to your systems is never sent a second time under a new key unless the gateway
proves the first one never ran.

## Try it

A builder fixes a failed run's cause and sends it on from where it stopped.

<!-- site: steps -->
1. Open a failed run. The card names the step that failed, the attempt, the kind of error and whether trying again
   helps.
2. Fix the cause, such as setting the address on the app's connection the step uses.
3. Press Redrive. The run goes Queued, runs the failed step again as its next attempt, and continues.
4. The steps that finished before the failure show one attempt each: they returned what they recorded and ran nothing.

## How it works

| Situation | What happens | What is never repeated |
|---|---|---|
| A worker dies mid-step | Its claim lapses; another worker takes the run over at the last recorded step, fenced so the first can write nothing more | A finished step, a recorded model answer, a write the gateway has a record of |
| The API process dies mid-reply | The reply is a work row of its own; a worker takes it over and continues the thread from its last checkpoint under the same turn id | A tool call already made in that turn |
| A write's outcome is unknown (a timeout, a gateway that died) | The gateway's record under the attempt's key decides. Found done: the step takes that answer. Never received: it is sent once more under the next key. Otherwise the run stops for a person | The write itself, unless the gateway proves it never ran |
| A run fails | It ends Failed with one error record (kind, code, step, attempt, whether a retry helps) | |
| Retry (a Stuck run) | Continues from its last checkpoint | Every recorded step |
| Redrive (a Failed or Stuck run) | Runs again from the failed step, on the version the run started on; a later publish is not used | Every step that finished before it, and any write whose outcome is unknown until its key is read |
| An event between services cannot be delivered | The relay tries it again with a backoff of up to a minute; after 15 failures (about ten minutes) it is a dead letter, kept with its last error and never sent again on its own | The change the event reports, which committed with it |

A step the run's failure names is the only one a redrive runs again. Its failed attempt is kept on the run as
history, marked redriven.

## Options

| Option | Default | Who changes it |
|---|---|---|
| Who may Retry or Redrive a run | Whoever may cancel it (the cases manage permission): the person who started it, or an admin or reviewer of its team; an API key only for runs started under its own identity | Team admin, through the team's roles |
| Bulk redrive or cancel by workflow, error kind, code and time | Off until called; at most 500 runs per call, in the acting team only | Anyone who may cancel those runs, through `POST /v1/runs/bulk`, the SDKs or `opsai runs bulk` |
| Attempts per step | 3 for reads and writes, 2 for model calls, within 900 seconds per step; only an error a second try can pass is tried again | Fixed; a builder sets each step's time limit (`timeoutSeconds`) |
| How long a delivered event is kept | A week, pruned hourly; a dead letter is kept until it is sent again | Not configurable |

## Limits

- Dead letters have no route or screen yet: nothing lists them, and sending one again needs an operator with access to
  the service's database. Bulk redrive and cancel have no console screen.
- No tool declares how its writes may be settled after a dead gateway, so every such write pauses the run as Stuck for
  a person, and no tool passes the run-and-step key to the system it writes to.
- Redrive is offered on any Failed run, of any age, including one that ended at an End the builder marked as a
  failure.
- A chat reply that outlives its deadline is ended by the worker, not by the process streaming it.
- These guarantees are proved by tests on PostgreSQL and by a kill test on one machine; a kill test on a deployed
  preview has not been run.

## Next

<!-- site: cards -->
- **[Access, approvals and audit](access-approvals-and-audit.md)**: Which writes wait for a person, and what is recorded.
- **[Model calls](model-calls.md)**: The gateway every model call goes through, with its log.
- **[Workflows](../guide/workflows.md)**: Retry, Redrive and the other run commands.
