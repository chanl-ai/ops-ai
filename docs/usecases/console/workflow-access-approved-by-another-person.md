# The requester cannot approve a workflow's access; another person can

Status: current. Id: `uc-053`. Service: `console`. Layers: ui.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA | `make db-up` |
| platform-service's dev seed | James Richardson (builder) and Priya Shah (admin) on Operations, Nadia Petrov (approver) on Security; password `northfield-demo` |
| agents-service's workflows | the ui harness starts it; tools-service reads workflows from it (`OPS_AGENTS_URL`) |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James publishes a module (Nadia approves its review) and requests a workflow's access to its operation | 201 |
| 2 | James opens the module's Access tab | Approve is off on his request: "You requested this; someone else in the owner team decides it" |
| 3 | Priya opens the same tab | Approve is on |
| 4 | Priya approves and confirms | 200; the grant is approved, decided by her |

Who is looking comes from the signed-in session (name and email), never from the workspace lookup's user, which
is a fixed seed value under a real sign-in (`useCurrentPerson`, `hooks/auth-queries.ts`).

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-053-ui.mjs` | passing |

## Non-vacuous check

With the person taken from the workspace lookup again, step 2 fails: under platform sign-in a request records the
requester's email, which never equals the seed name, so Approve is on for the requester too.
