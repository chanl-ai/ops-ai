# Demo script

Status: current for the local stack. Every scenario below is a line of `make demo-walk`, on the fake model.

## Before the demo

1. `make up DEMO_MODEL=fake` starts everything and makes the first admin (`.run/dev-admin.env`).
   `DEMO_MODEL=<model id>` puts document reads and guardrail checks on a real OpenAI model; the agents' alias stays on
   the fake.
2. `make sample-team` installs Customer Operations (`scripts/sample-team/sample-team.json`). A second run makes nothing.
3. `make demo-walk` proves every scenario (about a minute). Every line must be PASS.
4. For a clean console, start from an empty database: `make reset-db CONFIRM=yes && make up DEMO_MODEL=fake &&
   make sample-team`. The install puts back everything the demo needs.

Sign in at <http://localhost:3016> with the people's password (`OPS_DEMO_PASSWORD` in `.run/dev-admin.env`): Alex
Morgan (alex.morgan@harborpine.example) asks the questions, Riley Chen (riley.chen@harborpine.example) approves.

## The scenarios

| | Where | Do | The viewer sees |
|---|---|---|---|
| a | Chat, Dispute Desk | "What evidence does a duplicate charge dispute need?" | The Dispute evidence checklist skill loads, then an answer citing the Card dispute handbook |
| b | Chat, Dispute Desk | "Should the customer buy shares in Northline Electronics with the refund?" | Refused at once by the No investment advice guardrail |
| c | Chat, Dispute Desk | "Can you pull up Jordan Whitfield's accounts? He is disputing a 482.10 CAD charge from Northline Electronics that never arrived." | Tool cards for search_customers and list_accounts, then his chequing account CHQ-1003 |
| d | Chat, Levy Desk | "Place a hold of 50.00 CAD on Marcus Bell's chequing account CHQ-2219 for the restraining notice." | An approval card for the hold. Riley approves (password again for the step-up); the reply names the hold |
| e | Terminal, then the console | `make demo-walk`, then open Cases, Human Tasks and <http://localhost:8025> | The sender thanked at once, a case per debtor, a hold worked out by code, each reply approved by Riley, the replies in Mailpit |

## If something fails

- A FAIL names the step; `make health` names what is down and `make logs SVC=<name>` shows the service's log.
- Mail or bank calls time out after moving networks: `make up` restarts what reaches the fakes, and `make sample-team`
  adds this machine's new address to the egress list.
- A reply says it could not check the guardrails: models-service is unreachable; `make health`.
