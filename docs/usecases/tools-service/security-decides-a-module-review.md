# Security decides a tool module review

Status: current. Id: `uc-040`. Service: `tools-service`. Layers: api, ui.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA | `make db-up` |
| platform-service's dev seed | James Richardson (builder, Operations), Maya Okafor (approver, Operations), Nadia Petrov (approver, Security), Sam Adeyemi (admin, Security); password `northfield-demo` |
| tools-service and agents-service verifying platform tokens | The scripts start both with `OPS_AUTH_MODE=platform`; the review is a publish request in agents-service's Reviews (c-163) |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Sam (admin on Security) allows the module's host for egress; James creates a module with one operation and requests a security review | 201 or 200; 201 / 200; the version is `in_review` and names a `TMP-` publish request |
| 2 | Nadia lists `view=security_review` | the module, with `pendingReview.requestedBy` James Richardson |
| 3 | James decides his own review in Reviews (`POST /v1/publish-requests/{id}/decision`) | 403 |
| 4 | Maya (approver on Operations) decides it | 403, naming `team_security` |
| 5 | Nadia returns it with no reason | 400 |
| 6 | Nadia approves | 200; Reviews applies it in tools-service, the module is published, and it leaves the view |
| 7 | On a second module Nadia returns it with a reason | 200; the module is back to draft, the reason on the version as its finding |

In the console (ui layer): James's Approval tab says the version waits for Security, links it to Human Tasks and has no
decide form; Maya sees it in Human Tasks and Reviews refuses her; Nadia's return without a reason is stopped in the form
and sends nothing, then she approves in Human Tasks, and the module page shows the review approved by her; the publish
dialog says "What changed" is required.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-040-api.py` | passing |
| ui | `tools-service/scripts/test-uc-040-ui.mjs` | passing |

## Non-vacuous check

Step 4 pairs with step 6: removing the Security-team rule lets Maya's decision through (200). Tokens from platform's
dev sign-in carry `auth_method: dev`; a rule keyed on that alone would also let Maya through, which is the bug the api
layer caught (74f78f2). At the ui layer, the stopped change request pairs with the approval that follows.
