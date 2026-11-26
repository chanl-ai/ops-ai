# Cases

Status: current. Rows marked planned are designed and not built.

**Keep one record for a piece of work that takes days, so the next person picks it up where the last one left off.**

## Work that lasts days gets lost between people

A court order on an account, a complaint, an insurance claim or a loan hardship request passes through several people and
several runs. Without one record, each person reads the email chain to learn what happened. Nobody can say what the work
is waiting on or who owns it, and a deadline slips because no one could see the clock.

A case is the one record of that work: what it is about, what it is waiting on, who owns it, and everything that
happened to it. Use cases when a person needs to pick up a piece of work where someone else left it.

## The plan

<!-- site: steps -->
1. **Name the kind of work.** A builder edits a case type: the fields it carries and their order.
2. **Let a workflow open it.** An **Open case** step creates the case with the fields the workflow read.
3. **Work it.** People assign it, add notes and change its status. Drafted actions and Human Tasks show on the case.
4. **Close it.** A person closes the case. A run never does.

## Try it

A workflow opens a case with an **Open case** step. This one reads a claim document that arrives by email and opens a
case with two fields from it:

```yaml
- id: open
  type: ops.action.openCase
  typeVersion: 1
  name: Open a claim case
  parameters:
    subject: $.nodes.read.out.records.0.values.name
    caseType: complaint
    fields:
      claimant: $.nodes.read.out.records.0.values.name
      amount: $.nodes.read.out.records.0.values.amount
```

Once a run has opened it, find it and add a note:

```bash
opsai cases list --status open
opsai cases show <case-id>
opsai cases note <case-id> "Called the claimant; documents on the way."
```

In the console the case is under **Work › Cases**.

## What a case holds

- A case belongs to a team, and only that team's members with the Cases permission can open it.
- Its page shows the subject, status, priority, owner, customer and two clocks (first response and resolution), the
  fields the workflow set in the case type's order, the Human Tasks it is waiting on, and its linked files, runs, emails
  and other cases.
- The history is written in plain words ("Maria approved the hold"), not run ids. The five newest events show on the
  case; **View all** opens the full activity.
- A drafted action, such as a hold waiting for approval, shows on the case with its approval progress. It is approved on
  its Human Task, where step-up and two-person rules apply.
- A case type is a versioned record that names the fields and their order. Builders edit case types; no case type needs
  code.

## Options

| Action | Who | Where |
|---|---|---|
| Assign to yourself or someone else | People who may edit the team's cases | The case's header, or the Cases list |
| Change status, priority or deadlines | The same. Closing or reopening needs the Cases manage permission and is always a person, never a run | The case's header |
| Add a note | The same | The case, or `opsai cases note` |
| Open a case | A workflow's **Open case** step, or another system through the API | Workflows, or the HTTP API |

## Limits

- The console has no button to open a case by hand. A workflow or the API opens it.
- Waiting on the customer pauses both clocks; leaving that status moves both deadlines on by the time it waited.
- A conversation tab for email cases is planned; linked emails show as a list today.

## What success looks like

A workflow opens the case with its fields filled in. Anyone on the team with the Cases permission finds it, reads the
history in plain words, sees the Human Tasks it waits on and adds a note. The owner and the two clocks are on its page,
so a colleague who picks it up on Monday knows what happened on Friday.

## What skipping it costs

Without a case, the state of the work is spread across email threads and run logs. The next person rebuilds it by
reading all of them, and the owner of a deadline is whoever remembers it.

## Next

<!-- site: cards -->
- **[Human tasks and approvals](human-tasks.md)**: the decisions a case waits on.
- **[Workflows](workflows.md)**: the steps that open and update a case.
- **[How work flows](how-work-flows.md)**: an email that becomes cases, end to end.
