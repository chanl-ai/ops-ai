# The demo walk

Status: current. Id: `uc-140`. Service: `console` and every service behind it. Layers: ui.

The demo runs the console on the shared stack. Each part of the demo used to be proven separately, so a page could be
empty or broken on screen while its API test passed. This use case walks the whole demo in a browser on :3016, as a
person would, and reports each part on its own.

## Preconditions

| Needs | How |
|---|---|
| The shared stack, signed in through platform-service | `make up AUTH=platform` |
| The chat alias on the model the demo uses | whatever the stack serves; a run makes a few dozen model calls, so run it once, at the end |

James builds in Operations, Omar approves for Fraud Operations, Maya approves in Operations.

## Steps and expected results

The scenarios of `docs/console/demo-script.md`, in its order. `UC140_FROM=c` resumes a walk cut short and
`UC140_ONLY=e,f` runs some, so a rerun does not repeat real model calls.

| # | Step | Expected |
|---|---|---|
| a | James asks Advisor's Helper to compare Savings Plus and Money Market for a client who lost her job | The hardship skill loads; the answer cites Retail Product Sheet |
| b | He asks the Savings Plus rate against Money Market | 3.10 against 3.65 or 3.90, cited |
| b | He asks whether his client should buy Northfield shares | Refused, naming the No investment advice guardrail |
| c | He asks what Priya Natarajan has with the bank | search_customers, then get_customer or list_accounts, her account (BUS-7781), no failed call |
| d | He asks Wire Fraud Sentinel to hold wire W-88213; Maya then Omar approve in Human Tasks | Both decisions answer 2xx (step-up when asked) and the chat says the hold is placed |
| e | He filters Workflows › Runs to Customer lookup (seed walk) and opens the newest | Its run page says succeeded with its steps |
| f | He asks the advisor to run the customer summary workflow for Priya | The workflow tool card opens its run page |
| g | `make demo-mailbox` emails a court order notice; Maya follows it | Every mailbox line PASS; three or more court order cases with both deadlines; a `Levy notice` task with the customer and a dollar amount; the reply in Mailpit |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-140-ui.mjs` | passing on the shared stack, 2026-10-18: a, b, d, e, f passed as written; c and g passed on content and their checks were corrected after (BUS- account, en-CA dollar amounts) |
