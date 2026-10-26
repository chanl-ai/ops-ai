# Card disputes

Status: current. The workflow runs in the demo team, and the code below uses the SDK calls its tests run end to end
on a local stack.

A cardholder disputes a charge. The bank has to confirm who they are, check the dispute against its rules, and credit
the money for the time the dispute takes, with a person approving the credit and a record a reviewer accepts.

## The problem

A retail bank's card team works through hundreds of disputes a week. Most of the work is the same each time: find the
cardholder, list their accounts, read the handbook's rules for this kind of dispute. The judgement is small but it
matters: is the dispute in time, which rule applies, how much provisional credit is allowed. And the credit itself
moves money, so a person has to approve it, and the bank has to show who approved what.

## How Ops AI runs it

<!-- site: steps -->
1. **The dispute comes in** through a form or the API: who the cardholder is, the merchant, the amount and what went
   wrong. The Card dispute intake workflow starts.
2. **Fixed steps find the cardholder** and their accounts in the core banking system, through the tool gateway. A
   cardholder the workflow cannot confirm goes to a person instead of a guess.
3. **An agent checks the dispute against the handbook** and answers in a fixed shape: in time or not, the rule that
   applies, the credit allowed, with the handbook sections cited. The next step checks that shape before anything moves.
4. **A person approves the credit** in Human Tasks, with the amount, the account and where each fact came from.
   Approving sends the credit with a token bound to exactly what they saw.
5. **The case keeps the record**: the run, the credit and every decision.

![The Card dispute intake workflow on the canvas, from Dispute received through the cardholder lookup, the agent's check and the case to the approval, with the failure ends below](../../media/workflow-light.png)

![Riley Chen opens the Human Task for a 482.10 CAD provisional credit, reads where the amount came from, approves it, and the run ends at Credited](../../media/task.gif)

## Run it from code

Start a dispute, wait until it reaches the approval, and decide it. Create an API key under Settings > Team > API keys
in the team that owns the workflow; the person who decides needs the approver role.

```python tab="Python"
from ops_ai import OpsAI

ops = OpsAI(api_key="ok_...", base_url="https://ops.example.com", team="team_customer_ops")
started = ops.runs.start("card_dispute_intake", input={
    "cardholder": "Jordan Whitfield", "ssnLast4": "5555", "merchant": "Northline Electronics",
    "amount": "482.10", "postedOn": "2026-10-11", "cardType": "debit",
    "reason": "Ordered a monitor on 11 October; the parcel never arrived.",
})
run = ops.runs.wait(started["runId"])          # returns at the approval, with the task's id
approver = OpsAI(api_key="ok_...approver", base_url="https://ops.example.com", team="team_customer_ops")
approver.tasks.decide(run["taskId"], "approved", reason="Inside the 90-day debit limit.")
print(ops.runs.wait(started["runId"])["outcome"])   # credited
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
const approver = new OpsAI({ apiKey: 'ok_...approver', baseUrl: 'https://ops.example.com', team: 'team_customer_ops' });
await approver.tasks.decide(run.taskId!, 'approved', { reason: 'Inside the 90-day debit limit.' });
console.log((await ops.runs.wait(started.runId)).outcome);   // credited
```

The workflow, its agent and its tools are records the team builds in the console or through the same API; see
[Agents and workflows](../../console/agents-and-workflows.md).
