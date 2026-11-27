# Card disputes

Status: current.

This guide walks you through a card dispute from intake to a provisional credit. An agent checks the dispute against
the handbook, and a person approves the money before it moves.

## Most of a dispute is lookup work

A card team works through hundreds of disputes a week, and most of that work repeats. Someone finds the cardholder,
lists their accounts and reads the handbook's rules for this kind of dispute. The judgement that follows is small, but
it matters. Your team has to decide whether the dispute arrived in time, which rule applies and how much provisional
credit is allowed. Because the credit moves money, a person has to approve it, and the bank has to be able to show
later who approved what and what they saw.

In this guide you run one dispute with the Card dispute intake workflow in the demo team. Fixed steps do the lookups,
then an agent reads the handbook, and finally a person approves the credit.

## The plan

<!-- site: steps -->
1. **The dispute comes in** through a form or the API: who the cardholder is, the merchant, the amount and what went
   wrong. The Card dispute intake workflow starts.
2. **Fixed steps find the cardholder** and their accounts in the core banking system, through the tool gateway. A
   If the workflow cannot find the cardholder, the run ends as Cardholder not found, so nobody acts on a guessed match.
3. **An agent checks the dispute against the handbook** and answers in a fixed shape. The answer gives the reason
   category, whether provisional credit is due, whether a team lead must approve it, and a short summary. The next
   step checks that the answer has this shape before anything moves.
4. **The case opens** and holds the record of the run.
5. **A person approves the credit** in **Human Tasks**, seeing the dispute, the agent's assessment, the accounts and the
   case. Approving adds a note to the case, "Provisional credit approved by" the approver, and the run ends at Credited.

![The Card dispute intake workflow on the canvas, from Dispute received through the cardholder lookup, the agent's check and the case to the approval, with the failure ends below](../../media/workflow-light.png)

## Try it

You can run one dispute in the console and then approve its credit. If your team has the Two-person rule turned on,
a teammate must do the approving. If you are working alone, run the dispute as a team Admin, because an Admin may
approve their own run.

| Step | Where | Expected |
|---|---|---|
| Start a dispute | **Workflows**, Card dispute intake, **Run**, with the cardholder Jordan Whitfield (last four 5555), merchant Northline Electronics, amount 482.10, posted 2026-10-11, card type debit and the reason "Ordered a monitor on 11 October; the parcel never arrived." | The run starts and moves through the lookup and the agent's check |
| Watch the run | The run's page | Each step with its input and output, and the run stops at the approval |
| Approve | **Human Tasks**, the provisional credit task | The dispute, the assessment and the accounts are shown. Choose **Approve** and give a reason |
| Read the record | The case | The run ends at Credited, and the case holds the credit and the decision |

![Riley Chen opens the Human Task for a 482.10 CAD provisional credit, reads where the amount came from, approves it, and the run ends at Credited](../../media/task.gif)

## Run it from code

You can run the same dispute from a script. The script starts a dispute, waits until it reaches the approval, and
then decides it. The code below uses the same SDK calls that the workflow's tests run end to end. An API key from
**Settings › Team › API keys** can start a run and wait on it, but a key cannot decide a task. The approver signs in
as themselves to make the decision.

```python tab="Python"
from ops_ai import OpsAI

ops = OpsAI(api_key="ok_...", base_url="https://ops.example.com", team="team_customer_ops")
started = ops.runs.start(
    "card_dispute_intake",
    input={
        "cardholder": "Jordan Whitfield",
        "ssnLast4": "5555",
        "merchant": "Northline Electronics",
        "amount": "482.10",
        "postedOn": "2026-10-11",
        "cardType": "debit",
        "reason": "Ordered a monitor on 11 October; the parcel never arrived.",
    },
)
run = ops.runs.wait(started["runId"])  # returns at the approval, with the task's id
approver = OpsAI(profile="approver")  # the approver signs in as themselves; a key never decides
approver.tasks.decide(run["taskId"], "approved", reason="Inside the 90-day debit limit.")
print(ops.runs.wait(started["runId"])["outcome"])  # credited
```

```ts tab="TypeScript"
import { OpsAI } from '@chanl-ai/ops-ai';

const ops = new OpsAI({ apiKey: 'ok_...', baseUrl: 'https://ops.example.com', team: 'team_customer_ops' });
const started = await ops.runs.start('card_dispute_intake', {
  input: {
    cardholder: 'Jordan Whitfield', ssnLast4: '5555', merchant: 'Northline Electronics',
    amount: '482.10', postedOn: '2026-10-11', cardType: 'debit',
    reason: 'Ordered a monitor on 11 October; the parcel never arrived.',
  },
});
const run = await ops.runs.wait(started.runId);
const approver = new OpsAI({ profile: 'approver' });  // the approver signs in as themselves; a key never decides
await approver.tasks.decide(run.taskId!, 'approved', { reason: 'Inside the 90-day debit limit.' });
console.log((await ops.runs.wait(started.runId)).outcome);   // credited
```

When this works, the first wait returns at the approval with a task id. After the decision, the run's outcome is
`credited`.

## How each run can end

Every run ends in one of five outcomes, and the run's page shows which one. Four of them appear on the path below.

<!-- site: decision source caption="How a card dispute run ends: lookup, cardholder, then the approver" -->
- **Can the lookup reach the core banking system?**
  - **No**: Lookup failed.
  - **Yes**: The cardholder search runs next.
    - **Does it find a cardholder matching the details?**
      - **No**: Cardholder not found. The run stops without guessing at a match.
      - **Yes**: The agent checks the handbook, then a person decides the credit.
        - **Does the approver approve the provisional credit?**
          - **Approves**: Credited. The case holds the credit note and the decision.
          - **Declines**: Declined. No credit is sent.

If a step fails after the lookup, the run ends as Could not finish. The run's page then shows which step failed and
why.

## What a good run looks like

The run stops at the approval, and the task shows the approver the dispute, the assessment and the accounts. Once the
approver decides, the run ends at Credited, and the case holds the credit, the decision and the name of the person who
made it. If no cardholder matches the dispute, the run ends as Cardholder not found, so the credit never goes to the
wrong person.

## Why the approval step matters

If you remove the approval step, a provisional credit rests on a lookup and a summary alone. The bank would then have
no way to show later who approved the credit or what they saw when they did.

## Limits

- While the team's **Two-person rule** is on (**Settings › Approvals**), the approver cannot be the person who started
  the run. The exception is a team Admin, who can still decide their own request.
- The workflow, its agent and its tools are records your team owns, and you can change them in the console or through
  the same API. The demo team's copy is a starting point and is not a bank's policy.

## Next

<!-- site: cards -->
- [Hold a write for approval](approve-a-write.md): the approval settings behind the credit step.
- [Agents and workflows in the console](../../console/agents-and-workflows.md): build your own workflow.
- [Start the day from chat](chat-and-human-tasks.md): where the approver finds the task.
