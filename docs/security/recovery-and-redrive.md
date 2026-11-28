# Recovery and redrive

Status: current.

Sooner or later a process dies in the middle of a customer's request. A risk reviewer wants to know whether the model is asked twice, whether a payment or a record change is sent twice, and who may start the run again. Ops AI saves a workflow run and a chat reply in the database step by step. A replacement process picks up from the last saved step, and a write to your systems goes out a second time only when the record proves the first one did nothing.

This page shows you how to restart a failed run safely, and what Ops AI does without being asked.

## Fix a failed run and send it on

A builder fixes the cause of a failure and then sends the run on from where it stopped.

<!-- site: steps -->
1. Open the failed run in **Build › Workflows › Runs**. The page names the step that failed, the attempt, the kind of error and whether trying again could help.
2. Fix the cause, for example by setting the address on the app connection the step uses.
3. Press **Redrive**, or run `opsai runs redrive <run-id>`. The run goes back to Queued, runs the failed step again as its next attempt and carries on.
4. Look at the steps that finished before the failure. Each shows one attempt, because they returned what they had recorded and ran nothing again.

## The run finishes on its own record

The run ends as Succeeded. The steps that had already finished show one attempt each, the failed step shows its earlier attempt marked as redriven, and nothing was sent to your systems twice. A run that cannot continue on its own ends as Failed with one error record that names the step, the attempt, the kind of error and whether a retry can help.

## If failed runs are rerun by hand

Without saved steps, the usual answer to a crash is to start the whole run again. For a run that already approved a credit and sent it, starting over means asking the approver again or, worse, sending the credit twice. Ops AI avoids both by keeping each step's result and by checking the gateway's record before it sends a write again.

## How a run moves

<!-- site: state caption="The states a workflow run passes through, and what moves a failed or stuck run on" -->
- **Queued**: Waiting for a worker
  - **Running**: A worker claims the run
- **Running**: A worker is on a step
  - **Succeeded**: The last step finishes
  - **Failed**: A step fails and a retry cannot help
  - **Stuck**: The run stopped and needs a person, for example after a write whose outcome is unclear
- **Stuck**: Waiting for a person
  - **Queued**: Retry continues from the last saved step, or Redrive runs again from the failed step
- **Failed**: Ended with one error record
  - **Queued**: Redrive runs the failed step again, on the version the run started on
- **Succeeded**: Finished

## What happens when something dies

| Situation | What happens | What is never repeated |
|---|---|---|
| A worker dies in the middle of a step | Its claim on the run lapses. Another worker takes the run over at the last saved step, and the first worker can write nothing more | A finished step, a recorded model answer, a write the gateway has a record of |
| The API process dies in the middle of a chat reply | The reply is saved as work of its own. A worker takes it over and continues the thread from its last checkpoint under the same turn | A tool call already made in that turn |
| The outcome of a write is unknown, for example after a timeout | The gateway's record decides. If the record shows it was done, the step takes that answer. If it shows the call never arrived, the write is sent once more under a new key. Otherwise the run stops as Stuck for a person | The write itself, unless the gateway proves it never ran |
| An event between two services cannot be delivered | The sending side retries with a wait of up to a minute. After 15 failures, about ten minutes, the event is a dead letter. It is kept with its last error and never sent again on its own | The change the event reports, which was saved together with the event |

Each step has its own number of attempts: three for reads and writes, two for model calls and one for a step that waits for a person. A step stops retrying after 15 minutes, and only an error that a second try could pass is tried again.

## Retry and redrive

| Command | Applies to | What it does |
|---|---|---|
| Retry | A Stuck run | Continues from its last saved step and repeats no recorded step |
| Redrive | A Failed or Stuck run | Runs again from the failed step, on the version the run started on. A publish made after the run started is not used. No earlier step is repeated |
| Redrive of a failed write | A failed write step | Sends the write again, on its earlier approval and with the arguments that were approved, only when the answer proves it did nothing: it was refused, it was never sent, the gateway refused it before sending, or your system refused it with a 4xx error. After a timeout, a 5xx error, a call that broke off or an answer that could not be read, the gateway's record decides, and an unclear record stops the run for a person |

Only the failed step runs again. Its failed attempt stays on the run as history, marked redriven.

## Who may do it

| Action | Who may do it |
|---|---|
| Retry or redrive one run | Whoever may cancel it: the person who started it, or an admin or reviewer of its team. An API key may act only on runs started under its own identity |
| Redrive or cancel many runs at once | Anyone who may cancel those runs. Use `opsai runs bulk redrive` with a filter on workflow, error kind, error code or start time. A call acts on at most 500 runs of your own team, and lists the runs it skipped |

Delivered events are kept for a week and pruned hourly. A dead letter is kept until it is sent again.

## What you cannot do yet

- Dead letters have no route or screen. Nothing lists them, and sending one again needs an operator with access to the service's database.
- Bulk redrive and cancel have no console screen. The console shows Redrive on a Failed run and Retry on a Stuck run.
- No tool yet declares how its writes may be settled after the gateway died, so every such write stops the run as Stuck for a person. No tool passes the run and step key on to the system it writes to.
- Redriving a run whose Run workflow step failed because a child run failed finds the same child and fails again. Redrive the child run instead.
- Redrive is offered on any Failed run, of any age, including one that ended at an End step the builder marked as a failure.
- These guarantees are proved by tests on PostgreSQL and by a kill test on one machine. A kill test on a deployed preview has not been run.

## Next

<!-- site: cards -->
- **[Access, approvals and audit](access-approvals-and-audit.md)**: Which writes wait for a person, and what is recorded.
- **[Model calls](model-calls.md)**: The gateway every model call goes through, with its log.
- **[Workflows](../guide/workflows.md)**: Retry, redrive and the other run commands.
