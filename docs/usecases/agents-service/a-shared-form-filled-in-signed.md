# A shared form filled in signed out starts a workflow with knowledge and a tool, a person approves a step, and the run finishes with a record

Status: works in mock mode. Id: `uc-756`. Service: `agents-service`. Layers: api, ui. Mock mode only (no model, a mock upstream).

Short title: A shared form filled in signed out starts a workflow with knowledge and a tool, a person approves a step, and the run finishes with a record

## Story

As a bank customer with a link, I want to ask for a hold on my account without signing in so that a person approves it and the bank records it.

## People

| Person | Role | Does what |
|---|---|---|
| James Richardson | builder | Publishes the workflow and shares it as a form |
| Visitor | no account | Opens the link and fills the form |
| Maya Okafor | approver | Approves the hold in Human Tasks |

## In this example

In this example the visitor asks for a hold on CHQ-2219 and asks for the daily wire limit. It assumes the account module (a read and a write that needs approval) is published and the team's write approvals are on.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A signed-out visitor sends the shared form, a person approves the hold, the hold reaches the bank once and the run finishes held with a case | api | 1-8 | 8 |
| S2 | The same flow through the hosted form page and Human Tasks | ui | 1-4 | 4 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | The builder shares the workflow as a form | A link with a slug and a token |
| 2 | A visitor with no session opens the link; a wrong token submits | The form opens; the wrong token is refused |
| 3 | The visitor sends the form | Received |
| 4 | The runs are read | A run created by the form, in the team |
| 5 | The run is read while it waits | It read the account and searched the knowledge source, and waits in Human Tasks |
| 6 | The mock bank is read | No hold while the review waits (the non-vacuous check) |
| 7 | A person of the team approves | 200 |
| 8 | The run and the bank are read | One hold, outcome held, a case opened |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-756-api.py` | passes in mock mode |
| ui | `agents-service/scripts/test-uc-756-ui.mjs` | passes in mock mode |

## Non-vacuous check

Step 6: the bank holds nothing while the review waits, so the single hold in step 8 comes from the approval.
