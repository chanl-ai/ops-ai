# Cases

Status: current. Rows marked planned are designed and not built.

When a piece of work takes days and passes between several people, your team needs one place where anyone can see
where it stands. A case gives you that record, so the next person picks the work up where the last one left off.

## Work that lasts days gets lost between people

A court order on an account, a complaint, an insurance claim or a loan hardship request usually passes through several
people and several runs. Without one shared record, each person has to read the whole email chain to learn what
happened. Nobody can say what the work is waiting on or who owns it, and deadlines slip because no one can see the clock.

A case is that shared record. It holds what the work is about, what it is waiting on, who owns it and everything that
has happened to it. Use a case whenever someone on your team needs to pick up work that a colleague started.

## How a case moves from open to closed

<!-- site: steps -->
1. **Name the kind of work.** A builder edits a case type, which sets the fields the case carries and the order they appear in.
2. **Let a workflow open it.** An **Open case** step creates the case and fills in the fields the workflow has read.
3. **Work it.** Your team assigns the case, adds notes and changes its status as the work moves on. Drafted actions and Human Tasks show on the case.
4. **Close it.** A person closes the case when the work is done. A run never closes it, so that decision always rests with someone on your team.

## Open your first case

You open a case from a workflow with an **Open case** step. The example below reads a claim document that arrives by
email, then opens a case with two fields taken from it:

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

Once a run has opened the case, you can find it and add a note from the command line:

```bash
opsai cases list --status open
opsai cases show <case-id>
opsai cases note <case-id> "Called the claimant; documents on the way."
```

In the console, you will find the case under **Work › Cases**.

## What a case holds

A case holds everything a colleague needs to pick the work up.

<!-- site: cards -->
- **Owned by one team**: Each case belongs to one team, and only members of that team who have the Cases permission can open it.
- **One page of facts**: The case page shows the subject, status, priority, owner and customer, along with two clocks, one for first response and one for resolution. Below them come the fields the workflow set, in the order the case type gives them.
- **History in plain words**: Each event reads as a sentence such as "Maria approved the hold" rather than a run id. The case shows the five newest events, and **View all** opens the full activity.
- **Waiting work in view**: The case lists the Human Tasks it waits on, along with linked files, runs, emails and other cases. When an action has been drafted, such as a hold waiting for approval, the case shows its progress. Someone approves it on its Human Task, where step-up and two-person rules apply.
- **A versioned case type**: The case type names the fields and sets their order. Builders edit case types themselves, and no case type needs code.

## Who can do what

| Action | Who | Where |
|---|---|---|
| Assign to yourself or someone else | People who may edit the team's cases | The case's header, or the Cases list |
| Change status, priority or deadlines | The same. Closing or reopening needs the Cases manage permission and is always a person, never a run | The case's header |
| Add a note | The same | The case, or `opsai cases note` |
| Open a case | A workflow's **Open case** step, or another system through the API | Workflows, or the HTTP API |

## What to expect today

- The console has no button for opening a case by hand, so a workflow or the API has to open it.
- When a case is waiting on the customer, both clocks pause. Once the case leaves that status, both deadlines move on by the time it spent waiting.
- A conversation tab for email cases is planned. For now, linked emails show as a list.

## When cases are working well

A workflow opens each case with its fields already filled in. Anyone on your team with the Cases permission can find it,
read its history in plain words, see the Human Tasks it waits on and add a note. Because the owner and the two clocks
sit on the case page, a colleague who picks the work up on Monday knows what happened on Friday.

## What happens without a case

Without a case, the state of the work is spread across email threads and run logs. The next person has to rebuild it by
reading all of them, and a deadline belongs to whoever happens to remember it.

## Next

<!-- site: cards -->
- **[Human tasks and approvals](human-tasks.md)**: the decisions a case waits on.
- **[Workflows](workflows.md)**: the steps that open and update a case.
- **[How work flows](how-work-flows.md)**: an email that becomes cases, end to end.
