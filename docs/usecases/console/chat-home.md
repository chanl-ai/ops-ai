# Staff start, follow and finish their work in chat

Status: current. Id: `uc-469`. Service: `console` with `agents-service`. Layers: ui. Card: c-469.

A person signs in to Chat's home in the Focus layout: the composer, four suggested starts and what needs them, with the
console sidebar folded to its icon rail. The team's default agent answers with cards drawn from the records themselves
(case, Human Task, run, workflow start), and the card's buttons act as the person through the record's own route.

## Preconditions

| Needs | How |
|---|---|
| The demo stack with platform sign-in and a worker | `withUiStack(..., { platform: true, demo: true })`, `stack.startWorker` |
| James and Maya (approver), password `northfield-demo` | The platform seed |
| A card dispute waiting for its provisional credit decision | The script saves the demo's card dispute and James starts it |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Maya signs in | She lands on /chat, the sidebar folded, four starts |
| 2 | She presses "What needs me today" | The answer carries the dispute's Human Task as a card with Approve, values in words |
| 3 | She approves from the card, signing in again if the task asks | The card says so and the run leaves the decision step |
| 4 | She asks for the run | The run card no longer waits for a person |
| 5 | She reloads | The task card reads "Approved by …" with no buttons |
| 6 | She opens Cases | The sidebar is back |
| 7 | Throughout | No page error |

The non-vacuous check is step 5: the card is drawn from the record on every read, so a decided task never offers its
buttons again.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-469-ui.mjs` | passing |
