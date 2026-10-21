# Demo script

Status: current for the shared stack, 2026-10-18. Every scenario below passed `make demo-sweep` on real OpenAI models.

## Before the demo

1. `make up` starts everything, signs people in through platform-service and binds the models: `default` (agents'
   default and document reads) to gpt-5-mini, `gpt-5.5` (the chat alias the seeded agents name) to gpt-5-nano, and the
   guardrail checks to gpt-4.1-mini. After a reboot or a change of network this is the only step.
2. `make demo-sweep` proves all seven scenarios (about 3 minutes, about a dozen model calls). Every line must be PASS.
3. `make demo-reset CONFIRM=yes` clears every run, chat, Human Task, case and received-email record the sweep and
   earlier sessions left, brings the bank module and the demo knowledge up to date, and ends with
   `open Human Tasks: 0`. Run it last, so the console opens clean. It keeps agents, workflows, tools, knowledge,
   files, people and memories.
4. Do not run `make up RESET=1` or `make reset-db` before a demo. A wiped database loses the fake bank's module and the
   advisor's bank tools, which `make up` does not bring back.

Sign in at <http://localhost:3016>, password `northfield-demo`: James Richardson (j.richardson@northfieldbank.com)
asks the questions, Maya Okafor (m.okafor@northfieldbank.com) approves.

## The scenarios

| | Where | Do | The viewer sees |
|---|---|---|---|
| a | Chat, Advisor's Helper | "My client lost her job. Compare Savings Plus and Money Market for her." | The hardship skill loads, then a comparison citing Retail Product Sheet p.4 |
| b | Chat, Advisor's Helper | "What is the interest rate on Savings Plus, and how does it compare with Money Market?" | "3.10% a year" against Money Market's 3.65% and 3.90%, each with a citation |
| b | Chat, Advisor's Helper | "Should my client buy Northfield shares?" | Refused at once by the No investment advice guardrail |
| c | Chat, Advisor's Helper | "What does Priya Natarajan have with us?" | Tool cards for search_customers, get_customer and list_accounts, then her accounts and balances |
| d | Chat, Wire Fraud Sentinel | "Wire W-88213 for $48,500 went to a payee added today. Put a 24 hour hold on it." | An approval card for the hold. Maya approves (password again for the step-up), then Omar Haddad (o.haddad@northfieldbank.com) from Fraud; the reply says the hold is in place |
| e | Workflows > Runs | Open the latest "Customer lookup (seed walk)" run | Each step with its input and output, ending succeeded |
| f | Chat, Advisor's Helper | "Run the customer summary workflow for Priya Natarajan." | A workflow tool card, then a summary of Priya; the run opens from the card |
| g | Terminal, then the console | `make demo-mailbox`, then open Cases, Human Tasks and <http://localhost:8025> | Three high-priority court order cases, a `Levy notice` Human Task per matched debtor (customer, amount, CAD), the reply in Mailpit |

More answers with a citation, for questions from the room:

- Advisor's Helper: "What is the minimum balance to open Money Market?" answers 25,000.
- Advisor's Helper: "What is the monthly fee on Everyday Chequing, and how is it waived?" answers 11.95, waived with a
  3,000 minimum balance or a payroll deposit.
- Branch Policy: "What is the fee for an outgoing wire transfer?" answers 30.00 domestic and 45.00 international.

## The scanned notice

`make demo-mailbox LOW=1` emails a scan of the same notice. It has no text layer, so it is read by OCR; every field
scores below the floor, and the run stops at "Check the debtors read from the document" on Human Tasks before any case
opens. OCR reads all three debtors correctly, so approving as read opens the same cases as the text notice.

The correction moment: say the court has phoned to reduce Marcus Bell's amount to 3,000. Change his amount on the
check before approving, and his court order task (`Levy notice`) shows 3,000.00 CAD instead of the 3,250.00 the notice
printed. The person corrects the read, and the workflow carries on from the corrected value. A correction naming a
field the read does not have is refused. Status: the API takes the correction (`inputs.edited` on
`POST /reviews/{id}/decision`); the Human Task form for it is still being built.

## If something fails

- `stack: down: …` from demo-mailbox: run `make up` again; `make logs SVC=<name>` shows the service's log.
- Mail or bank calls time out after moving networks: `make up` restarts what reaches the fakes.
- A reply says it could not check the guardrails: models-service or OpenAI is unreachable; `make health`.
