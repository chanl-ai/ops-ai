# How work flows

Status: current. Each flow below is exercised end to end by the release's automated use cases.

Three flows cover most of what Ops AI does: a person chats with an agent that wants to change something, a workflow
pauses for a person and resumes days later, and an email becomes cases that people decide. In each one the same three
rules hold: a write waits for an approval bound to its exact input, every outside call leaves through a gateway, and a
run's state is saved after every step so a crash or a restart loses nothing.

## A chat turn with a tool approval

A member of the operations team asks the team's agent to place a hold on an account. Reading is free; the hold is a
write, so the agent drafts it and a person approves it before anything reaches the core system.

```mermaid
sequenceDiagram
  autonumber
  actor P as Person
  participant AG as agents
  participant MO as AI gateway
  participant TO as Data gateway
  participant SYS as Your core system
  P->>AG: Message, signed in
  AG->>MO: Model call on the agent's alias and key
  MO-->>AG: Call get_account, then place_hold
  AG->>TO: get_account (a read)
  TO->>SYS: HTTPS, allow-listed host
  SYS-->>TO: Balance and holds
  TO-->>AG: Result, logged
  Note over AG: place_hold is a write: the run<br/>pauses with its state saved
  AG-->>P: Approval card with the exact input
  P->>AG: Approve, with a fresh sign-in if asked
  Note over AG: Token bound to the input's hash,<br/>the tool and the step
  AG->>TO: place_hold with the token
  Note over TO: Policy engine: signed, same input,<br/>not expired, enough approvers
  TO->>SYS: HTTPS with the stored credential
  SYS-->>TO: Hold placed
  TO-->>AG: Result, recorded once by its key
  AG->>MO: Model call with the result
  AG-->>P: The answer, streamed
```

*The person sees the input that will be sent before approving it. Who may approve is the operation's policy: the
number of approvers, the team they belong to, whether a fresh sign-in is needed, and whether the person who asked may
decide.*

| Step | What protects it |
|---|---|
| The message | The person's sign-in token names the tenant and team; nothing in the message can change them |
| The model call | The AI gateway checks the agent's key, its budget and the data's sensitivity before it calls your model endpoint |
| The pause | The approval waits in the conversation with its state saved; closing the browser loses nothing |
| The write | The data gateway refuses a call whose input differs from what was approved by a single character, a token past its 15 minutes, or a token from a run that another process has since taken over |
| A repeat | A retried call with the same idempotency key returns the first result and writes nothing |

## A workflow run with a human task

A workflow starts from an API call, an email or an event from another service. The worker runs its steps in order
and saves each one. When a step needs a person, the run pauses and holds no worker; the person's decision puts it back
on the queue.

```mermaid
sequenceDiagram
  autonumber
  participant T as Trigger
  participant Q as agents and work queue
  participant W as worker
  actor R as Reviewer
  participant TO as Data gateway
  T->>Q: Start, with a dedupe key
  W->>Q: Claim the run and take its lease
  loop Each step
    W->>W: Run it, journal its input, output and key
  end
  Note over W: Human task: the run pauses,<br/>frees the worker, sets a deadline
  W-->>R: Task in Human Tasks and on the case
  R->>Q: Approve, reject or return, with a reason
  W->>Q: Claim the resume
  W->>TO: The approved write, with its token
  TO-->>W: Result, recorded once
  W->>W: Remaining steps, then the outcome
```

*A waiting run costs nothing but its saved rows, whether the person answers in a minute or in a week.*

| Situation | What happens |
|---|---|
| A worker dies mid-step | Its lease expires after 15 seconds. Another worker takes the run, raises the lease generation, and continues from the last saved step. A write the first worker already made is found by its key and not made again; anything the first worker sends afterwards is refused as stale |
| The task's deadline passes | The task shows as overdue, or, when the step says so, the run leaves on its timeout path, for example to escalate. A timeout never approves anything |
| A step fails three times | The run fails with the error on its record, and its case shows the failure to people |
| The workflow is republished mid-run | The run keeps the version it started on; new runs take the new version |

## Email to case: a tax levy notice

This is one worked example. A team connects its mailbox, publishes three workflows through review, and from then on
each notice a court or tax authority emails is read, checked, turned into cases and answered. Nothing in it is code
written for levies: the document type, the workflows, the tools and the task types are configuration.

```mermaid
sequenceDiagram
  autonumber
  participant MB as Team mailbox
  participant W as worker
  participant DO as files and documents
  actor PE as People in Human Tasks
  participant TO as Data gateway
  MB->>W: New message
  Note over W: Mailed documents: the message id<br/>is the dedupe key
  W->>DO: Store each attachment
  loop Each attachment: Mailed document
    W->>DO: Read it as a levy notice
    DO-->>W: Debtors, each value citing its place
    opt A score below the floor
      W-->>PE: Check the read beside the page
      PE->>W: Corrected values, or reject
    end
    loop Each debtor: Levy case
      W->>TO: Search customers, list accounts
      W->>W: Match the debtor, open a case
      W-->>PE: Hold funds or flag the customer?
      PE->>W: Hold
      W->>TO: Place the hold, with the token
    end
    W-->>PE: Send the acknowledgement?
    PE->>W: Approve
    W->>TO: Reply from the mailbox's address
  end
```

*The checker corrects what was read; the correction is kept as an example for the next read of that document type.
Each debtor gets a case whatever happens to the others, and an unmatched debtor gets a case of its own for a person.*

| Configuration | What it holds |
|---|---|
| The mailbox | Provider, folder, the credential's name in the credential store, and the address replies come from |
| A document type, "levy notice" | The fields to read, their checks, the score floor, and the examples corrections have taught it |
| Three workflows | Mailed documents (one run per message), Mailed document (one per attachment), Levy case (one per debtor) |
| Tools | Search customers, list accounts, place hold, add a note, send a reply: operations on your systems with their approval policies |
| Task types | Check the read, hold or flag, send the acknowledgement: what the person sees and the actions they can take |

Other worked examples in the release use the same parts: complaint email triage, a hold requested through the API,
and a customer summary built from the core system and an agent.
