# A banker decides a drafted write inside the chat

Status: current. Id: `uc-072`. Service: `console`. Layers: ui.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA | `make db-up` |
| platform-service's dev seed | Maya Okafor; password `northfield-demo` |
| The scripted model | the ui harness's agents-service; the Wire Fraud Sentinel cites the People knowledge base and drafts wire holds |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Maya opens her thread with the Wire Fraud Sentinel and asks for the daily wire limit | the answer streams in; its citation opens on the passage |
| 2 | She asks for a 24-hour hold on wire W-88213 | an approval card in the thread names the wire, with Approve |
| 3 | She approves | "Confirm it is you" opens before any decision is sent |
| 4 | She confirms with her password | one decision, accepted; the thread resumes with "The hold is in place." |
| 5 | She opens that review in Reviews | "Approved with step-up" and the step-up's fingerprint, as the API records it |
| 6 | She asks for a hold on W-77001 and rejects it with a reason | the card keeps the reason; the agent says the wire continues |

The place-wire-hold operation needs two approvers, so approving it needs a step-up; in dev the person who asked in a
chat may approve it (allow_self_approval_in_chat). The Branch Concierge has no write that needs a step-up and its
knowledge has no passage the scripted model cites, so the Wire Fraud Sentinel carries this flow.

The step-up under platform sign-in re-checks Maya's password at platform-service (an earlier change T022).

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-072-ui.mjs` | passing |

## Non-vacuous check

Step 3 fails if the console sends the decision before the step-up: a decision response is recorded before the dialog.
